#!/usr/bin/env bash
# LLM 网关路由探针 — 用 FastAPI 自带的 openapi.json 揭示真实路由
# 用法（在部署服务器上，能访问 10.196.119.63 的机器）：
#   bash probe-issue2.sh
# 或从容器内：
#   docker exec -it browser-auto-hub-bah-api-1 /bin/bash /mnt/probe-issue2.sh
set -u

BASE="http://10.196.119.63"
INFER_ID="35d8ff0c-fa4c-42fe-bf9c-cf743762e03c"
INFER_BASE="$BASE/v2/infer/$INFER_ID"
API_KEY="o-RS1hDDO7q2St4IysnIotUMhjqUTA7jQ077rq5jgLpNnSoXDt6WeaeAcW4DxxhlLgYTSFxDIGOb9kGMx5KG3g"

echo "==== [1] 网关根 / 健康检查 ===="
for path in "/" "/health" "/healthz" "/ping" "/ready"; do
  printf "%-12s " "$path"
  curl -sS -o /tmp/r.json -w "code=%{http_code} body_size=%{size_download}\n" --max-time 10 "$BASE$path" 2>&1 || echo "FAILED"
  head -c 300 /tmp/r.json 2>/dev/null; echo
done

echo
echo "==== [2] FastAPI 自描述端点（决定性证据） ===="
for path in "/openapi.json" "/docs" "/redoc" "/swagger" "/docs/openapi.json"; do
  printf "%-22s " "$path"
  curl -sS -o /tmp/r.json -w "code=%{http_code} body_size=%{size_download}\n" --max-time 10 "$BASE$path" 2>&1 || echo "FAILED"
  head -c 400 /tmp/r.json 2>/dev/null; echo
done

echo
echo "==== [3] infer 端点 GET（可能返回模型元信息） ===="
for path in "/v2/infer/$INFER_ID" "/v2/infer/$INFER_ID/" "/v2/infer/$INFER_ID/info" "/v2/infer/$INFER_ID/models" "/v2/infer/$INFER_ID/health"; do
  printf "%-45s " "$path"
  curl -sS -o /tmp/r.json -w "code=%{http_code} body_size=%{size_download}\n" -H "Authorization: Bearer $API_KEY" --max-time 10 "$BASE$path" 2>&1 || echo "FAILED"
  head -c 400 /tmp/r.json 2>/dev/null; echo
done

echo
echo "==== [4] 候选 chat/completions 路径（POST） ===="
BODY='{"model":"qwen3.5","messages":[{"role":"user","content":"ping"}],"max_tokens":8,"temperature":0}'
for path in \
  "/v2/infer/$INFER_ID/chat/completions" \
  "/v2/infer/$INFER_ID/v1/chat/completions" \
  "/v2/infer/$INFER_ID/completions" \
  "/v1/chat/completions" \
  "/v2/chat/completions" \
  "/chat/completions"; do
  printf "%-50s " "$path"
  curl -sS -o /tmp/r.json -w "code=%{http_code} body_size=%{size_download}\n" \
    -X POST -H "Content-Type: application/json" -H "Authorization: Bearer $API_KEY" \
    -d "$BODY" --max-time 30 "$BASE$path" 2>&1 || echo "FAILED"
  head -c 500 /tmp/r.json 2>/dev/null; echo
done

echo
echo "==== [5] 网关 v2 顶层路由 ===="
for path in "/v2" "/v2/" "/v2/models" "/v1" "/v1/" "/v1/models" "/models"; do
  printf "%-12s " "$path"
  curl -sS -o /tmp/r.json -w "code=%{http_code} body_size=%{size_download}\n" -H "Authorization: Bearer $API_KEY" --max-time 10 "$BASE$path" 2>&1 || echo "FAILED"
  head -c 300 /tmp/r.json 2>/dev/null; echo
done
