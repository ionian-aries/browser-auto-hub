#!/usr/bin/env bash
# 港航采集 真实 Chromium 可达性探针 v4
# 在容器内启动真实 Chromium（与 pipeline 同款），对每个 entry 做：
#   1. page.goto(url, wait_until="commit")  — 与 collect.py 完全一致
#   2. page.wait_for_selector(container_sel) — 与 collect.py 完全一致
# 目的：定位「打不开」的真实根因
#   - GOTO FAIL + readyState=uninitialized   → 网络层不可达（TCP/TLS 被防火墙丢包）
#   - GOTO FAIL + netErr=ERR_CONNECTION_*    → TCP 层失败，看具体错误码
#   - GOTO FAIL + netErr=ERR_NAME_NOT_RESOLVED → DNS 解析失败
#   - SEL FAIL                                → 页面打开了但选择器没匹配（页面改版/反爬挑战页）
#   - OK                                      → 全通
# 零临时文件（stdin 直传），15s goto timeout（TCP 层失败 5s 内显现，15s 足够判断）
# 用法：bash probe-issue4-playwright.sh
set -euo pipefail
CONTAINER="browser-auto-hub-bah-api-1"

echo ">>> 容器内 Playwright/Chromium 真实可达性探针..."
echo
# 直接用 .venv 的 python 二进制（不经过 uv run，避免 uv 的 sync 检查可能改动 venv）
# venv 路径来自 Dockerfile.backend：WORKDIR /app + uv sync → /app/.venv
sudo docker exec -i -w /app "$CONTAINER" /app/.venv/bin/python -u - <<'PYEOF'
import asyncio, time
from playwright.async_api import async_playwright

# 来自 sources.json 的 20 个 entry + 对应 container selector
# 图片新闻 entry 有 override selector，其余用 source 级默认
ENTRIES = [
    ("交通运输部", "交通要闻",        "https://www.mot.gov.cn/xinwen/jiaotongyaowen/index.html", "ul.news-list"),
    ("交通运输部", "图片新闻",        "https://www.mot.gov.cn/xinwen/tupianxinwen/index.html", "section.desktop-photo-grid-section .photo-grid"),
    ("交通运输部", "时政要闻",        "https://www.mot.gov.cn/xinwen/shizhengyaowen/index.html", "ul.news-list"),
    ("中央人民政府", "要闻",          "https://www.gov.cn/yaowen/liebiao/", "div.list ul"),
    ("中央人民政府", "最新政策",      "https://www.gov.cn/zhengce/zuixin/", "div.list ul"),
    ("工信部", "时政要闻",            "https://www.miit.gov.cn/xwfb/szyw/index.html", ".page-content ul"),
    ("工信部", "工信动态",            "https://www.miit.gov.cn/xwfb/gxdt/index.html", ".page-content ul"),
    ("工信部", "部领导活动",          "https://www.miit.gov.cn/xwfb/bldhd/index.html", ".page-content ul"),
    ("工信部", "最新政策",            "https://www.miit.gov.cn/xwfb/zxzc/index.html", ".page-content ul"),
    ("工信部", "媒体报道-文字报道",   "https://www.miit.gov.cn/xwfb/mtbd/wzbd/index.html", ".page-content ul"),
    ("工信部", "工信数据-民用船舶",   "https://www.miit.gov.cn/gxsj/tjfx/zbgy/mycb/index.html", ".page-content ul"),
    ("工信部", "国新办新闻发布会",     "https://www.miit.gov.cn/xwfb/xwfbh/gxbxwfbh/index.html", ".page-content ul"),
    ("工信部", "国务院政策例行吹风会", "https://www.miit.gov.cn/xwfb/xwfbh/gwyzclxcfh/index.html", ".page-content ul"),
    ("工信部", "部新闻发布会",        "https://www.miit.gov.cn/xwfb/xwfbh/bxwfbh/index.html", ".page-content ul"),
    ("工信部", "其他新闻发布会",      "https://www.miit.gov.cn/xwfb/xwfbh/qtxwfbh/index.html", ".page-content ul"),
    ("发改委", "新闻发布",            "https://www.ndrc.gov.cn/xwdt/xwfb/", "ul.u-list"),
    ("发改委", "时政要闻",            "https://www.ndrc.gov.cn/xwdt/szyw/", "ul.u-list"),
    ("发改委", "委领导动态",          "https://www.ndrc.gov.cn/xwdt/dt/wlddt/", "ul.u-list"),
    ("发改委", "司局动态",            "https://www.ndrc.gov.cn/xwdt/dt/sjdt/", "ul.u-list"),
    ("发改委", "地方动态",            "https://www.ndrc.gov.cn/xwdt/dt/dfdt/", "ul.u-list"),
]

