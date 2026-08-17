#!/usr/bin/env bash
# 港航采集 全量 entry 探针 v3
# 目的：针对 sources.json 中所有 20 个 entry，逐个验证
#   - 哪些 host 在网络层就超时（TCP/TLS 不通 = 防火墙白名单未覆盖）
#   - 哪些 entry HTTP 层失败（403/404/5xx）
#   - 哪些 entry 拿到了非空 body（容器选择器是否能匹配，需另外测）
# 并行 8 路、5s 超时、浏览器 UA（绕过 miit nginx UA 过滤，模拟 pipeline 真实流量）
# IPv4-only（family=AF_INET）：容器无 IPv6 路由，测 IPv6 必败是假阳性
# 零临时文件（stdin 直传容器内 python3）
# 用法：bash probe-issue3.sh
set -euo pipefail
CONTAINER="browser-auto-hub-bah-api-1"

echo ">>> 容器内全量 entry 探针（20 entry × 4 层，并行 8，约 15s 完成）..."
echo
sudo docker exec -i "$CONTAINER" python3 -u - <<'PYEOF'
import socket, ssl, time, urllib.request
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# 与 sources.json 完全一致的 20 个 entry
ENTRIES = [
    ("交通运输部", "交通要闻",       "https://www.mot.gov.cn/xinwen/jiaotongyaowen/index.html"),
    ("交通运输部", "图片新闻",       "https://www.mot.gov.cn/xinwen/tupianxinwen/index.html"),
    ("交通运输部", "时政要闻",       "https://www.mot.gov.cn/xinwen/shizhengyaowen/index.html"),
    ("中央人民政府", "要闻",         "https://www.gov.cn/yaowen/liebiao/"),
    ("中央人民政府", "最新政策",     "https://www.gov.cn/zhengce/zuixin/"),
    ("工信部", "时政要闻",           "https://www.miit.gov.cn/xwfb/szyw/index.html"),
    ("工信部", "工信动态",           "https://www.miit.gov.cn/xwfb/gxdt/index.html"),
    ("工信部", "部领导活动",         "https://www.miit.gov.cn/xwfb/bldhd/index.html"),
    ("工信部", "最新政策",           "https://www.miit.gov.cn/xwfb/zxzc/index.html"),
    ("工信部", "媒体报道-文字报道",  "https://www.miit.gov.cn/xwfb/mtbd/wzbd/index.html"),
    ("工信部", "工信数据-民用船舶",  "https://www.miit.gov.cn/gxsj/tjfx/zbgy/mycb/index.html"),
    ("工信部", "国新办新闻发布会",    "https://www.miit.gov.cn/xwfb/xwfbh/gxbxwfbh/index.html"),
    ("工信部", "国务院政策例行吹风会","https://www.miit.gov.cn/xwfb/xwfbh/gwyzclxcfh/index.html"),
    ("工信部", "部新闻发布会",       "https://www.miit.gov.cn/xwfb/xwfbh/bxwfbh/index.html"),
    ("工信部", "其他新闻发布会",     "https://www.miit.gov.cn/xwfb/xwfbh/qtxwfbh/index.html"),
    ("发改委", "新闻发布",           "https://www.ndrc.gov.cn/xwdt/xwfb/"),
    ("发改委", "时政要闻",           "https://www.ndrc.gov.cn/xwdt/szyw/"),
    ("发改委", "委领导动态",         "https://www.ndrc.gov.cn/xwdt/dt/wlddt/"),
    ("发改委", "司局动态",           "https://www.ndrc.gov.cn/xwdt/dt/sjdt/"),
    ("发改委", "地方动态",           "https://www.ndrc.gov.cn/xwdt/dt/dfdt/"),
]

# 浏览器 UA：模拟 pipeline (Playwright/Chromium) 真实流量，绕过 miit nginx UA 过滤
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

def probe(source, entry, url):
    host = urlparse(url).hostname
    # 只输出一行汇总，便于横向对比
    # 优先级：HTTP status > 失败层
    t0 = time.monotonic()
    # DNS — family=AF_INET 只取 IPv4（容器无 IPv6 路由，测 IPv6 必败是假阳性）
    try:
        ips = sorted({i[4][0] for i in socket.getaddrinfo(host, 443, family=socket.AF_INET, type=socket.SOCK_STREAM)})
        if not ips:
            return f"FAIL DNS   | {source:6} | {entry:14} | {host:16} | {time.monotonic()-t0:5.2f}s | 无 IPv4 地址"
    except Exception as e:
        return f"FAIL DNS   | {source:6} | {entry:14} | {host:16} | {time.monotonic()-t0:5.2f}s | {type(e).__name__}: {e}"
    # TCP（5s 超时；正常 <0.5s，5s 不通 = 防火墙丢包）
    try:
        s = socket.create_connection((ips[0], 443), timeout=5)
    except Exception as e:
        return f"FAIL TCP   | {source:6} | {entry:14} | {host:16} {ips[0]:15} | {time.monotonic()-t0:5.2f}s | {type(e).__name__}"
    # TLS
    try:
        ctx = ssl.create_default_context()
        ss = ctx.wrap_socket(s, server_hostname=host)
        cipher = ss.cipher()[0]
        ss.close()
    except Exception as e:
        s.close()
        return f"FAIL TLS   | {source:6} | {entry:14} | {host:16} {ips[0]:15} | {time.monotonic()-t0:5.2f}s | {type(e).__name__}"
    # HTTP（浏览器 UA，5s，读 200 字节判断是否挑战页/空 body）
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        r = urllib.request.urlopen(req, timeout=5)
        body = r.read(200)
        snippet = body[:60].replace(b"\n", b" ").decode("utf-8", "replace")
        return f"HTTP {r.status:3} | {source:6} | {entry:14} | {host:16} {ips[0]:15} | {time.monotonic()-t0:5.2f}s | {len(body):3}B | {snippet}"
    except Exception as e:
        return f"FAIL HTTP  | {source:6} | {entry:14} | {host:16} {ips[0]:15} | {time.monotonic()-t0:5.2f}s | {type(e).__name__}: {e}"

print("=== 全量 entry 探针：20 entry × DNS/TCP/TLS/HTTP，并行 8 ===", flush=True)
print(f"{'结果':10} | {'信源':6} | {'entry':14} | {'host':16} {'ip':15} | {'耗时':5} | {'body':3} | snippet", flush=True)
print("-" * 120, flush=True)

results = []
with ThreadPoolExecutor(max_workers=8) as ex:
    futs = [ex.submit(probe, s, e, u) for s, e, u in ENTRIES]
    for f in as_completed(futs):
        line = f.result()
        results.append(line)
        print(line, flush=True)

print("\n=== 汇总（按信源/host 分组）===", flush=True)
from collections import defaultdict
by_host = defaultdict(list)
for r in results:
    parts = r.split("|")
    source = parts[1].strip()
    host = parts[3].strip().split()[0]
    by_host[(source, host)].append(r)
for (source, host) in sorted(by_host):
    rows = by_host[(source, host)]
    ok = sum(1 for r in rows if "HTTP 2" in r or "HTTP 3" in r)
    print(f"  {source:6} | {host:16} 共 {len(rows)} entry，HTTP 成功 {ok}/{len(rows)}", flush=True)

print("\n=== 完成 ===", flush=True)
PYEOF
echo
echo ">>> 探针结束（无任何临时文件残留）"
