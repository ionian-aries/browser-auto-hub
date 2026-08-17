#!/usr/bin/env bash
# 港航采集超时根因探针 v2
# 并行 + 5s 超时 + 实时输出 + 零临时文件
# 验证假设：gov.cn/ndrc 是否在 TCP 层就被防火墙丢包（白名单 IP 未覆盖）
# 用法：bash probe-issue1.sh
set -euo pipefail
CONTAINER="browser-auto-hub-bah-api-1"

echo ">>> 容器内并行探针（4 站点，5s 超时，约 10s 完成）..."
echo
sudo docker exec -i "$CONTAINER" python3 -u - <<'PYEOF'
import socket, ssl, time, urllib.request
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# 4 个信源各取 1 URL（同 host 网络层等价，不必测多 path）
HOSTS = [
    ("gov.cn",      "https://www.gov.cn/yaowen/liebiao/"),
    ("ndrc.gov.cn", "https://www.ndrc.gov.cn/xwdt/xwfb/"),
    ("mot.gov.cn",  "https://www.mot.gov.cn/xinwen/jiaotongyaowen/index.html"),
    ("miit.gov.cn", "https://www.miit.gov.cn/xwfb/szyw/index.html"),
]

def probe(label, url):
    host = urlparse(url).hostname
    out = [f"\n--- {label} ({host}) ---"]
    # DNS
    t = time.monotonic()
    try:
        ips = sorted({i[4][0] for i in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
        out.append(f"  DNS  {ips}  ({time.monotonic()-t:.2f}s)")
    except Exception as e:
        out.append(f"  DNS  FAIL  {e}")
        return "\n".join(out)
    # TCP（5s 超时；gov.cn 正常 <0.5s，5s 不通 = 被防火墙丢包）
    t = time.monotonic()
    try:
        s = socket.create_connection((ips[0], 443), timeout=5)
        out.append(f"  TCP  OK   {time.monotonic()-t:.2f}s  ->{ips[0]}")
    except Exception as e:
        out.append(f"  TCP  FAIL {time.monotonic()-t:.2f}s  {type(e).__name__}: {e}")
        return "\n".join(out)
    # TLS（5s）
    t = time.monotonic()
    try:
        ctx = ssl.create_default_context()
        ss = ctx.wrap_socket(s, server_hostname=host)
        out.append(f"  TLS  OK   {time.monotonic()-t:.2f}s  cipher={ss.cipher()[0]}")
        ss.close()
    except Exception as e:
        out.append(f"  TLS  FAIL {time.monotonic()-t:.2f}s  {type(e).__name__}: {e}")
        s.close()
        return "\n".join(out)
    # HTTP（5s，读 200 字节；body 用来判断是不是反爬挑战页）
    t = time.monotonic()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        r = urllib.request.urlopen(req, timeout=5)
        body = r.read(200)
        out.append(f"  HTTP {r.status}  {time.monotonic()-t:.2f}s  body={body[:80]}")
    except Exception as e:
        out.append(f"  HTTP FAIL {time.monotonic()-t:.2f}s  {type(e).__name__}: {e}")
    return "\n".join(out)

print("=== 并行探针：DNS/TCP/TLS/HTTP × 4 站点 ===", flush=True)
with ThreadPoolExecutor(max_workers=4) as ex:
    futs = [ex.submit(probe, l, u) for l, u in HOSTS]
    for f in as_completed(futs):
        print(f.result(), flush=True)
print("\n=== 完成 ===", flush=True)
PYEOF
echo
echo ">>> 探针结束（无任何临时文件残留）"
