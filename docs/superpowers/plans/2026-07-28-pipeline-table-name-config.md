# Pipeline 业务表名动态配置 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make pipeline business table names configurable via `TABLE_` prefixed environment variables, with zero-config defaults.

**Architecture:** A single `resolve_table(logical_name, default)` function in `engine/table_names.py` reads `TABLE_{logical_name}` from `os.environ`. Both engine raw SQL and backend ORM `__tablename__` use this function, ensuring they always operate on the same physical table. No registry, no dependencies beyond `os`.

**Tech Stack:** Python, os.environ, SQLAlchemy (raw text + ORM)

## Global Constraints

- engine 不可导入 backend models（架构约束）
- 零配置时必须开箱即用（默认值回退到代码中的 hardcoded default）
- engine 和 backend ORM 必须操作同一张物理表
- 所有现有测试（117 个）必须继续通过

---

### Task 1: resolve_table() 核心函数 + 测试

**Files:**
- Create: `packages/engine/src/engine/table_names.py`
- Create: `packages/engine/tests/test_table_names.py`

**Interfaces:**
- Produces: `resolve_table(logical_name: str, default: str) -> str`
  - Reads `os.environ.get(f"TABLE_{logical_name}", default)`
  - 后续 Task 2/3 都依赖此函数签名

- [ ] **Step 1: Write the failing tests**

```python
# packages/engine/tests/test_table_names.py
import os

from engine.table_names import resolve_table


def test_resolve_table_returns_default_when_env_not_set(monkeypatch):
    monkeypatch.delenv("TABLE_foo", raising=False)
    assert resolve_table("foo", "foo_default") == "foo_default"


def test_resolve_table_returns_env_value_when_set(monkeypatch):
    monkeypatch.setenv("TABLE_foo", "custom_foo")
    assert resolve_table("foo", "foo_default") == "custom_foo"


def test_resolve_table_uses_table_prefix(monkeypatch):
    """TABLE_ 前缀是 key 的一部分，不带前缀的环境变量不应被读取。"""
    monkeypatch.setenv("foo", "wrong_value")
    monkeypatch.delenv("TABLE_foo", raising=False)
    assert resolve_table("foo", "fallback") == "fallback"


def test_resolve_table_inbox_documents_example(monkeypatch):
    """端到端示例：TABLE_inbox_documents=skill_custom_inbox_documents"""
    monkeypatch.setenv("TABLE_inbox_documents", "skill_custom_inbox_documents")
    assert resolve_table("inbox_documents", "inbox_documents") == "skill_custom_inbox_documents"


def test_resolve_table_empty_env_value_is_used(monkeypatch):
    """空字符串也是有效配置值（虽然不推荐），应被返回而非回退到 default。"""
    monkeypatch.setenv("TABLE_bar", "")
    assert resolve_table("bar", "bar_default") == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/engine/tests/test_table_names.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.table_names'`

- [ ] **Step 3: Write minimal implementation**

```python
# packages/engine/src/engine/table_names.py
"""Pipeline 业务表名动态解析。

通过 TABLE_ 前缀环境变量覆盖默认表名。
例：TABLE_inbox_documents=skill_custom_inbox_documents

零配置时返回代码中的默认值，开箱即用。
"""

import os


def resolve_table(logical_name: str, default: str) -> str:
    """返回物理表名：优先读环境变量 TABLE_{logical_name}，缺失则用 default。"""
    return os.environ.get(f"TABLE_{logical_name}", default)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/engine/tests/test_table_names.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add packages/engine/src/engine/table_names.py packages/engine/tests/test_table_names.py
git commit -m "feat(engine): add resolve_table() for dynamic pipeline table names"
```

---

### Task 2: Engine pipeline SQL 改用动态表名

**Files:**
- Modify: `packages/engine/src/engine/pipelines/oa/communicate_todos.py` (lines 108, 534-536)
- Modify: `packages/engine/src/engine/pipelines/oa/communicate_forward.py` (lines 189-191, 207-212)

**Interfaces:**
- Consumes: `resolve_table(logical_name: str, default: str) -> str` (from Task 1)
- Produces: 模块级常量 `_INBOX_TABLE` — 模块加载时解析一次

- [ ] **Step 1: Add resolve_table import and module-level constant to communicate_todos.py**

在文件顶部 imports 区域添加（在 `from engine.registry import register_pipeline` 之后）：

```python
from engine.table_names import resolve_table

_INBOX_TABLE = resolve_table("inbox_documents", "inbox_documents")
```

- [ ] **Step 2: Update SELECT SQL in communicate_todos.py (line 108)**

替换：

```python
                result = await ctx.db.execute(text("SELECT task_id FROM inbox_documents"))
```

为：

```python
                result = await ctx.db.execute(text(f"SELECT task_id FROM {_INBOX_TABLE}"))
```

- [ ] **Step 3: Update INSERT SQL in communicate_todos.py (lines 534-536)**

替换：

```python
        insert_sql = text("""
            INSERT INTO inbox_documents (id, task_id, creator, send_time, title, participants, cc_recipients, summary, attachment_urls)
            VALUES (:id, :task_id, :creator, :send_time, :title, :participants, :cc_recipients, :summary, :attachment_urls)
        """)
```

为：

