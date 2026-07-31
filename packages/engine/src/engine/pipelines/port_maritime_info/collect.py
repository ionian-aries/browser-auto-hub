"""列表采集 — 遍历信源所有 entry，翻页采集标题列表。

产出: [{title, link_url, doc_date, website_name}, ...]
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin

from playwright.async_api import Page


# ── 主入口 ──
async def crawl_list(
    page: Page,
    sources: list[dict],
    start_date: str,
    end_date: str,
    config: dict,
    log,
) -> list[dict]:
    """遍历所有信源的所有 entry，每个 entry 在独立 tab 中并行采集。"""
    _validate_dates(start_date, end_date)

    max_pages = config.get("max_pages", 50)
    rate_limit_ms = config.get("rate_limit_ms", 2000)
    page_timeout = config.get("page_load_timeout", 120000)
    browser_tabs = min(max(config.get("browser_tabs", 5), 1), 5)

    ctx = page.context
    all_items: list[dict] = []
    results_lock = asyncio.Lock()
    tab_sem = asyncio.Semaphore(browser_tabs)

    async def _crawl_entry(
        source_name: str,
        entry_name: str,
        entry_url: str,
        list_cfg: dict,
        pagination_cfg: dict | None,
    ) -> None:
        """单 entry 采集 worker：开新 tab → 翻页采集 → 关闭 tab。"""
        container_sel = list_cfg.get("fields", {}).get("container", "")
        async with tab_sem:
            tab = await ctx.new_page()
            try:
                await log.info("crawl", f"{entry_name}: {entry_url}")

                await tab.goto(entry_url, wait_until="commit", timeout=page_timeout)
                if container_sel:
                    try:
                        await tab.wait_for_selector(container_sel, timeout=15000)
                    except Exception:
                        await log.warn(
                            "crawl", f"[{entry_name}] 容器未出现: {container_sel}"
                        )

                items = await _crawl_pages(
                    tab, list_cfg, pagination_cfg,
                    container_sel, entry_url,
                    start_date, end_date,
                    max_pages, rate_limit_ms, log,
                )

                for it in items:
                    it["website_name"] = source_name

                await log.info("crawl", f"[{entry_name}] → {len(items)} 条")

                async with results_lock:
                    all_items.extend(items)

            except Exception as e:
                await log.error("crawl", f"[{entry_name}] 采集失败: {e}")
            finally:
                await tab.close()

    # 收集所有 entry 任务
    tasks = []
    for source in sources:
        source_name = source.get("source_name", "未知")
        source_configs = source.get("configs", {})

        await log.info("crawl", f"---- {source_name} ----")

        for entry in source.get("entries", []):
            entry_name = entry.get("entry_name", "未命名")
            entry_url = entry.get("url", "")

            # entry 级覆盖信源级配置
            list_cfg = entry.get("list") or source_configs.get("list", {})
            pagination_cfg = (
                entry.get("pagination")
                if "pagination" in entry
                else source_configs.get("pagination")
            )

            tasks.append(_crawl_entry(
                source_name, entry_name, entry_url,
                list_cfg, pagination_cfg,
            ))

    # 所有 entry 并行执行
    await asyncio.gather(*tasks)

    # 跨 entry 全局 URL 去重（保序留先；同 URL 多 entry 重复会导致后续并发写同一 db_id）
    seen: set[str] = set()
    unique_items: list[dict] = []
    for it in all_items:
        url = it.get("link_url", "")
        if url and url not in seen:
            seen.add(url)
            unique_items.append(it)
    dup = len(all_items) - len(unique_items)
    if dup:
        await log.info("crawl", f"跨 entry 重复 URL 去重: {dup} 条")

    await log.info("crawl", f"共采集: {len(unique_items)} 条")

    # 按信源分组列明细（标题 + 链接），供人工核对覆盖面
    by_source: dict[str, list[dict]] = {}
    for it in unique_items:
        by_source.setdefault(it.get("website_name", ""), []).append(it)
    lines = ["采集明细:"]
    for name, items in by_source.items():
        lines.append(f"【{name}】{len(items)} 条:")
        for it in items:
            lines.append(f"  · {it.get('title', '')[:40]}")
            lines.append(f"    链接: {it.get('link_url', '')}")
    await log.info("crawl", "\n".join(lines))

    return unique_items


# ── 入参校验 ──
_REL_DATE_PAT = re.compile(r"^today(?:-(\d+))?$")


def resolve_date_expr(value: str) -> str:
    """相对日期表达式解析：`today` / `today-N` → 本地日期 YYYY-MM-DD；其余原样透传。

    解析发生在每次执行时刻（非定时任务创建时刻），cron 存表达式即可滚动窗口。
    透传值由 _validate_dates 兜底校验（含非字符串类型混淆与无法识别的伪表达式）。
    """
    if not isinstance(value, str):
        return value
    m = _REL_DATE_PAT.fullmatch(value.strip())
    if not m:
        return value
    n = int(m.group(1) or 0)
    return (datetime.now().date() - timedelta(days=n)).isoformat()


def _validate_dates(start_date: str, end_date: str) -> None:
    """校验日期参数格式 YYYY-MM-DD 且 start <= end。"""
    pat = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for name, val in [("start_date", start_date), ("end_date", end_date)]:
        if not isinstance(val, str) or not pat.match(val):
            raise ValueError(
                f"{name} 格式错误: {val!r}，要求 YYYY-MM-DD 或 today / today-N"
            )
    if start_date > end_date:
        raise ValueError(
            f"start_date({start_date}) > end_date({end_date})"
        )


# ── 翻页编排 ──
async def _crawl_pages(
    page: Page,
    list_cfg: dict,
    pagination_cfg: dict | None,
    container_sel: str,
    entry_url: str,
    start_date: str,
    end_date: str,
    max_pages: int,
    rate_limit_ms: int,
    log,
) -> list[dict]:
    """翻页循环: 提取原始条目 → 日期边界 → 过滤 → 翻页。

    日期边界用未过滤的原始日期判断: min(raw_dates) < start_date → 停止。
    """
    all_items: list[dict] = []
    seen_urls: set[str] = set()
    pending_verify = False
    fields = list_cfg.get("fields", {})

    for _ in range(max_pages):
        raw_items = await _extract_selectors(page, fields, entry_url)
        raw_dates = [it["doc_date"] for it in raw_items if it.get("doc_date")]

        # 按日期范围过滤
        items = [
            it for it in raw_items
            if it.get("doc_date") and start_date <= it["doc_date"] <= end_date
        ]

        # 去重（正常网站不重复，此为防止异常的保险措施）
        new_items = [it for it in items if it["link_url"] not in seen_urls]

        # 翻页后验证: 容器存在但无原始条目 → 页面未加载成功
        if pending_verify:
            if not raw_items:
                await log.warn("crawl", "翻页后页面未加载，停止")
                break
            pending_verify = False

        # 收集符合范围的条目
        all_items.extend(new_items)
        seen_urls.update(it["link_url"] for it in new_items)

        # 日期边界: 原始条目中有条目 < start_date → 后续只会更旧
        if raw_dates and min(raw_dates) < start_date:
            break

        # 翻页
        if not pagination_cfg or not await _go_next_page(page, pagination_cfg):
            break
        if container_sel:
            try:
                await page.wait_for_selector(container_sel, timeout=15000)
            except Exception:
                break

        pending_verify = True
        await asyncio.sleep(rate_limit_ms / 1000)

    return all_items


# ── DOM 提取 ──
async def _extract_selectors(
    page: Page, fields: dict, entry_url: str,
) -> list[dict]:
    """通过 CSS 选择器逐 item 提取 {title, date, url}，无日期的直接丢弃。"""
    container = fields.get("container", "")
    item_sel = fields.get("item", "li")
    full_sel = f"{container} > {item_sel}" if container else item_sel

    locator = page.locator(full_sel)
    count = await locator.count()
    if count == 0:
        return []

    title_sel = fields.get("title", "a")
    date_sel = fields.get("date")
    link_cfg = fields.get("link", {})
    link_sel = link_cfg.get("sel", "a") if isinstance(link_cfg, dict) else link_cfg
    link_attr = link_cfg.get("attr", "href") if isinstance(link_cfg, dict) else "href"

    items = []
    for i in range(count):
        el = locator.nth(i)

        title_loc = el.locator(title_sel)
        title = (
            (await title_loc.first.inner_text()).strip()
            if await title_loc.count() > 0
            else ""
        )

        link_loc = el.locator(link_sel)
        url = (
            (await link_loc.first.get_attribute(link_attr))
            if await link_loc.count() > 0
            else ""
        ) or ""

        # 日期: 选择器文本 → URL 兜底
        date = None
        if date_sel:
            date_loc = el.locator(date_sel)
            if await date_loc.count() > 0:
                date = _parse_date(
                    (await date_loc.first.inner_text()).strip(), url
                )
        if not date and url:
            date = _parse_date("", url)
        if not date:
            continue

        if url and not url.startswith("http"):
            url = urljoin(entry_url, url)

        if title or url:
            items.append({"title": title, "link_url": url, "doc_date": date})

    return items


# ── 日期解析 ──
def _parse_date(date_text: str, url: str = "") -> str | None:
    """从文本或 URL 中解析日期，返回 YYYY-MM-DD 或 None。"""
    if date_text:
        # 标准格式: 2026-07-24, 2026/07/24, 2026.07.24
        m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", date_text)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        # 中文格式: 2026年07月22日
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_text)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    if url:
        m = re.search(r"/(\d{4})(\d{2})/.*?(\d{4})(\d{2})(\d{2})", url)
        if m:
            return f"{m.group(3)}-{m.group(4)}-{m.group(5)}"
        m = re.search(r"/(\d{4})(\d{2})(\d{2})/", url)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


# ── 翻页 ──
async def _go_next_page(page: Page, pagination_cfg: dict) -> bool:
    """点击下一页按钮。返回 True=成功，False=无按钮或失败。"""
    next_sel = pagination_cfg.get("fields", {}).get("next", "")
    if not next_sel:
        return False

    btn = page.locator(next_sel)
    if await btn.count() == 0:
        return False

    await btn.first.click()
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass
    return True
