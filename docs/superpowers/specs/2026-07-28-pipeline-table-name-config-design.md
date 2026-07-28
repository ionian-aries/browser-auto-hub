# Pipeline 业务表名动态配置设计

## 背景

Pipeline 业务表名（如 `inbox_documents`）当前硬编码在 engine 层的原始 SQL 和 backend 的 ORM 模型中。
部署不同客户环境时，可能需要使用不同的物理表名（如 `skill_custom_inbox_documents`），
但目前必须修改代码才能实现，不利于 Docker 镜像复用和多环境部署。

## 目标

通过 `TABLE_` 前缀环境变量注入表名映射，开发和部署时只需设置环境变量，内部代码无需改动。

## 约束

- engine 不可导入 backend models（架构约束）
- 零配置时必须开箱即用（默认值回退）
- engine 和 backend ORM 必须操作同一张物理表

## 设计

### 核心机制

新增 `packages/engine/src/engine/table_names.py`：

```python
import os

def resolve_table(logical_name: str, default: str) -> str:
    """返回物理表名：优先读 TABLE_{logical_name} 环境变量，缺失则用 default。"""
    return os.environ.get(f"TABLE_{logical_name}", default)
```

- 位置：engine 层（backend 依赖 engine，两边都能导入）
- 求值时机：模块加载时一次性解析，部署期间表名固定
- 零依赖：仅使用 `os.environ`

### Engine 层使用

Pipeline 原始 SQL 中的表名从硬编码改为动态解析：

```python
from engine.table_names import resolve_table

_INBOX_TABLE = resolve_table("inbox_documents", "inbox_documents")

# f"SELECT task_id FROM {_INBOX_TABLE}"
# f"INSERT INTO {_INBOX_TABLE} (...) VALUES (...)"
# f"SELECT fwd, forward_time FROM {_INBOX_TABLE} WHERE task_id = :task_id"
# f"UPDATE {_INBOX_TABLE} SET fwd = 1, forward_time = :ts WHERE ..."
```

影响文件：
- `packages/engine/src/engine/pipelines/oa/communicate_todos.py`（2 处 SQL）
- `packages/engine/src/engine/pipelines/oa/communicate_forward.py`（2 处 SQL）

### Backend ORM 同步

ORM 模型使用同一函数解析 `__tablename__`，确保 engine 和 backend 操作同一物理表：

```python
from engine.table_names import resolve_table

class InboxDocument(Base):
    __tablename__ = resolve_table("inbox_documents", "inbox_documents")
```

影响文件：
- `packages/backend/src/backend/models/inbox_document.py`

### 配置方式

**本地开发**（`.env`）：

```bash
# 可选：覆盖默认表名
TABLE_inbox_documents=skill_custom_inbox_documents
```

**Docker 部署**（`docker-compose.yml`）：

```yaml
environment:
  - TABLE_inbox_documents=skill_custom_inbox_documents
```

**零配置**：不设环境变量时，`resolve_table` 返回默认值 `inbox_documents`，行为与当前一致。

### 扩展性

未来新增 pipeline 业务表时：
1. 在新 pipeline 代码中调用 `resolve_table("new_table", "new_table")`
2. 在 `.env` 或 `docker-compose.yml` 中配置 `TABLE_new_table=custom_name`（可选）

无需修改 `table_names.py` 或任何注册表。

## 测试策略

| 场景 | 验证内容 |
|------|----------|
| 默认值 | 不设环境变量时返回 default |
| 覆盖值 | 设置 `TABLE_xxx=custom` 后返回 `custom` |
| ORM 一致性 | backend model 和 engine resolve 同一 logical name 得到同一物理表名 |
| 现有测试 | 所有 117 个现有测试继续通过 |

## 影响范围

| 文件 | 变更类型 |
|------|----------|
| `packages/engine/src/engine/table_names.py` | 新增 |
| `packages/engine/src/engine/pipelines/oa/communicate_todos.py` | 修改（2 处 SQL） |
| `packages/engine/src/engine/pipelines/oa/communicate_forward.py` | 修改（2 处 SQL） |
| `packages/backend/src/backend/models/inbox_document.py` | 修改（__tablename__） |
| `packages/engine/tests/test_table_names.py` | 新增 |
| `.env` | 修改（添加注释说明） |
