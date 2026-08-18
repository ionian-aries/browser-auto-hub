#!/usr/bin/env bash
# build-delivery-amd64.sh — Browser Auto Hub 青岛港离线交付包（linux/amd64）
#
# 构建机要求：Docker + 外网（PyPI / npm / Playwright / apt）
# 产出目录（默认 ~/Downloads/交付包-amd64）：
#   - browser-auto-hub-backend.tar.gz          # docker save（标准 load）
#   - browser-auto-hub-frontend.tar.gz         # docker save（优先 load）
#   - browser-auto-hub-frontend-rootfs.tar     # docker export（load 失败时 import 兜底）
#   - deploy.sh / docker-compose.prod.yml 来自仓库 交付包/（不再从旧交付包 patch）
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
[ -f "$BAH_REPO/交付包/deploy.sh" ] || die "缺少 交付包/deploy.sh"
[ -f "$BAH_REPO/交付包/docker-compose.prod.yml" ] || die "缺少 交付包/docker-compose.prod.yml"

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

# ── 5. 组装交付目录（仓库 交付包/ 为 compose/deploy 唯一来源，不再 patch）──
log "复制部署文件（来自仓库 交付包/）"
cp -f "$BAH_REPO/交付包/deploy.sh" "$BAH_OUT/deploy.sh"
cp -f "$BAH_REPO/交付包/docker-compose.prod.yml" "$BAH_OUT/docker-compose.prod.yml"
chmod +x "$BAH_OUT/deploy.sh"
if [ -f "$BAH_REPO/交付包/env.docker.example" ]; then
  cp -f "$BAH_REPO/交付包/env.docker.example" "$BAH_OUT/env.txt"
  cp -f "$BAH_REPO/交付包/env.docker.example" "$BAH_OUT/.env.docker.example"
fi

# 文档仍可从旧交付包带上（可选）
if [ -d "$BAH_OLD_PKG" ]; then
  for f in README.md 镜像部署方案.md \
           OA流水线API触发指南.md OA流水线CURL调用手册.md 局域网HTTP调用速查.md; do
    [ -f "$BAH_OLD_PKG/$f" ] && cp -f "$BAH_OLD_PKG/$f" "$BAH_OUT/"
  done
else
  log "未找到旧交付包目录 $BAH_OLD_PKG，跳过文档复制"
fi

# 青岛港 .env.docker 模板（无真实密钥；升级时勿覆盖客户机已填好的文件）
if [ -f "$BAH_REPO/交付包/env.docker.example" ]; then
  cp -f "$BAH_REPO/交付包/env.docker.example" "$BAH_OUT/.env.docker"
else
  cat > "$BAH_OUT/.env.docker" <<'ENV'
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
TABLE_ganghang_materials=documents
ENV
fi

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
- 升级时覆盖 `deploy.sh` / `docker-compose.prod.yml` / 镜像 tar，**保留客户机已填好的 `.env.docker`**。
- RHEL7 上 `bah-web` 需要 compose 中的 `security_opt: seccomp:unconfined` + `label:disable`，否则 nginx pwrite(pid) 会 EPERM。
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
