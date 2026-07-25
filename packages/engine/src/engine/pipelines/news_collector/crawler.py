"""基于 config 的列表提取 + 翻页 + 正文提取（spec §3.5, §3.6）"""

from __future__ import annotations

import re
from typing import Any

from playwright.async_api import Page


async def try_extract_items(page: Page, list_config: dict) -> list[dict]:
    """基于 list config 提取当前页的新闻条目。

    Returns: [{title, date, url}, ...] 空列表表示提取失败。
    """
    mode = list_config["mode"]
    fields = list_config["fields"]

    if mode == "script":
        # JS 代码块直接返回数组
        result = await page.evaluate(fields["items"])
        if not result:
            return []
        return [
            {"title": it.get("title", ""), "date": it.get("date"), "url": it.get("url", "")}
            for it in result
        ]

    # mode == "selectors"
    container_sel = fields.get("container", "")
    item_sel = fields.get("item", "li")
    full_sel = f"{container_sel} > {item_sel}" if container_sel else item_sel

    items_loc = page.locator(full_sel)
    count = await items_loc.count()
    if count == 0:
        return []

    results = []
    for i in range(count):
        el = items_loc.nth(i)
        # 标题
        title_sel = fields.get("title", "a")
        title_el = await el.query_selector(title_sel)
        title = (await title_el.inner_text()).strip() if title_el else ""

        # 链接
        link_sel = fields.get("link", "a")
        link_el = await el.query_selector(link_sel)
        link_attr = fields.get("link_attr", "href")
        url = (await link_el.get_attribute(link_attr)) if link_el else ""

        # 日期
        date = None
        date_sel = fields.get("date")
        if date_sel:
            date_el = await el.query_selector(date_sel)
            if date_el:
                date_text = (await date_el.inner_text()).strip()
                # 尝试标准化日期
                m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", date_text)
                if m:
                    date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        # 日期 fallback：从 URL 中提取
        if not date and url:
            m = re.search(r"/(\d{4})(\d{2})/.*?(\d{4})(\d{2})(\d{2})", url)
            if m:
                date = f"{m.group(3)}-{m.group(4)}-{m.group(5)}"
            else:
                m = re.search(r"/(\d{4})(\d{2})(\d{2})/", url)
                if m:
                    date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

        if title or url:
            results.append({"title": title, "date": date, "url": url or ""})

    return results


async def go_next_page(page: Page, pagination_config: dict | None) -> bool:
    """翻到下一页。返回 True 表示成功，False 表示无下一页。"""
    if pagination_config is None:
        return False

    mode = pagination_config["mode"]
    fields = pagination_config["fields"]

    if mode == "script":
        next_url = await page.evaluate(fields.get("next_url", "() => null"))
        if not next_url:
            return False
        await page.goto(next_url, wait_until="domcontentloaded", timeout=60000)
        return True

    # mode == "selectors"
    # 优先 url_pattern
    url_pattern = fields.get("url_pattern")
    if url_pattern:
        # 从当前 URL 推断下一页
        current = page.url
        m = re.search(r"index_(\d+)\.html", current)
        if m:
            next_page = int(m.group(1)) + 1
            next_url = re.sub(r"index_\d+\.html", f"index_{next_page}.html", current)
        else:
            next_url = current.rstrip("/").rsplit("/", 1)[0] + "/" + url_pattern.replace("{page}", "1")
        await page.goto(next_url, wait_until="domcontentloaded", timeout=60000)
        return True

    # 点击下一页按钮
    next_sel = fields.get("next", "")
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


async def try_extract_detail(page: Page, detail_config: dict | None) -> dict | None:
    """基于 detail config 提取正文。返回 {title, content, date, source} 或 None。"""
    if detail_config is None:
        return None

    mode = detail_config["mode"]
    fields = detail_config["fields"]

    if mode == "script":
        result = {}
        for key in ("title", "content", "date", "source"):
            code = fields.get(key)
            if code:
                result[key] = await page.evaluate(code)
            else:
                result[key] = ""
        if not result.get("content"):
            return None
        return result

    # mode == "selectors"
    result = {}
    for key in ("title", "content", "date", "source"):
        sel = fields.get(key)
        if sel:
            loc = page.locator(sel)
            if await loc.count() > 0:
                result[key] = (await loc.first.inner_text()).strip()
            else:
                result[key] = ""
        else:
            result[key] = ""

    if not result.get("content"):
        return None

    # 日期标准化
    if result.get("date"):
        m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", result["date"])
        if m:
            result["date"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    return result
