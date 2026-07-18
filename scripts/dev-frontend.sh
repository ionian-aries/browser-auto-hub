#!/usr/bin/env bash
# 仅启动前端（用于单独调试前端）
set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR/packages/frontend"

echo "启动前端开发服务器..."
echo ""

exec npx pnpm dev
