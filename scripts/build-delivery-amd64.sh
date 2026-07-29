#!/usr/bin/env bash
# build-delivery-amd64.sh — Browser Auto Hub 青岛港离线交付包（linux/amd64）
#
# 构建机要求：Docker + 外网（PyPI / npm / Playwright / apt）
# 产出目录（默认 ~/Downloads/交付包-amd64）：
#   - browser-auto-hub-backend.tar.gz          # docker save（标准 load）
#   - browser-auto-hub-frontend.tar.gz         # docker save（优先 load）
#   - browser-auto-hub-frontend-rootfs.tar     # docker export（load 失败时 import 兜底）
#   - deploy.sh / docker-compose.prod.yml / .env.docker / env.txt / 文档
#
# Compose 服务名：bah-api / bah-web（镜像 tag 仍为 *-backend / *-frontend）
# DATABASE_URL 驱动：mysql+aiomysql（本服务依赖 aiomysql，勿用 Himea 的 asyncmy）
#
# 用法（仓库根或任意目录）：
#   bash scripts/build-delivery-amd64.sh
#   SKIP_BACKEND=1 SKIP_FRONTEND=1 bash scripts/build-delivery-amd64.sh   # 只重导出/组装
#   SKIP_PNPM_INSTALL=1 bash ...                                          # 跳过前端 install
#
set -euo pipefail

BAH_REPO="${BAH_REPO:-$HOME/Desktop/wangyi/git-ai/browser-auto-hub}"
BAH_OLD_PKG="${BAH_OLD_PKG:-$HOME/Downloads/交付包}"
BAH_OUT="${BAH_OUT:-$HOME/Downloads/交付包-amd64}"
PLATFORM="${PLATFORM:-linux/amd64}"
BACKEND_TAG="${BACKEND_TAG:-browser-auto-hub-backend:latest}"
FRONTEND_TAG="${FRONTEND_TAG:-browser-auto-hub-frontend:latest}"
SKIP_PNPM_INSTALL="${SKIP_PNPM_INSTALL:-0}"
SKIP_VERIFY="${SKIP_VERIFY:-0}"
SKIP_BACKEND="${SKIP_BACKEND:-0}"
SKIP_FRONTEND="${SKIP_FRONTEND:-0}"

export BAH_OUT

log() { printf '\n▸ %s\n' "$*"; }
die() { printf '✗ %s\n' "$*" >&2; exit 1; }

_docker_build() {
  if docker buildx version >/dev/null 2>&1; then
    docker buildx build --platform "$PLATFORM" --load "$@"
  else
    docker build --platform "$PLATFORM" "$@"
  fi
}

_pnpm() {
  # 规避家目录 packageManager=yarn 导致直接 pnpm 失败
  if command -v pnpm >/dev/null 2>&1 && pnpm -v >/dev/null 2>&1; then
    pnpm "$@"
  else
    npx pnpm@9 "$@"
  fi
}

command -v docker >/dev/null || die "需要 Docker"
[ -d "$BAH_REPO" ] || die "源码目录不存在: $BAH_REPO"
[ -f "$BAH_REPO/docker/Dockerfile.backend" ] || die "缺少 Dockerfile.backend"
[ -d "$BAH_OLD_PKG" ] || die "旧交付包目录不存在（复制 deploy/docs）: $BAH_OLD_PKG"

mkdir -p "$BAH_OUT"
cd "$BAH_REPO"

# Dockerfile.backend 需要 uv.lock；仓库若缺失则生成
if [ ! -f uv.lock ]; then
  log "生成 uv.lock"
  command -v uv >/dev/null || die "缺少 uv.lock 且本机无 uv，无法生成"
  uv lock
fi

# ── 1. Backend（全量烘焙 Python + Playwright Chromium + 系统库）──
if [ "$SKIP_BACKEND" != "1" ]; then
  log "构建 backend 镜像 ($PLATFORM, --no-cache)"
  _docker_build --no-cache -f docker/Dockerfile.backend -t "$BACKEND_TAG" .
else
  log "跳过 backend 构建 (SKIP_BACKEND=1)"
fi

