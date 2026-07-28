# Browser Auto Hub — Project Rules

## Immutable Principle

**Spec is the single source of truth.**

Any change to project structure, functionality, architecture, models, APIs, or configuration
MUST align with the spec document at `docs/specs/1.2026-07-18-浏览器自动化平台设计.md`.

If a change requires deviating from the spec:
1. Update the spec first — document the rationale
2. Then implement the code change

Never change code in a way that contradicts the spec without updating the spec first.

## Document Naming Convention (Mandatory)

所有 spec 文档必须遵循以下命名格式：

```
{序号}.{YYYY-MM-DD}-{中文标题}.md
```

- 序号：无前导零的递增数字（1, 2, 3...）
- 日期：创建日期，ISO 格式
- 标题：中文简述，用短横线连接

示例：
- `docs/specs/1.2026-07-18-浏览器自动化平台设计.md`
- `docs/specs/2.2026-07-20-用户认证模块设计.md`

## Document Hierarchy

| Document | Role | Authority |
|----------|------|-----------|
| `docs/specs/*.md` | Architecture, interfaces, constraints | **Authoritative — immutable unless explicitly updated** |
| Code | Implementation | Must conform to spec at all times |

## Project Structure

- Monorepo: uv workspace (Python) + pnpm workspace (Node)
- Backend: `packages/backend/` — FastAPI + SQLAlchemy + APScheduler
- Engine: `packages/engine/` — browser-use + playwright-cli executors
- Frontend: `packages/frontend/` — React + Vite + Ant Design + React Query
- Infrastructure: `docker/` + `docker-compose.yml`
- Config: `.env`（infra 配置唯一来源；运行旋钮存 system_settings 表）

## Testing

```bash
# Run all tests
uv run pytest -v

# Frontend build check
cd packages/frontend && npx pnpm build
```

## Key Decisions

- MySQL 8.0 with microsecond timestamp precision (DATETIME(fsp=6))
- MinIO for pipeline business attachments（bucket 外部预创建，平台仅连接）
- Pipeline registry via Python decorators + auto-discovery
- SSE for real-time execution monitoring
- Docker Compose for deployment
