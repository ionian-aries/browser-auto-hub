#!/usr/bin/env bash
# 仅启动后端（用于单独调试后端）
set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "启动后端 (http://localhost:8900)..."
echo "API 文档: http://localhost:8900/docs"
echo ""

exec uv run uvicorn backend.main:app --reload --port 8900
