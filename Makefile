# Makefile for browser-auto-hub
# 本地开发连接外部 MySQL/MinIO，后端前端本地运行

.PHONY: help dev dev-backend dev-frontend stop test test-backend test-engine build deploy install clean

help: ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# === 一键启动 ===

dev: ## 一键启动项目（后端 + 前端，连接外部 MySQL/MinIO）
	@./scripts/dev.sh

dev-backend: ## 仅启动后端（热重载，用于单独调试）
	@./scripts/dev-backend.sh

dev-frontend: ## 仅启动前端（热重载，用于单独调试）
	@./scripts/dev-frontend.sh

stop: ## 停止 compose 服务（backend/frontend）
	docker compose down

# === 测试 ===

test: ## 运行全量测试
	uv run pytest -v

test-backend: ## 仅运行后端测试
	uv run pytest packages/backend/tests -v

test-engine: ## 仅运行引擎测试
	uv run pytest packages/engine/tests -v

# === 构建 & 部署 ===

build: ## 构建 Docker 镜像（用于部署）
	docker compose build

deploy: ## 全容器化启动（生产/预发布模式）
	docker compose up -d --build

# === 依赖 ===

install: ## 安装所有依赖（Python + 前端）
	uv sync
	cd packages/frontend && npx pnpm install

# === 清理 ===

clean: ## 清理构建产物
	rm -rf packages/frontend/dist
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