# ── 2. Frontend（优先容器内 build；失败则本地 pnpm + nginx 组装）──
build_frontend_in_docker() {
  local tmpnginx ctx
  tmpnginx=$(mktemp)
  sed 's|http://backend:8900|http://bah-api:8900|g' docker/nginx.conf > "$tmpnginx"
  ctx=$(mktemp -d)
  mkdir -p "$ctx/packages"
  cp "$tmpnginx" "$ctx/nginx.conf"
  rm -f "$tmpnginx"
  cat > "$ctx/Dockerfile" <<'DOCKERFILE'
FROM node:18-alpine AS builder
RUN npm install -g pnpm@9
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY packages/frontend/package.json packages/frontend/
RUN pnpm install --frozen-lockfile --filter frontend...
COPY packages/frontend/ packages/frontend/
RUN pnpm --filter frontend build
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/packages/frontend/dist /usr/share/nginx/html
EXPOSE 80
# 不在构建期跑 nginx -t：bah-api 主机名仅在 compose 网络中可解析
DOCKERFILE
  cp package.json pnpm-lock.yaml pnpm-workspace.yaml "$ctx/"
  cp -R packages/frontend "$ctx/packages/"
  _docker_build -f "$ctx/Dockerfile" -t "$FRONTEND_TAG" "$ctx"
  rm -rf "$ctx"
}

build_frontend_local() {
  log "frontend 改用本地 pnpm + nginx 组装"
  if [ "$SKIP_PNPM_INSTALL" != "1" ]; then
    _pnpm -F frontend install --frozen-lockfile || _pnpm -F frontend install
  fi
  _pnpm -F frontend build
  local ctx tmpnginx
  ctx=$(mktemp -d)
  tmpnginx=$(mktemp)
  sed 's|http://backend:8900|http://bah-api:8900|g' docker/nginx.conf > "$tmpnginx"
  cp "$tmpnginx" "$ctx/default.conf"
  mkdir -p "$ctx/html"
  cp -R packages/frontend/dist/. "$ctx/html/"
  rm -f "$tmpnginx"
  cat > "$ctx/Dockerfile" <<'DOCKERFILE'
FROM nginx:alpine
COPY default.conf /etc/nginx/conf.d/default.conf
COPY html /usr/share/nginx/html
EXPOSE 80
DOCKERFILE
  _docker_build -f "$ctx/Dockerfile" -t "$FRONTEND_TAG" "$ctx"
  rm -rf "$ctx"
}

if [ "$SKIP_FRONTEND" != "1" ]; then
  log "构建 frontend 镜像 ($PLATFORM)"
  if ! build_frontend_in_docker; then
    log "frontend 容器内构建失败，回退本地组装"
    build_frontend_local
  fi
else
  log "跳过 frontend 构建 (SKIP_FRONTEND=1)"
fi

# ── 3. 校验架构 + 离线自包含 ──
if [ "$SKIP_VERIFY" != "1" ]; then
  log "校验镜像架构 (expect amd64)"
  backend_arch=$(docker image inspect "$BACKEND_TAG" --format '{{.Architecture}}')
  frontend_arch=$(docker image inspect "$FRONTEND_TAG" --format '{{.Architecture}}')
  [ "$backend_arch" = "amd64" ] || die "backend 架构=$backend_arch，期望 amd64"
  [ "$frontend_arch" = "amd64" ] || die "frontend 架构=$frontend_arch，期望 amd64"

  log "校验 backend 离线自包含 (Playwright/Python)"
  docker run --rm --platform "$PLATFORM" --entrypoint sh "$BACKEND_TAG" -c \
    'uv run playwright --version && uv run python -c "import backend, engine; print(\"import ok\")"'

  log "校验 frontend 静态资源 + bah-api 反代配置"
  docker run --rm --platform "$PLATFORM" --entrypoint sh "$FRONTEND_TAG" -c \
    'test -f /usr/share/nginx/html/index.html && grep -q bah-api /etc/nginx/conf.d/default.conf && echo OK'
fi

# ── 4. 导出 tar.gz + frontend rootfs（Himea 同思路：load 失败则 import）──
log "导出镜像到 $BAH_OUT"
docker save "$BACKEND_TAG"  | gzip > "$BAH_OUT/browser-auto-hub-backend.tar.gz"
docker save "$FRONTEND_TAG" | gzip > "$BAH_OUT/browser-auto-hub-frontend.tar.gz"

