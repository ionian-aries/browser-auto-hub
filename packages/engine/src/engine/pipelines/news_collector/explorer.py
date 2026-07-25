"""探索 Agent：LLM 分析 DOM → 生成/修复 config（spec §7）"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.async_api import Page

from .config_store import save_source_config
from .crawler import try_extract_items, try_extract_detail
from .llm_client import call_llm_json

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_EXPLORER_PROMPT = (_PROMPTS_DIR / "explorer.txt").read_text(encoding="utf-8")

# Config JSON schema 描述（注入到 prompt 中）
_CONFIG_JSON_SCHEMA = """
{
  "list": {
    "mode": "selectors" | "script",
    "fields": {
      // selectors: {container, item, title, date, link, link_attr}
      // script: {items: "JS代码，返回 [{title, date, url}, ...]"}
    }
  },
  "pagination": null | {
    "mode": "selectors" | "script",
    "fields": {
      // selectors: {next: "CSS选择器", next_text: "按钮文本"}
      // script: {next_url: "JS代码，返回下一页URL或null"}
    }
  },
  "detail": {
    "mode": "selectors" | "script",
    "fields": {
      // selectors: {title, content, date, source} — 均为 CSS 选择器
      // script: {title, content, date, source} — 均为 JS 代码
    }
  }
}
"""

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


def _build_prompt(
    url: str,
    source_name: str,
    page_type: str,
    dom_json: str,
    repair_hint: str,
) -> str:
    """构建 LLM prompt。"""
    prompt = _EXPLORER_PROMPT.replace("{url}", url)
    prompt = prompt.replace("{source_name}", source_name)
    prompt = prompt.replace("{page_type}", page_type)
    prompt = prompt.replace("{config_json_schema}", _CONFIG_JSON_SCHEMA)
    prompt = prompt.replace("{repair_hint}", repair_hint)
    prompt += f"\n\n## DOM 结构摘要\n```json\n{dom_json}\n```"
    return prompt


async def explore_list(
    page: Page,
    source_name: str,
    base_url: str,
    max_retries: int = 3,
) -> dict | None:
    """探索列表页 DOM → LLM 生成 config → 验证 → 存文件。

    Returns: 可用的 config dict 或 None（失败）。
    """
    dom_summary = await page.evaluate(_DOM_SUMMARY_JS)
    dom_json = json.dumps(dom_summary, ensure_ascii=False, indent=2)

    repair_hint = ""
    for attempt in range(max_retries):
        prompt = _build_prompt(page.url, source_name, "list", dom_json, repair_hint)

        try:
            config = await call_llm_json(prompt)
        except Exception:
            repair_hint = (
                "\n## 上次尝试失败\n"
                "LLM 返回的内容无法解析为 JSON，请确保严格输出 JSON 格式。"
            )
            continue

        # 验证：用生成的 config 在当前页面试跑
        list_config = config.get("list")
        if not list_config or not list_config.get("fields"):
            repair_hint = (
                "\n## 上次尝试失败\n"
                "生成的 config 缺少 list.fields，请确保输出完整的配置。"
            )
            continue

        items = await try_extract_items(page, list_config)
        if items:
            # 成功 → 存文件
            save_source_config(source_name, base_url, config)
            return config

        repair_hint = (
            f"\n## 上次尝试失败\n"
            f"你生成的配置提取结果为空（items 数量: {len(items)}）。\n"
            f"请重新分析 DOM 结构，修正选择器或 JS 代码。"
        )

    return None


async def explore_detail(
    page: Page,
    url: str,
    max_retries: int = 3,
) -> dict | None:
    """探索详情页 DOM → LLM 生成 detail config → 验证。

    Returns: 可用的 detail config dict 或 None。
    """
    dom_summary = await page.evaluate(_DOM_SUMMARY_JS)
    dom_json = json.dumps(dom_summary, ensure_ascii=False, indent=2)

    repair_hint = ""
    for attempt in range(max_retries):
        prompt = _build_prompt(url, "", "detail", dom_json, repair_hint)

        try:
            config = await call_llm_json(prompt)
        except Exception:
            repair_hint = "\n## 上次尝试失败\nLLM 返回无法解析为 JSON。"
            continue

        detail_config = config.get("detail") or config
        if not detail_config.get("fields"):
            repair_hint = "\n## 上次尝试失败\n缺少 detail.fields。"
            continue

        result = await try_extract_detail(page, detail_config)
        if result and result.get("content"):
            return detail_config

        repair_hint = (
            "\n## 上次尝试失败\n"
            "提取到的正文为空。请修正 content 选择器或 JS 代码。"
        )

    return None
