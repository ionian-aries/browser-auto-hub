"""列表/详情提取 + 翻页（class-based, 与 collector.py 接口对齐）"""

from __future__ import annotations

import re

from playwright.async_api import Page


class Crawler:
    """基于 config 的页面提取器。

    支持两种模式：
    - selectors: CSS 选择器提取
    - script: JS 代码块提取
    """

    def __init__(self, page: Page, logger):
        self.page = page
        self.logger = logger

    async def extract_list(self, merged: dict) -> list[dict]:
        """从当前页提取文章列表。返回 [{title, date, url}, ...]。"""
        list_cfg = merged.get("list")
        if not list_cfg:
            return []

        mode = list_cfg.get("mode", "selectors")
        fields = list_cfg.get("fields", {})

        if mode == "script":
            code = fields.get("items", "")
            if not code:
                return []
            try:
                result = await self.page.evaluate(code)
                if not result:
                    return []
                return [
                    {
                        "title": it.get("title", ""),
                        "date": it.get("date"),
                        "url": it.get("url", ""),
                    }
                    for it in result
                    if it.get("title") or it.get("url")
                ]
            except Exception:
                return []

        # selectors 模式
        container_sel = fields.get("container", "")
        item_sel = fields.get("item", "li")
        full_sel = f"{container_sel} > {item_sel}" if container_sel else item_sel

        items_loc = self.page.locator(full_sel)
        count = await items_loc.count()
        if count == 0:
            return []

        results = []
        for i in range(count):
            el = items_loc.nth(i)

            title_sel = fields.get("title", "a")
            title_el = await el.query_selector(title_sel)
            title = (await title_el.inner_text()).strip() if title_el else ""

            link_sel = fields.get("link", "a")
            link_el = await el.query_selector(link_sel)
            link_attr = fields.get("link_attr", "href")
            url = (await link_el.get_attribute(link_attr)) if link_el else ""

            date = None
            date_sel = fields.get("date")
            if date_sel:
                date_el = await el.query_selector(date_sel)
                if date_el:
                    date_text = (await date_el.inner_text()).strip()
                    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", date_text)
                    if m:
                        date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
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

    async def has_next_page(self, merged: dict) -> bool:
        """检查是否存在下一页。"""
        pag = merged.get("pagination")
        if not pag:
            return False
        fields = pag.get("fields", {})
        if pag.get("mode") == "script":
            return True
        next_sel = fields.get("next", "")
        if not next_sel:
            return bool(fields.get("url_pattern"))
        btn = self.page.locator(next_sel)
        return (await btn.count()) > 0

    async def goto_next_page(self, merged: dict) -> bool:
        """翻到下一页。返回 True 表示成功。"""
        pag = merged.get("pagination")
        if not pag:
            return False
        mode = pag.get("mode", "selectors")
        fields = pag.get("fields", {})

        if mode == "script":
            next_url = await self.page.evaluate(fields.get("next_url", "() => null"))
            if not next_url:
                return False
            await self.page.goto(next_url, wait_until="domcontentloaded", timeout=60000)
            return True

        url_pattern = fields.get("url_pattern")
        if url_pattern:
            current = self.page.url
            m = re.search(r"index_(\d+)\.html", current)
            if m:
                next_page = int(m.group(1)) + 1
                next_url = re.sub(r"index_\d+\.html", f"index_{next_page}.html", current)
            else:
                next_url = current.rstrip("/").rsplit("/", 1)[0] + "/" + url_pattern.replace("{page}", "1")
            await self.page.goto(next_url, wait_until="domcontentloaded", timeout=60000)
            return True

        next_sel = fields.get("next", "")
        if not next_sel:
            return False
        btn = self.page.locator(next_sel)
        if await btn.count() == 0:
            return False
        await btn.first.click()
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
        return True

    async def extract_detail(self, merged: dict) -> dict:
        """从当前详情页提取正文。返回 {title, content, date, source}。"""
        detail_cfg = merged.get("detail")
        if not detail_cfg:
            return {"title": "", "content": "", "date": "", "source": ""}

        mode = detail_cfg.get("mode", "selectors")
        fields = detail_cfg.get("fields", {})

        if mode == "script":
            result = {}
            for key in ("title", "content", "date", "source"):
                code = fields.get(key)
                if code:
                    result[key] = await self.page.evaluate(code)
                else:
                    result[key] = ""
            return result

        # selectors 模式
        result = {}
        for key in ("title", "content", "date", "source"):
            sel = fields.get(key)
            if sel:
                loc = self.page.locator(sel)
                if await loc.count() > 0:
                    result[key] = (await loc.first.inner_text()).strip()
                else:
                    result[key] = ""
            else:
                result[key] = ""

        if result.get("date"):
            m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", result["date"])
            if m:
                result["date"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

        return result
