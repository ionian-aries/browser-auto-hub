# Browser Auto Hub

浏览器自动化管理平台 — 支持 pipeline 编排、定时调度、实时监控。

## 技术栈

| 层 | 技术 |
|----|------|
| 前端 | React 18 + TypeScript + Vite + Ant Design 5 + React Query |
| 后端 | Python 3.11 + FastAPI + SQLAlchemy 2.0 + APScheduler 4 |
| 引擎 | browser-use + playwright-cli + CloakBrowser |
| 存储 | MySQL 8.0 + MinIO |
| 部署 | Docker + Docker Compose |

## 快速开始

### 前置条件

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose（仅生产部署需要）
- [uv](https://docs.astral.sh/uv/) (Python 包管理)
- 外部 MySQL 8.0 实例（本地开发共用已有服务）
- 外部 MinIO 实例

### 1. 安装依赖

```bash
# Python 依赖
uv sync

# 前端依赖
cd packages/frontend && npx pnpm install && cd ../..
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填写 DATABASE_URL、MINIO_ENDPOINT 等
```

### 3. 本地开发

```bash
# 一键启动后端 + 前端（连接外部 MySQL/MinIO，Ctrl+C 统一停止）
make dev

# 或者分别启动（适合单独调试）
make dev-backend    # 仅后端 (http://localhost:8900)
make dev-frontend   # 仅前端 (http://localhost:3200)
```

### 4. 生产部署（全容器化）

```bash
make deploy
# 前端: http://localhost:3200
# 后端: http://localhost:8900
```

> MySQL / MinIO 为外部已 provisioning 设施（库表与 bucket 提前创建），
> compose 仅编排 backend + frontend；端口可用 .env 中 BACKEND_PORT / FRONTEND_PORT 覆盖。

## 开发命令

```bash
make help           # 查看所有可用命令
make test           # 运行全量测试
make test-backend   # 仅后端测试
make test-engine    # 仅引擎测试
make build          # 构建 Docker 镜像
make stop           # 停止 compose 服务
make clean          # 清理构建产物
```

## 项目结构

```
browser-auto-hub/
├── packages/
│   ├── backend/        # FastAPI 后端服务
│   │   ├── src/backend/
│   │   │   ├── api/        # REST API 路由
│   │   │   ├── models/     # SQLAlchemy 数据模型
│   │   │   ├── services/   # 业务逻辑层
│   │   │   └── scheduler/  # APScheduler 定时调度
│   │   └── tests/
│   ├── engine/         # 浏览器自动化引擎（作为库被 backend 导入）
│   │   ├── src/engine/
│   │   │   ├── executors/  # playwright-cli / cloakbrowser
│   │   │   ├── pipelines/  # 具体 Pipeline 实现
│   │   │   └── registry.py # Pipeline 注册与发现
│   │   └── tests/
│   └── frontend/       # React 前端管理面板
│       └── src/
│           ├── pages/      # 页面组件
│           ├── components/ # 通用组件
│           ├── api/        # API 客户端
│           └── types/      # TypeScript 类型
├── scripts/            # 开发脚本 (dev.sh)
├── docker/             # Dockerfile + nginx.conf
├── docs/
│   └── specs/          # 设计规格文档（唯一权威）
├── docker-compose.yml
├── .env.example
└── CLAUDE.md           # 项目治理规则
```

## 架构说明

```
用户 → Nginx(:3200) ─┬─ /api/* → FastAPI(:8900) → MySQL
                      └─ /*     → React SPA        MinIO
```

- **本地开发**：后端 + 前端本地热重载，连接外部已有 MySQL/MinIO
- **生产部署**：全量 Docker Compose，Nginx 反向代理前后端

## 端口分配

| 服务 | 端口 | 说明 |
|------|------|------|
| 后端 API | 8900 | FastAPI (uvicorn)，compose 部署可用 BACKEND_PORT 覆盖 |
| 前端 Web | 3200 | Vite dev / Nginx prod，compose 部署可用 FRONTEND_PORT 覆盖 |
| MySQL | 3306 | 外部实例（库表提前创建，应用仅连接） |
| MinIO API | 9000 | 外部实例（bucket 提前创建，pipeline 业务附件） |

端口选择避开了 himea-agent-infra 等同机部署项目的常用端口。

## 文档

- 设计规格（Spec）：[docs/specs/1.2026-07-18-浏览器自动化平台设计.md](docs/specs/1.2026-07-18-浏览器自动化平台设计.md)