log "导出 frontend rootfs（供客户机 docker import 兜底）"
_cid=$(docker create --platform "$PLATFORM" "$FRONTEND_TAG")
docker export "$_cid" -o "$BAH_OUT/browser-auto-hub-frontend-rootfs.tar"
docker rm "$_cid" >/dev/null

(
  cd "$BAH_OUT"
  shasum -a 256 \
    browser-auto-hub-backend.tar.gz \
    browser-auto-hub-frontend.tar.gz \
    browser-auto-hub-frontend-rootfs.tar \
    > SHA256SUMS.txt
)

# ── 5. 组装交付目录（compose/deploy/docs + 青岛港 env）──
log "复制并 patch 部署文件"
for f in deploy.sh docker-compose.prod.yml README.md 镜像部署方案.md \
         OA流水线API触发指南.md OA流水线CURL调用手册.md 局域网HTTP调用速查.md; do
  [ -f "$BAH_OLD_PKG/$f" ] && cp -f "$BAH_OLD_PKG/$f" "$BAH_OUT/"
done

# 一次性 patch：服务名 + frontend rootfs import 兜底（ENTRYPOINT 勿多转义）
python3 - <<'PY'
from pathlib import Path
import os
import re

out = Path(os.environ["BAH_OUT"])

# compose: backend/frontend → bah-api/bah-web
compose = out / "docker-compose.prod.yml"
if compose.exists():
    text = compose.read_text(encoding="utf-8")
    text = text.replace("\n  backend:\n", "\n  bah-api:\n")
    text = text.replace("\n  frontend:\n", "\n  bah-web:\n")
    text = text.replace("\n      - backend\n", "\n      - bah-api\n")
    compose.write_text(text, encoding="utf-8")
    print(f"patched {compose}")

deploy = out / "deploy.sh"
if not deploy.exists():
    raise SystemExit(f"missing {deploy}")

text = deploy.read_text(encoding="utf-8")

# 容器名 / 日志
text = text.replace("name=browser-auto-hub-backend", "name=browser-auto-hub-bah-api")
text = text.replace("logs backend", "logs bah-api")
text = text.replace('ok "backend 已加入', 'ok "bah-api 已加入')
text = text.replace('ok "backend 已在', 'ok "bah-api 已在')

# 替换 _load_image 函数体（兼容旧版「只 load」与已打过补丁的版本）
new_load = r'''_load_image() {
    local tar="$1" name="$2"
    [ -f "$tar" ] || fail "镜像文件缺失: $tar"
    if docker load -i "$tar"; then
        ok "$name 已加载"
        return 0
    fi

    # frontend 某些客户 Docker 20.10 + overlay2/xfs 环境下会在 docker load
    # 阶段报 invalid diffID。兜底改用 docker export/rootfs + docker import，
    # 避开分层镜像校验链路（与 Himea infra/docker deploy 思路一致）。
    if [ "$name" = "browser-auto-hub-frontend:latest" ]; then
        local rootfs="browser-auto-hub-frontend-rootfs.tar"
        [ -f "$rootfs" ] || fail "frontend load 失败，且缺少 rootfs 兜底文件: $rootfs"
        warn "frontend docker load 失败，改用 rootfs import 兜底"
        docker import \\
          --change 'ENTRYPOINT ["/docker-entrypoint.sh"]' \\
          --change 'CMD ["nginx","-g","daemon off;"]' \\
          --change 'EXPOSE 80' \\
          "$rootfs" browser-auto-hub-frontend:latest >/dev/null
        ok "$name 已通过 rootfs import 导入"
        return 0
    fi

    fail "$name 导入失败"
}'''

# 匹配从 _load_image() { 到紧随其后的第一个 _load_image 调用之前
pat = re.compile(
    r"_load_image\(\)\s*\{.*?\n\}\n(?=_load_image browser-auto-hub-backend)",
    re.DOTALL,
)
if not pat.search(text):
    raise SystemExit("deploy.sh: 未能定位 _load_image 函数，请检查模板")
text = pat.sub(new_load + "\n", text, count=1)
deploy.write_text(text, encoding="utf-8")
print(f"patched {deploy}")
PY