```python
        insert_sql = text(f"""
            INSERT INTO {_INBOX_TABLE} (id, task_id, creator, send_time, title, participants, cc_recipients, summary, attachment_urls)
            VALUES (:id, :task_id, :creator, :send_time, :title, :participants, :cc_recipients, :summary, :attachment_urls)
        """)
```

同时更新 `_save_records` 的 docstring（line 529）：

```python
    async def _save_records(self, records: list[dict], ctx: ExecutionContext):
        """批量写入 inbox_documents（raw SQL，engine 不可导入 backend models；表名由 TABLE_ 环境变量配置）"""
```

- [ ] **Step 4: Add resolve_table import and module-level constant to communicate_forward.py**

在文件顶部 imports 区域添加（在 `from engine.registry import register_pipeline` 之后）：

```python
from engine.table_names import resolve_table

_INBOX_TABLE = resolve_table("inbox_documents", "inbox_documents")
```

- [ ] **Step 5: Update SELECT SQL in communicate_forward.py (line 190)**

替换：

```python
        result = await ctx.db.execute(
            text("SELECT fwd, forward_time FROM inbox_documents WHERE task_id = :task_id"),
            {"task_id": task_id},
        )
```

为：

```python
        result = await ctx.db.execute(
            text(f"SELECT fwd, forward_time FROM {_INBOX_TABLE} WHERE task_id = :task_id"),
            {"task_id": task_id},
        )
```

- [ ] **Step 6: Update UPDATE SQL in communicate_forward.py (lines 208-212)**

替换：

```python
        result = await ctx.db.execute(
            text(
                "UPDATE inbox_documents SET fwd = 1, forward_time = :ts"
                " WHERE task_id = :task_id"
                " AND (fwd IS NULL OR fwd = 0) AND forward_time IS NULL"
            ),
```

为：

```python
        result = await ctx.db.execute(
            text(
                f"UPDATE {_INBOX_TABLE} SET fwd = 1, forward_time = :ts"
                " WHERE task_id = :task_id"
                " AND (fwd IS NULL OR fwd = 0) AND forward_time IS NULL"
            ),
```

- [ ] **Step 7: Run all tests to verify nothing broke**

Run: `uv run pytest -v --tb=short`
Expected: All 122 tests pass (117 existing + 5 new from Task 1)

- [ ] **Step 8: Commit**

```bash
git add packages/engine/src/engine/pipelines/oa/communicate_todos.py packages/engine/src/engine/pipelines/oa/communicate_forward.py
git commit -m "feat(engine): use resolve_table() for inbox_documents in OA pipelines"
```

---

### Task 3: Backend ORM __tablename__ 同步

**Files:**
- Modify: `packages/backend/src/backend/models/inbox_document.py` (line 10)

**Interfaces:**
- Consumes: `resolve_table(logical_name: str, default: str) -> str` (from Task 1)
- Produces: `InboxDocument.__tablename__` — 与 engine 的 `_INBOX_TABLE` 解析同一值

- [ ] **Step 1: Write a consistency test**

在已有的 `packages/backend/tests/test_inbox_document_model.py` 末尾添加：

```python
def test_inbox_document_tablename_matches_resolve_table():
    """ORM __tablename__ 必须与 engine resolve_table() 解析同一 logical name 的结果一致。"""
    from engine.table_names import resolve_table
    from backend.models.inbox_document import InboxDocument

    expected = resolve_table("inbox_documents", "inbox_documents")
    assert InboxDocument.__tablename__ == expected
```

- [ ] **Step 2: Run test to verify it passes (should already pass with default)**

Run: `uv run pytest packages/backend/tests/test_inbox_document_model.py::test_inbox_document_tablename_matches_resolve_table -v`
Expected: PASS（当前 ORM 硬编码 "inbox_documents" 与 resolve_table 默认值一致）

- [ ] **Step 3: Modify InboxDocument.__tablename__ to use resolve_table()**

替换 `packages/backend/src/backend/models/inbox_document.py` 的第 10 行：

```python
    __tablename__ = "inbox_documents"
```

为：

```python
from engine.table_names import resolve_table

class InboxDocument(Base):
    __tablename__ = resolve_table("inbox_documents", "inbox_documents")
```

注意：`from engine.table_names import resolve_table` 放在文件顶部 imports 区域（在 `from backend.models.base import Base, UTCDateTime, generate_uuid` 之后）。

- [ ] **Step 4: Run all tests**

Run: `uv run pytest -v --tb=short`
Expected: All tests pass（包括新增的一致性测试）

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/backend/models/inbox_document.py packages/backend/tests/test_inbox_document_model.py
git commit -m "feat(backend): InboxDocument ORM uses resolve_table() for dynamic table name"
```

---

### Task 4: .env 添加配置说明注释

**Files:**
- Modify: `.env` (append section)

**Interfaces:**
- 纯文档性变更，无代码接口影响

- [ ] **Step 1: Add commented example to .env**

在 `.env` 文件末尾添加：

```bash
# Pipeline 业务表名映射（TABLE_ 前缀，可选配置）
# 默认表名已内置于代码中，仅在需要覆盖时取消注释并修改
# TABLE_inbox_documents=inbox_documents
```

- [ ] **Step 2: Run all tests one final time**

Run: `uv run pytest -v --tb=short`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add .env
git commit -m "docs: add TABLE_ env var example to .env"
```