GOTO_TIMEOUT = 15000       # 15s：TCP 层失败 5s 内显现，15s 足够（pipeline 用 60s，但失败位点一致）
SELECTOR_TIMEOUT = 15000   # 与 collect.py 一致

async def probe(page, net_errors, source, entry, url, sel):
    net_errors.clear()
    t0 = time.monotonic()
    # 1) goto — wait_until="commit" 与 pipeline 完全一致
    try:
        await page.goto(url, wait_until="commit", timeout=GOTO_TIMEOUT)
        goto_time = time.monotonic() - t0
    except Exception as e:
        goto_time = time.monotonic() - t0
        # 判断是否收到任何响应：检查 document.readyState
        try:
            rs = await page.evaluate("document.readyState")
        except Exception:
            rs = "(no document)"
        err = str(e)[:100]
        net_err = " | ".join(net_errors[:3]) if net_errors else "(无 net 错误)"
        return f"GOTO FAIL | {source:6} | {entry:14} | {goto_time:5.1f}s | readyState={rs:12} | {net_err} | {err}"

    # 2) selector — 与 collect.py wait_for_selector 一致
    t1 = time.monotonic()
    try:
        await page.wait_for_selector(sel, timeout=SELECTOR_TIMEOUT)
        sel_time = time.monotonic() - t1
        count = await page.locator(sel).count()
        title = (await page.title())[:35]
        return f"OK       | {source:6} | {entry:14} | goto={goto_time:4.1f}s sel={sel_time:4.1f}s | items={count:3} | {title}"
    except Exception as e:
        sel_time = time.monotonic() - t1
        return f"SEL FAIL | {source:6} | {entry:14} | goto={goto_time:4.1f}s sel={sel_time:4.1f}s | sel={sel:45} | {type(e).__name__}"

async def main():
    print("=== Playwright/Chromium 真实可达性探针：20 entry ===", flush=True)
    print(f"goto timeout={GOTO_TIMEOUT}ms (wait_until=commit) | selector timeout={SELECTOR_TIMEOUT}ms", flush=True)
    print("-" * 130, flush=True)

    async with async_playwright() as p:
        # --no-first-run --no-default-browser-check：抑制 Chromium 写 first-run 标记
        browser = await p.chromium.launch(headless=True, args=[
            "--no-sandbox", "--disable-dev-shm-usage",
            "--no-first-run", "--no-default-browser-check",
        ])
        try:
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                locale="zh-CN",
            )
            page = await context.new_page()
            # 捕获 Chromium 网络层错误码（ERR_CONNECTION_TIMED_OUT 等）——决定性证据
            net_errors = []
            page.on("requestfailed", lambda req: net_errors.append(f"{req.url[:55]} -> {req.failure}"))

            for source, entry, url, sel in ENTRIES:
                print(f"--- {source} / {entry} ---", flush=True)
                try:
                    result = await probe(page, net_errors, source, entry, url, sel)
                except Exception as e:
                    result = f"ERR      | {source:6} | {entry:14} | {type(e).__name__}: {str(e)[:90]}"
                print(result, flush=True)
        finally:
            # 任何路径（含异常/KeyboardInterrupt）都保证关浏览器，清理 /tmp 临时 profile
            await browser.close()

    print("\n=== 完成 ===", flush=True)

asyncio.run(main())
PYEOF
echo
echo ">>> 探针结束（无任何临时文件残留）"
