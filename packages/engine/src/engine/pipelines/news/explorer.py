"""探索 Agent：LLM 分析 DOM → 生成/修复 config（class-based, 与 collector.py 接口对齐）"""

from __future__ import annotations

import json

from playwright.async_api import Page

from engine.pipelines.news.prompts import EXPLORER_SYSTEM, EXPLORER_USER


# 通用 DOM 摘要 JS（零假设，通用结构分析）
_DOM_SUMMARY_JS = r"""
() => {
    const NOISE_TAGS = new Set([
        'SCRIPT','STYLE','NOSCRIPT','SVG','CANVAS',
        'NAV','HEADER','FOOTER','IFRAME','EMBED','OBJECT'
    ]);
    const NOISE_KW = [
        'nav','menu','sidebar','footer','header','breadcrumb',
        'copyright','ad-','ads','banner','toolbar','cookie',
        'modal','popup','tooltip'
    ];
    function isNoise(el) {
        if (NOISE_TAGS.has(el.tagName)) return true;
        const cls = (typeof el.className === 'string' ? el.className : '').toLowerCase();
        const id = (el.id || '').toLowerCase();
        return NOISE_KW.some(kw => (cls + ' ' + id).includes(kw));
    }
    function summarize(el, depth, maxNodes) {
        if (!el || !el.tagName || depth > 6 || isNoise(el)) return null;
        try {
            const s = window.getComputedStyle(el);
            if (s.display === 'none' || s.visibility === 'hidden') return null;
        } catch(e) {}
        const node = { t: el.tagName.toLowerCase() };
        if (el.id) node.id = el.id;
        if (el.className && typeof el.className === 'string') {
            const cls = el.className.trim().replace(/\s+/g, ' ');
            if (cls) node.c = cls;
        }
        const firstLink = el.querySelector('a[href]');
        if (firstLink) {
            node.has_link = true;
            const href = firstLink.getAttribute('href') || '';
            if (href) node.link_sample = href.substring(0, 120);
        }
        const children = Array.from(el.children).filter(c => !isNoise(c));
        if (children.length === 0) {
            const text = (el.innerText || '').trim();
            if (text) node.txt = text.substring(0, 80);
        } else {
            node.n = children.length;
            if (depth < 6 && maxNodes.remaining > 0) {
                const ch = [];
                for (const child of children) {
                    if (maxNodes.remaining <= 0) break;
                    maxNodes.remaining--;
                    const s = summarize(child, depth + 1, maxNodes);
                    if (s) ch.push(s);
                }
                if (ch.length > 0) node.ch = ch;
            }
        }
        return node;
    }
    function findRepeating() {
        const out = [];
        const seen = new Set();
        for (const el of document.querySelectorAll('*')) {
            if (isNoise(el)) continue;
            const ch = Array.from(el.children).filter(c => !isNoise(c));
            if (ch.length < 3) continue;
            const groups = {};
            for (const c of ch) { (groups[c.tagName] = groups[c.tagName] || []).push(c); }
            const best = Object.entries(groups).sort((a,b) => b[1].length - a[1].length)[0];
            if (!best || best[1].length < 3) continue;
            const key = el.tagName + '|' + (el.className||'') + '|' + best[0];
            if (seen.has(key)) continue;
            seen.add(key);
            const withLinks = best[1].filter(c => c.querySelector('a[href]')).length;
            if (withLinks < 3) continue;
            out.push({
                container: { tag: el.tagName.toLowerCase(), id: el.id || undefined,
                    c: (typeof el.className === 'string' ? el.className.trim() : '') || undefined },
                groupSize: best[1].length, groupWithLinks: withLinks,
                samples: best[1].slice(0,3).map(c => {
                    const a = c.querySelector('a[href]');
                    return { tag: c.tagName.toLowerCase(),
                        text: (c.innerText||'').trim().substring(0,80),
                        link_href: a ? (a.getAttribute('href')||'').substring(0,120) : undefined };
                })
            });
        }
        return out.sort((a,b) => b.groupWithLinks - a.groupWithLinks).slice(0,5);
    }
    function findPagination() {
        const out = [];
        for (const el of document.querySelectorAll('a, button, [onclick]')) {
            const text = (el.innerText||'').trim();
            const href = el.getAttribute('href') || '';
            const onclick = el.getAttribute('onclick') || '';
            if (/\d/.test(text) || /[下><»]|next|prev|page/i.test(text) ||
                /page|index_/.test(href) || /page|goPage/i.test(onclick)) {
                out.push({ tag: el.tagName.toLowerCase(),
                    c: (typeof el.className === 'string' ? el.className.trim() : '') || undefined,
                    text: text.substring(0,40),
                    href: href ? href.substring(0,120) : undefined,
                    onclick: onclick ? onclick.substring(0,100) : undefined });
            }
        }
        return out.slice(0, 15);
    }
    const maxNodes = { remaining: 300 };
    return {
        url: location.href, title: document.title,
        body: summarize(document.body, 0, maxNodes),
        repeating_structures: findRepeating(),
        pagination_candidates: findPagination(),
    };
}
"""


_CONFIG_SCHEMA_HINT = """
{
  "list": {
    "mode": "selectors" | "script",
    "fields": { "container": "", "item": "li", "title": "a", "date": "span", "link": "a", "link_attr": "href" }
  },
  "pagination": null | {
    "mode": "selectors" | "script",
    "fields": { "next": "a.next", "next_text": "下一页" }
  },
  "detail": {
    "mode": "selectors" | "script",
    "fields": { "title": "h1", "content": "div.content", "date": "span.date", "source": "span.src" }
  }
}
"""


class Explorer:
    """探索 Agent：LLM 分析页面 DOM → 生成/修复采集 config。"""

    def __init__(self, page: Page, logger, llm_caller=None, max_retries: int = 3):
        self.page = page
        self.logger = logger
        self.llm_caller = llm_caller
        self.max_retries = max_retries

    async def explore(
        self, source_name: str, entry_name: str, url: str
    ) -> dict | None:
        """探索当前页面 DOM → LLM 生成 config → 验证。

        成功返回可用 config dict，失败返回 None。
        """
        if not self.llm_caller:
            await self.logger.warn("explorer", "LLM 未配置，跳过探索")
            return None

        dom_summary = await self.page.evaluate(_DOM_SUMMARY_JS)
        dom_json = json.dumps(dom_summary, ensure_ascii=False, indent=2)

        repair_hint = ""
        for attempt in range(self.max_retries):
            user = EXPLORER_USER.format(
                url=url,
                source_name=source_name,
                entry_name=entry_name,
                dom_summary=dom_json,
                config_schema=_CONFIG_SCHEMA_HINT,
                repair_hint=repair_hint,
            )
            resp = await self.llm_caller(EXPLORER_SYSTEM, user)
            if not resp:
                repair_hint = "\n上次尝试：LLM 返回为空。"
                continue
            try:
                config = _parse_llm_json(resp)
            except Exception:
                repair_hint = "\n上次尝试：LLM 返回无法解析为 JSON。"
                continue

            # 验证 config 结构
            if not config.get("list", {}).get("fields"):
                repair_hint = "\n上次尝试：config 缺少 list.fields。"
                continue

            await self.logger.step(
                "explorer", f"探索生成 config（第{attempt + 1}次尝试），验证中..."
            )
            return config

        return None


def _parse_llm_json(text: str):
    """从 LLM 返回文本中提取 JSON。"""
    import re
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()
    return json.loads(text)
