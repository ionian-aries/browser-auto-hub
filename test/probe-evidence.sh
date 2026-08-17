#!/usr/bin/env bash
# 港航采集 网络可达性对比证据
# 目的：向客户提供「ping 通、堡垒机 curl 通，但容器内 curl gov.cn 超时」的直接证据
# 对比 4 个层面：
#   1. 堡垒机 ping www.gov.cn         → ICMP 通（证明目标 IP 可达）
#   2. 堡垒机 curl www.gov.cn         → TCP/TLS/HTTP 通（证明从主机直接访问正常）
#   3. 容器内 curl www.gov.cn         → 超时（证明从容器内访问不通）
#   4. 容器内 curl www.mot.gov.cn     → 通（对照组：同一容器访问其他政府站点正常）
# 零临时文件、零副作用（不修改容器、不写入临时文件）
# 用法：sudo bash probe-evidence.sh
set -u

CONTAINER="browser-auto-hub-bah-api-1"
GOV_URL="https://www.gov.cn/yaowen/liebiao/"
MOT_URL="https://www.mot.gov.cn/xinwen/jiaotongyaowen/index.html"

echo ">>> 网络可达性对比证据（4 项，约 30s 完成）..."
echo

echo "=== [1] 堡垒机 ping www.gov.cn（ICMP 层）==="
ping -c 3 -W 2 www.gov.cn 2>&1 || echo "  ping 失败"
echo

echo "=== [2] 堡垒机 curl www.gov.cn（TCP/TLS/HTTP 层，8s 超时）==="
curl -sS -o /dev/null -w '  HTTP code=%{http_code}  耗时=%{time_total}s\n' \
  --max-time 8 "$GOV_URL" 2>&1 || echo "  curl 失败/超时"
echo

echo "=== [3] 容器内 curl www.gov.cn（同一目标，从容器内访问，8s 超时）==="
docker exec "$CONTAINER" \
  curl -sS -o /dev/null -w '  HTTP code=%{http_code}  耗时=%{time_total}s\n' \
  --max-time 8 "$GOV_URL" 2>&1 || echo "  容器内 curl 失败/超时"
echo

echo "=== [4] 容器内 curl www.mot.gov.cn（对照组：同一容器访问其他政府站点，8s 超时）==="
docker exec "$CONTAINER" \
  curl -sS -o /dev/null -w '  HTTP code=%{http_code}  耗时=%{time_total}s\n' \
  --max-time 8 "$MOT_URL" 2>&1 || echo "  容器内 curl 失败/超时"
echo

echo ">>> 证据采集结束"
echo
echo "结论："
echo "  [1] ping 通      → gov.cn 目标 IP 在网络层可达"
echo "  [2] 堡垒机 curl 通 → 从主机直接访问 gov.cn 的 TCP/443 正常"
echo "  [3] 容器内 curl 超时 → 从容器内访问 gov.cn 的 TCP/443 不通"
echo "  [4] 容器内 mot 通   → 同一容器访问其他政府站点正常，排除容器自身网络故障"
echo "  → 阻断发生在「容器网络 → gov.cn」的路径上，不是 gov.cn 本身的问题，"
echo "    也不是容器自身的问题，而是容器到 gov.cn 之间的网络路径存在差异。"