# 青岛港 .env.docker（aiomysql，勿用 asyncmy）
cat > "$BAH_OUT/.env.docker" <<'ENV'
# Browser Auto Hub — 青岛港离线环境模板（deploy.sh + compose 共用）
# 部署前替换 CHANGE_ME_*；密码与 Himea himea-offline/.env 对齐
# ★ 驱动必须是 aiomysql（本镜像依赖）；勿抄 Himea 的 mysql+asyncmy

DATABASE_URL=mysql+aiomysql://himea:CHANGE_ME_himea@mysql:3306/himea?charset=utf8mb4

MINIO_ENDPOINT=http://minio:9000
MINIO_ACCESS_KEY=himea
MINIO_SECRET_KEY=CHANGE_ME_minio
MINIO_BUCKET=himea-skills
MINIO_OBJECT_PREFIX=attachments

PUBLIC_BASE_URL=http://10.236.3.186:8901

BACKEND_PORT=8901
FRONTEND_PORT=3201

TABLE_inbox_documents=skill_custom_inbox_documents
ENV

# Finder 可见副本
cat > "$BAH_OUT/env.txt" <<'ENV'
# Browser Auto Hub — 青岛港部署配置模板（Finder 可见副本）
#
# 用法：
#   cp env.txt .env.docker
#   vim .env.docker          # 替换 CHANGE_ME_*；驱动保持 aiomysql
#   ./deploy.sh

DATABASE_URL=mysql+aiomysql://himea:CHANGE_ME_himea@mysql:3306/himea?charset=utf8mb4

MINIO_ENDPOINT=http://minio:9000
MINIO_ACCESS_KEY=himea
MINIO_SECRET_KEY=CHANGE_ME_minio
MINIO_BUCKET=himea-skills
MINIO_OBJECT_PREFIX=attachments

PUBLIC_BASE_URL=http://10.236.3.186:8901

BACKEND_PORT=8901
FRONTEND_PORT=3201

TABLE_inbox_documents=skill_custom_inbox_documents
ENV

# 文档补充（幂等 append）
if [ -f "$BAH_OUT/镜像部署方案.md" ]; then
  if ! grep -q 'bah-api' "$BAH_OUT/镜像部署方案.md"; then
    cat >> "$BAH_OUT/镜像部署方案.md" <<'DOC'

## 离线部署补充（青岛港）

- 镜像为 **linux/amd64**，构建期已烘焙 Python/npm/Playwright/Chromium，客户机无需外网。
- 须先 load 并运行 Himea 中间件（mysql/minio）；`deploy.sh` 建表/建桶复用本机已有镜像。
- Compose 服务名：**bah-api**（后端）、**bah-web**（前端）。
- `DATABASE_URL` 使用 **`mysql+aiomysql://`**（勿用 Himea 的 `asyncmy`）。
- 查看日志：`docker compose -f docker-compose.prod.yml logs -f bah-api`
DOC
  fi
  if ! grep -q 'frontend-rootfs' "$BAH_OUT/镜像部署方案.md"; then
    cat >> "$BAH_OUT/镜像部署方案.md" <<'DOC'

## frontend docker load 兜底

- 若 `browser-auto-hub-frontend.tar.gz` 在客户机 `docker load` 报 `invalid diffID`，
  `deploy.sh` 会自动改用 `browser-auto-hub-frontend-rootfs.tar` 执行 `docker import`，无需手工处理。
- 升级时一般只需覆盖镜像 tar / rootfs / deploy.sh，**保留客户机已填好的 `.env.docker`**。
DOC
  fi
fi

chmod +x "$BAH_OUT/deploy.sh"

log "完成"
ls -lh \
  "$BAH_OUT/browser-auto-hub-backend.tar.gz" \
  "$BAH_OUT/browser-auto-hub-frontend.tar.gz" \
  "$BAH_OUT/browser-auto-hub-frontend-rootfs.tar"
echo "SHA256:"
cat "$BAH_OUT/SHA256SUMS.txt"
echo
echo "上传到客户机: scp -r \"$BAH_OUT\" qdg@10.236.3.186:/home/qdg/"
echo "客户机升级（保留 .env.docker）: 覆盖 tar/rootfs/deploy.sh 后 sudo sh deploy.sh"
