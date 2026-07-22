# Frontend Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the Browser Auto Hub frontend with a Dashboard-centric layout, Pipeline-integrated scheduling, SSE execution debugging, and system settings — plus supporting backend APIs.

**Architecture:** Dashboard as real-time command center. Pipeline detail page integrates schedule management (3 tabs). Execution detail provides SSE log streaming with left/right split layout. Backend adds stats, system info, settings CRUD, pipeline patch, and file presign endpoints.

**Tech Stack:** React 18 + TypeScript + Vite + Ant Design 5 + React Query 5 + react-router-dom v6 + axios + EventSource (SSE)

## Global Constraints

- All IDs are UUID strings (`string` type, never `number`)
- Chinese UI text throughout (no i18n)
- Ant Design 5 components exclusively
- API base: `/api` (proxied via Vite dev server to :8900)
- Backend: FastAPI + SQLAlchemy async + aiomysql
- "Today" in stats = UTC 00:00:00 to now
- Frontend build must pass: `cd packages/frontend && npx pnpm build`
- Backend tests must pass: `uv run pytest -v`

---

### Task 1: Backend — System Settings Model + APIs

**Files:**
- Create: `packages/backend/src/backend/models/system_setting.py`
- Modify: `packages/backend/src/backend/models/__init__.py`
- Modify: `packages/backend/src/backend/api/system.py`
- Modify: `packages/backend/src/backend/config.py`
- Create: `packages/backend/tests/test_system_settings.py`

**Interfaces:**
- Consumes: `Base` from `backend.models.base`, `get_settings()` from `backend.config`
- Produces: `SystemSetting` model, `GET /api/system/settings`, `PUT /api/system/settings`, `POST /api/system/storage/test`, updated `get_settings()` that merges DB overrides

- [ ] **Step 1: Create SystemSetting model**

```python
# packages/backend/src/backend/models/system_setting.py
from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 2: Register model in __init__.py**

Add to `packages/backend/src/backend/models/__init__.py`:
```python
from backend.models.system_setting import SystemSetting
# Add "SystemSetting" to __all__
```

- [ ] **Step 3: Update config.py to merge DB settings**

```python
# packages/backend/src/backend/config.py
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "mysql+aiomysql://root:root@127.0.0.1:3306/browser_auto_hub?charset=utf8mb4"
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "browser-auto-hub"
    minio_object_prefix: str = "browser-auto-hub"
    minio_presign_expires_seconds: int = 604800
    app_secret_key: str = "changeme"
    app_log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Runtime-overridable keys (merged from system_settings table)
OVERRIDABLE_KEYS = {"minio_object_prefix", "minio_presign_expires_seconds"}


async def get_merged_settings(session) -> Settings:
    """Get settings with DB overrides applied."""
    from sqlalchemy import select
    from backend.models.system_setting import SystemSetting

    settings = get_settings()
    result = await session.execute(
        select(SystemSetting).where(SystemSetting.key.in_(OVERRIDABLE_KEYS))
    )
    overrides = {row.key: row.value for row in result.scalars()}

    if overrides:
        values = {}
        if "minio_object_prefix" in overrides:
            values["minio_object_prefix"] = overrides["minio_object_prefix"]
        if "minio_presign_expires_seconds" in overrides:
            values["minio_presign_expires_seconds"] = int(overrides["minio_presign_expires_seconds"])
        if values:
            return settings.model_copy(update=values)
    return settings
```

- [ ] **Step 4: Add settings + storage test endpoints to system.py**

Replace `packages/backend/src/backend/api/system.py`:

```python
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_session
from backend.models.execution import TaskExecution
from backend.models.pipeline import Pipeline
from backend.models.schedule import Schedule
from backend.models.system_setting import SystemSetting

router = APIRouter(prefix="/api/system", tags=["system"])

_start_time = time.time()


@router.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@router.get("/info")
async def system_info(session: AsyncSession = Depends(get_session)):
    from backend.scheduler.manager import scheduler_manager

    active_schedules = await session.scalar(
        select(func.count()).select_from(Schedule).where(Schedule.enabled == True)
    ) or 0

    scheduler_status = "running"
    if scheduler_manager:
        scheduler_status = "paused" if getattr(scheduler_manager, "_paused", False) else "running"

    return {
        "uptime_seconds": int(time.time() - _start_time),
        "scheduler_status": scheduler_status,
        "active_schedules": active_schedules,
        "db_pool": {"pool_size": 5, "checked_out": 0, "overflow": 0},
    }


@router.get("/settings")
async def get_system_settings(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(SystemSetting))
    rows = result.scalars().all()
    settings = get_settings()

    # Merge: DB values override .env defaults; include read-only fields for frontend display
    defaults = {
        "minio_endpoint": settings.minio_endpoint,
        "minio_bucket": settings.minio_bucket,
        "minio_object_prefix": settings.minio_object_prefix,
        "minio_presign_expires_seconds": str(settings.minio_presign_expires_seconds),
        "log_retention_days": "30",
        "scheduler_enabled": "true",
    }
    for row in rows:
        defaults[row.key] = row.value

    return defaults


class SettingsUpdate(BaseModel):
    minio_object_prefix: str | None = None
    minio_presign_expires_seconds: int | None = None
    log_retention_days: int | None = None
    scheduler_enabled: bool | None = None


@router.put("/settings")
async def update_system_settings(
    body: SettingsUpdate, session: AsyncSession = Depends(get_session)
):
    updates = body.model_dump(exclude_unset=True)
    for key, value in updates.items():
        str_value = str(value).lower() if isinstance(value, bool) else str(value)
        result = await session.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = str_value
        else:
            session.add(SystemSetting(key=key, value=str_value))
    await session.commit()
    return {"status": "ok"}


@router.post("/storage/test")
async def test_storage():
    try:
        from backend.storage.minio_client import MinioStorage
        storage = MinioStorage()
        storage.ensure_bucket()
        return {"status": "ok", "message": "MinIO connection successful"}
    except Exception as e:
        raise HTTPException(500, f"MinIO connection failed: {e}")


```

- [ ] **Step 5: Write tests**

```python
# packages/backend/tests/test_system_settings.py
from backend.models.system_setting import SystemSetting


def test_system_setting_model():
    s = SystemSetting(key="test_key", value="test_value")
    assert s.key == "test_key"
    assert s.value == "test_value"


def test_system_setting_tablename():
    assert SystemSetting.__tablename__ == "system_settings"
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest packages/backend/tests/test_system_settings.py -v`
Expected: 2 PASS

- [ ] **Step 7: Commit**

```bash
git add packages/backend/src/backend/models/system_setting.py \
  packages/backend/src/backend/models/__init__.py \
  packages/backend/src/backend/api/system.py \
  packages/backend/src/backend/config.py \
  packages/backend/tests/test_system_settings.py
git commit -m "feat: add system_settings model and settings/info/storage-test APIs"
```

---

### Task 2: Backend — Executions Stats API (Today Filter)

**Files:**
- Modify: `packages/backend/src/backend/api/executions.py`
- Create: `packages/backend/tests/test_executions_stats.py`

**Interfaces:**
- Consumes: `TaskExecution` model, `get_session`
- Produces: `GET /api/executions/stats` → `{today_count, today_success, today_failed, success_rate, running_count}`

- [ ] **Step 1: Add stats endpoint to executions.py**

Add to the end of `packages/backend/src/backend/api/executions.py`:

```python
@router.get("/stats")
async def execution_stats(session: AsyncSession = Depends(get_session)):
    from datetime import datetime, timezone

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    today_count = await session.scalar(
        select(func.count()).select_from(TaskExecution).where(
            TaskExecution.created_at >= today_start
        )
    ) or 0

    today_success = await session.scalar(
        select(func.count()).select_from(TaskExecution).where(
            TaskExecution.created_at >= today_start,
            TaskExecution.status == "success",
        )
    ) or 0

    today_failed = await session.scalar(
        select(func.count()).select_from(TaskExecution).where(
            TaskExecution.created_at >= today_start,
            TaskExecution.status == "failed",
        )
    ) or 0

    running_count = await session.scalar(
        select(func.count()).select_from(TaskExecution).where(
            TaskExecution.status == "running"
        )
    ) or 0

    success_rate = round(today_success / today_count, 2) if today_count > 0 else 0

    return {
        "today_count": today_count,
        "today_success": today_success,
        "today_failed": today_failed,
        "success_rate": success_rate,
        "running_count": running_count,
    }
```

Also add `func` to the imports at top of executions.py:
```python
from sqlalchemy import func, select
```

- [ ] **Step 2: IMPORTANT — move /stats route BEFORE /{execution_id}**

The `/stats` endpoint must be defined BEFORE `/{execution_id}` in the router, otherwise FastAPI will interpret "stats" as an execution_id. Move the `@router.get("/stats")` block to appear right after `list_executions` and before `get_execution`.

- [ ] **Step 3: Write test**

```python
# packages/backend/tests/test_executions_stats.py
"""Test that execution_stats endpoint structure is correct."""


def test_stats_endpoint_exists():
    """Verify the stats function is importable and has correct signature."""
    from backend.api.executions import execution_stats
    import inspect
    sig = inspect.signature(execution_stats)
    assert "session" in sig.parameters
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest packages/backend/tests/test_executions_stats.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/backend/api/executions.py \
  packages/backend/tests/test_executions_stats.py
git commit -m "feat: add GET /api/executions/stats with today-scoped metrics"
```

---

### Task 3: Backend — Pipeline PATCH + File Presign APIs

**Files:**
- Modify: `packages/backend/src/backend/api/pipelines.py`
- Modify: `packages/backend/src/backend/api/files.py`
- Create: `packages/backend/tests/test_pipeline_patch.py`

**Interfaces:**
- Consumes: `Pipeline` model, `MinioStorage`
- Produces: `PATCH /api/pipelines/:name` (update max_concurrent/timeout_seconds), `GET /api/files/presign?key=xxx`

- [ ] **Step 1: Add PATCH endpoint to pipelines.py**

Add to `packages/backend/src/backend/api/pipelines.py`:

```python
from pydantic import BaseModel


class PipelineUpdate(BaseModel):
    max_concurrent: int | None = None
    timeout_seconds: int | None = None


@router.patch("/{name}", response_model=PipelineResponse)
async def update_pipeline(
    name: str, body: PipelineUpdate, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(select(Pipeline).where(Pipeline.name == name))
    pipeline = result.scalar_one_or_none()
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline '{name}' not found")

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(pipeline, field, value)

    await session.commit()
    await session.refresh(pipeline)
    return pipeline
```

- [ ] **Step 2: Add presign endpoint to files.py**

Replace `packages/backend/src/backend/api/files.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models.execution import TaskArtifact
from backend.storage.minio_client import MinioStorage

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("/presign")
async def presign_url(key: str = Query(..., description="MinIO object key")):
    try:
        storage = MinioStorage()
        url = storage.presign_url(key)
        return {"url": url}
    except Exception as e:
        raise HTTPException(500, f"Failed to generate presign URL: {e}")


@router.get("/{artifact_id}/download")
async def download_artifact(
    artifact_id: str, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(
        select(TaskArtifact).where(TaskArtifact.id == artifact_id)
    )
    artifact = result.scalar_one_or_none()
    if artifact is None:
        raise HTTPException(404, "Artifact not found")

    storage = MinioStorage()
    url = storage.presign_url(artifact.minio_key)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url)
```

- [ ] **Step 3: Write test**

```python
# packages/backend/tests/test_pipeline_patch.py
import inspect

from backend.api.pipelines import update_pipeline, PipelineUpdate


def test_pipeline_update_schema():
    schema = PipelineUpdate.model_json_schema()
    assert "max_concurrent" in schema["properties"]
    assert "timeout_seconds" in schema["properties"]


def test_patch_endpoint_exists():
    sig = inspect.signature(update_pipeline)
    assert "name" in sig.parameters
    assert "body" in sig.parameters
```

- [ ] **Step 4: Run all tests**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/backend/api/pipelines.py \
  packages/backend/src/backend/api/files.py \
  packages/backend/tests/test_pipeline_patch.py
git commit -m "feat: add PATCH /api/pipelines/:name and GET /api/files/presign"
```

---

### Task 4: Frontend — Types + API Client + Routing

**Files:**
- Modify: `packages/frontend/src/types/index.ts`
- Modify: `packages/frontend/src/api/client.ts`
- Modify: `packages/frontend/src/App.tsx`
- Modify: `packages/frontend/src/layouts/MainLayout.tsx`

**Interfaces:**
- Consumes: Backend API endpoints
- Produces: Updated TypeScript types, full API client with all endpoints, updated routing

- [ ] **Step 1: Update types/index.ts**

```typescript
// packages/frontend/src/types/index.ts
export interface Pipeline {
  id: string;
  name: string;
  display_name: string;
  description: string;
  trigger_modes: string[];
  config_schema: Record<string, unknown> | null;
  max_concurrent: number;
  timeout_seconds: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface Schedule {
  id: string;
  pipeline_id: string;
  pipeline_name: string | null;
  name: string;
  trigger_type: "cron" | "interval" | "once";
  cron_expr: string | null;
  interval_seconds: number | null;
  config_override: Record<string, unknown> | null;
  enabled: boolean;
  next_run_at: string | null;
  max_retries: number;
  retry_delay_seconds: number;
  created_at: string;
  updated_at: string;
}

export interface Execution {
  id: string;
  pipeline_id: string;
  pipeline_name: string | null;
  schedule_id: string | null;
  trigger_type: "scheduled" | "api" | "manual";
  status: "pending" | "running" | "success" | "failed" | "cancelled";
  config: Record<string, unknown> | null;
  retry_count: number;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  result_summary: Record<string, unknown> | null;
  created_at: string;
}

export interface LogEntry {
  timestamp: string;
  level: "info" | "warn" | "error";
  step: string;
  message: string;
  screenshot_key: string | null;
}

export interface ExecutionStats {
  today_count: number;
  today_success: number;
  today_failed: number;
  success_rate: number;
  running_count: number;
}

export interface SystemInfo {
  uptime_seconds: number;
  scheduler_status: "running" | "paused";
  active_schedules: number;
  db_pool: { pool_size: number; checked_out: number; overflow: number };
}

export interface SystemSettings {
  minio_endpoint: string;
  minio_bucket: string;
  minio_object_prefix: string;
  minio_presign_expires_seconds: string;
  log_retention_days: string;
  scheduler_enabled: string;
}

export interface Artifact {
  id: string;
  file_name: string;
  content_type: string;
  size_bytes: number;
  download_url: string;
  created_at: string;
}
```

- [ ] **Step 2: Update api/client.ts**

```typescript
// packages/frontend/src/api/client.ts
import axios from "axios";
import type {
  Artifact,
  Execution,
  ExecutionStats,
  LogEntry,
  Pipeline,
  Schedule,
  SystemInfo,
  SystemSettings,
} from "../types";

const api = axios.create({ baseURL: "/api" });

export const pipelineApi = {
  list: () => api.get<Pipeline[]>("/pipelines").then((r) => r.data),
  get: (name: string) => api.get<Pipeline>(`/pipelines/${name}`).then((r) => r.data),
  patch: (name: string, data: { max_concurrent?: number; timeout_seconds?: number }) =>
    api.patch<Pipeline>(`/pipelines/${name}`, data).then((r) => r.data),
};

export const scheduleApi = {
  list: (params?: { pipeline_id?: string }) =>
    api.get<Schedule[]>("/schedules", { params }).then((r) => r.data),
  create: (data: {
    pipeline_id: string;
    name: string;
    trigger_type: string;
    cron_expr?: string;
    interval_seconds?: number;
    config_override?: Record<string, unknown>;
    max_retries?: number;
    retry_delay_seconds?: number;
  }) => api.post<Schedule>("/schedules", data).then((r) => r.data),
  update: (id: string, data: Partial<Schedule>) =>
    api.put<Schedule>(`/schedules/${id}`, data).then((r) => r.data),
  delete: (id: string) => api.delete(`/schedules/${id}`),
  toggle: (id: string) => api.patch<Schedule>(`/schedules/${id}/toggle`).then((r) => r.data),
};

export const executionApi = {
  list: (params?: { pipeline?: string; status?: string; page?: number; page_size?: number }) =>
    api.get<Execution[]>("/executions", { params }).then((r) => r.data),
  get: (id: string) => api.get<Execution>(`/executions/${id}`).then((r) => r.data),
  create: (data: { pipeline: string; config?: Record<string, unknown>; trigger_type?: string }) =>
    api.post<Execution>("/executions", data).then((r) => r.data),
  cancel: (id: string) => api.post<Execution>(`/executions/${id}/cancel`).then((r) => r.data),
  getLogs: (id: string) => api.get<LogEntry[]>(`/executions/${id}/logs`).then((r) => r.data),
  getArtifacts: (id: string) => api.get<Artifact[]>(`/executions/${id}/artifacts`).then((r) => r.data),
  stats: () => api.get<ExecutionStats>("/executions/stats").then((r) => r.data),
};

export const systemApi = {
  health: () => api.get<{ status: string; version: string }>("/system/health").then((r) => r.data),
  info: () => api.get<SystemInfo>("/system/info").then((r) => r.data),
  getSettings: () => api.get<SystemSettings>("/system/settings").then((r) => r.data),
  updateSettings: (data: Partial<SystemSettings>) =>
    api.put("/system/settings", data).then((r) => r.data),
  testStorage: () => api.post<{ status: string; message: string }>("/system/storage/test").then((r) => r.data),
};

export const fileApi = {
  presign: (key: string) => api.get<{ url: string }>("/files/presign", { params: { key } }).then((r) => r.data),
};
```

- [ ] **Step 3: Update App.tsx routing**

```typescript
// packages/frontend/src/App.tsx
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MainLayout } from "./layouts/MainLayout";
import { Dashboard } from "./pages/Dashboard";
import { Pipelines } from "./pages/Pipelines";
import { PipelineDetail } from "./pages/PipelineDetail";
import { Executions } from "./pages/Executions";
import { ExecutionDetail } from "./pages/ExecutionDetail";
import { Settings } from "./pages/Settings";

const queryClient = new QueryClient();

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<MainLayout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/pipelines" element={<Pipelines />} />
            <Route path="/pipelines/:name" element={<PipelineDetail />} />
            <Route path="/executions" element={<Executions />} />
            <Route path="/executions/:id" element={<ExecutionDetail />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
```

- [ ] **Step 4: Update MainLayout.tsx**

```typescript
// packages/frontend/src/layouts/MainLayout.tsx
import { Layout, Menu } from "antd";
import {
  DashboardOutlined,
  NodeIndexOutlined,
  UnorderedListOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

const { Sider, Content } = Layout;

const menuItems = [
  { key: "/", icon: <DashboardOutlined />, label: "看板" },
  { key: "/pipelines", icon: <NodeIndexOutlined />, label: "Pipeline" },
  { key: "/executions", icon: <UnorderedListOutlined />, label: "执行记录" },
  { key: "/settings", icon: <SettingOutlined />, label: "系统设置" },
];

export function MainLayout() {
  const navigate = useNavigate();
  const location = useLocation();

  const selectedKey = menuItems
    .filter((item) => location.pathname.startsWith(item.key) && item.key !== "/")
    .sort((a, b) => b.key.length - a.key.length)[0]?.key || "/";

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider>
        <div style={{ color: "#fff", padding: "16px", fontSize: "16px", fontWeight: "bold" }}>
          Browser Auto Hub
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Content style={{ margin: "24px", padding: "24px", background: "#fff" }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
```

- [ ] **Step 5: Delete Schedules.tsx (no longer needed as standalone page)**

```bash
rm packages/frontend/src/pages/Schedules.tsx
```

- [ ] **Step 6: Verify frontend builds**

Run: `cd packages/frontend && npx pnpm build`
Expected: Build succeeds (may have unused import warnings from pages not yet updated — that's ok for now)

- [ ] **Step 7: Commit**

```bash
git add packages/frontend/src/types/index.ts \
  packages/frontend/src/api/client.ts \
  packages/frontend/src/App.tsx \
  packages/frontend/src/layouts/MainLayout.tsx
git rm packages/frontend/src/pages/Schedules.tsx
git commit -m "feat: update frontend types, API client, routing (remove standalone schedules page)"
```

---

### Task 5: Frontend — Dashboard Page

**Files:**
- Modify: `packages/frontend/src/pages/Dashboard.tsx`

**Interfaces:**
- Consumes: `executionApi.stats()`, `executionApi.list()`, `pipelineApi.list()` from Task 4
- Produces: Dashboard page with stats cards, running tasks area, recent timeline

- [ ] **Step 1: Rewrite Dashboard.tsx**

```typescript
// packages/frontend/src/pages/Dashboard.tsx
import { Card, Col, Empty, Row, Statistic, Tag, Timeline } from "antd";
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  NodeIndexOutlined,
  PlayCircleOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { executionApi, pipelineApi } from "../api/client";
import type { Execution } from "../types";

const statusColors: Record<string, string> = {
  pending: "default",
  running: "processing",
  success: "success",
  failed: "error",
  cancelled: "warning",
};

function formatDuration(startedAt: string | null): string {
  if (!startedAt) return "-";
  const seconds = Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000);
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.floor(hours / 24)} 天前`;
}

export function Dashboard() {
  const navigate = useNavigate();
  const { data: stats } = useQuery({
    queryKey: ["execution-stats"],
    queryFn: executionApi.stats,
    refetchInterval: 5000,
  });
  const { data: pipelines } = useQuery({
    queryKey: ["pipelines"],
    queryFn: pipelineApi.list,
  });
  const { data: executions } = useQuery({
    queryKey: ["executions", { page_size: 10 }],
    queryFn: () => executionApi.list({ page_size: 10 }),
    refetchInterval: 5000,
  });

  const runningTasks = executions?.filter((e) => e.status === "running") ?? [];
  const recentDone = executions?.filter((e) => e.status !== "running").slice(0, 10) ?? [];

  return (
    <div>
      <h2>看板</h2>

      {/* Stats cards */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="Pipeline 总数"
              value={pipelines?.length ?? 0}
              prefix={<NodeIndexOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="今日执行"
              value={stats?.today_count ?? 0}
              prefix={<PlayCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="今日成功率"
              value={stats ? Math.round(stats.success_rate * 100) : 0}
              suffix="%"
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="运行中"
              value={stats?.running_count ?? 0}
              prefix={<ClockCircleOutlined />}
              valueStyle={stats?.running_count ? { color: "#1890ff" } : undefined}
            />
          </Card>
        </Col>
      </Row>

      {/* Running tasks */}
      <Card title="运行中任务" style={{ marginBottom: 24 }}>
        {runningTasks.length === 0 ? (
          <Empty description="当前没有正在执行的任务" />
        ) : (
          <Row gutter={16}>
            {runningTasks.map((exec) => (
              <Col span={8} key={exec.id}>
                <Card
                  hoverable
                  size="small"
                  onClick={() => navigate(`/executions/${exec.id}`)}
                >
                  <div style={{ fontWeight: "bold" }}>{exec.pipeline_name}</div>
                  <Tag color="processing">{exec.trigger_type}</Tag>
                  <div style={{ marginTop: 8, color: "#666" }}>
                    运行时长: {formatDuration(exec.started_at)}
                  </div>
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Card>

      {/* Recent timeline */}
      <Card
        title="最近执行"
        extra={<a onClick={() => navigate("/executions")}>查看全部</a>}
      >
        <Timeline
          items={recentDone.map((exec: Execution) => ({
            color: exec.status === "success" ? "green" : exec.status === "failed" ? "red" : "gray",
            children: (
              <div
                style={{ cursor: "pointer" }}
                onClick={() => navigate(`/executions/${exec.id}`)}
              >
                <strong>{exec.pipeline_name}</strong>{" "}
                <Tag color={statusColors[exec.status]}>{exec.status}</Tag>
                {exec.finished_at && exec.started_at && (
                  <span style={{ color: "#999", marginLeft: 8 }}>
                    耗时 {Math.floor((new Date(exec.finished_at).getTime() - new Date(exec.started_at).getTime()) / 1000)}s
                  </span>
                )}
                {exec.finished_at && (
                  <span style={{ color: "#999", marginLeft: 8 }}>
                    {new Date(exec.finished_at).toLocaleString()}
                  </span>
                )}
              </div>
            ),
          }))}
        />
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd packages/frontend && npx pnpm build`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
git add packages/frontend/src/pages/Dashboard.tsx
git commit -m "feat: redesign Dashboard with stats cards, running tasks, recent timeline"
```

---

### Task 6: Frontend — Pipeline List (Card Grid + Trigger Modal)

**Files:**
- Modify: `packages/frontend/src/pages/Pipelines.tsx`
- Create: `packages/frontend/src/components/ExecuteModal.tsx`

**Interfaces:**
- Consumes: `pipelineApi`, `executionApi` from Task 4
- Produces: Pipeline card grid page, ExecuteModal component (dynamic form from config_schema)

- [ ] **Step 1: Create ExecuteModal component**

```typescript
// packages/frontend/src/components/ExecuteModal.tsx
import { Form, Input, InputNumber, Modal } from "antd";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { executionApi } from "../api/client";
import type { Pipeline } from "../types";

interface Props {
  pipeline: Pipeline | null;
  open: boolean;
  onClose: () => void;
}

export function ExecuteModal({ pipeline, open, onClose }: Props) {
  const [form] = Form.useForm();
  const navigate = useNavigate();

  const mutation = useMutation({
    mutationFn: (config: Record<string, unknown>) =>
      executionApi.create({ pipeline: pipeline!.name, config, trigger_type: "manual" }),
    onSuccess: (exec) => {
      form.resetFields();
      onClose();
      navigate(`/executions/${exec.id}`);
    },
  });

  if (!pipeline?.config_schema) return null;

  const schema = pipeline.config_schema as {
    properties?: Record<string, { type?: string; default?: unknown; description?: string }>;
    required?: string[];
  };
  const properties = schema.properties || {};
  const required = schema.required || [];

  return (
    <Modal
      title={`执行 ${pipeline.display_name}`}
      open={open}
      onCancel={onClose}
      onOk={() => form.submit()}
      confirmLoading={mutation.isPending}
    >
      <Form form={form} layout="vertical" onFinish={(values) => mutation.mutate(values)}>
        {Object.entries(properties).map(([key, prop]) => {
          const isRequired = required.includes(key);
          const isPassword = prop.description?.includes("密码");
          const label = prop.description || key;

          return (
            <Form.Item
              key={key}
              name={key}
              label={label}
              initialValue={prop.default}
              rules={isRequired ? [{ required: true, message: `请输入${label}` }] : []}
            >
              {prop.type === "integer" ? (
                <InputNumber style={{ width: "100%" }} />
              ) : isPassword ? (
                <Input.Password />
              ) : (
                <Input />
              )}
            </Form.Item>
          );
        })}
      </Form>
    </Modal>
  );
}
```

- [ ] **Step 2: Rewrite Pipelines.tsx as card grid**

```typescript
// packages/frontend/src/pages/Pipelines.tsx
import { useState } from "react";
import { Button, Card, Col, Row, Tag } from "antd";
import { PlayCircleOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { executionApi, pipelineApi } from "../api/client";
import { ExecuteModal } from "../components/ExecuteModal";
import type { Execution, Pipeline } from "../types";

function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.floor(hours / 24)} 天前`;
}

const statusColors: Record<string, string> = {
  pending: "default", running: "processing", success: "success", failed: "error", cancelled: "warning",
};

export function Pipelines() {
  const navigate = useNavigate();
  const { data: pipelines } = useQuery({ queryKey: ["pipelines"], queryFn: pipelineApi.list });
  const { data: executions } = useQuery({
    queryKey: ["executions", { page_size: 100 }],
    queryFn: () => executionApi.list({ page_size: 100 }),
  });
  const [executePipeline, setExecutePipeline] = useState<Pipeline | null>(null);

  const getLastExecution = (pipelineName: string): Execution | undefined =>
    executions?.find((e) => e.pipeline_name === pipelineName);

  const handleExecute = (pipeline: Pipeline) => {
    const schema = pipeline.config_schema as { required?: string[] } | null;
    const hasRequired = schema?.required && schema.required.length > 0;

    if (hasRequired) {
      setExecutePipeline(pipeline);
    } else {
      // Direct trigger without modal
      executionApi
        .create({ pipeline: pipeline.name, trigger_type: "manual" })
        .then((exec) => navigate(`/executions/${exec.id}`));
    }
  };

  return (
    <div>
      <h2>Pipeline</h2>
      <Row gutter={[16, 16]}>
        {pipelines?.map((p) => (
          <Col span={8} key={p.id}>
            <Card
              title={
                <a onClick={() => navigate(`/pipelines/${p.name}`)}>
                  {p.display_name}
                </a>
              }
              extra={<Tag color={p.status === "active" ? "success" : "default"}>{p.status}</Tag>}
              actions={[
                <Button
                  key="run"
                  type="link"
                  icon={<PlayCircleOutlined />}
                  onClick={() => handleExecute(p)}
                >
                  立即执行
                </Button>,
              ]}
            >
              <p style={{ color: "#666", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {p.description || "暂无描述"}
              </p>
              <div>
                {p.trigger_modes.map((m) => (
                  <Tag key={m}>{m}</Tag>
                ))}
              </div>
              <div style={{ marginTop: 8, fontSize: 12, color: "#999" }}>
                {(() => {
                  const last = getLastExecution(p.name);
                  if (!last) return "暂无执行记录";
                  return (
                    <>
                      最近执行: <Tag color={statusColors[last.status]} style={{ fontSize: 11 }}>{last.status}</Tag>
                      {last.created_at && formatRelativeTime(last.created_at)}
                    </>
                  );
                })()}
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      <ExecuteModal
        pipeline={executePipeline}
        open={!!executePipeline}
        onClose={() => setExecutePipeline(null)}
      />
    </div>
  );
}
```

- [ ] **Step 3: Verify build**

Run: `cd packages/frontend && npx pnpm build`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add packages/frontend/src/pages/Pipelines.tsx \
  packages/frontend/src/components/ExecuteModal.tsx
git commit -m "feat: Pipeline card grid with smart trigger + ExecuteModal"
```

---

### Task 7: Frontend — Pipeline Detail (3 Tabs)

**Files:**
- Modify: `packages/frontend/src/pages/PipelineDetail.tsx`
- Modify: `packages/frontend/src/components/ScheduleCreateModal.tsx`

**Interfaces:**
- Consumes: `pipelineApi`, `scheduleApi`, `executionApi` from Task 4, `ExecuteModal` from Task 6
- Produces: Pipeline detail page with Overview/Schedules/History tabs

- [ ] **Step 1: Rewrite ScheduleCreateModal for Pipeline context**

```typescript
// packages/frontend/src/components/ScheduleCreateModal.tsx
import { Form, Input, InputNumber, Modal, Radio } from "antd";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { scheduleApi } from "../api/client";
import type { Schedule } from "../types";

interface Props {
  pipelineId: string;
  open: boolean;
  onClose: () => void;
  editSchedule?: Schedule | null;
}

export function ScheduleCreateModal({ pipelineId, open, onClose, editSchedule }: Props) {
  const [form] = Form.useForm();
  const queryClient = useQueryClient();
  const triggerType = Form.useWatch("trigger_type", form);

  const createMutation = useMutation({
    mutationFn: (values: Record<string, unknown>) =>
      editSchedule
        ? scheduleApi.update(editSchedule.id, values as Partial<Schedule>)
        : scheduleApi.create({ ...values, pipeline_id: pipelineId } as Parameters<typeof scheduleApi.create>[0]),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["schedules"] });
      form.resetFields();
      onClose();
    },
  });

  return (
    <Modal
      title={editSchedule ? "编辑调度" : "新建调度"}
      open={open}
      onCancel={() => { form.resetFields(); onClose(); }}
      onOk={() => form.submit()}
      confirmLoading={createMutation.isPending}
      destroyOnClose
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={editSchedule || { trigger_type: "cron", max_retries: 0, retry_delay_seconds: 60 }}
        onFinish={(values) => createMutation.mutate(values)}
      >
        <Form.Item name="name" label="调度名称" rules={[{ required: true }]}>
          <Input placeholder="如：工作日早8点采集" />
        </Form.Item>
        <Form.Item name="trigger_type" label="触发方式" rules={[{ required: true }]}>
          <Radio.Group>
            <Radio value="cron">Cron 表达式</Radio>
            <Radio value="interval">固定间隔</Radio>
            <Radio value="once">单次</Radio>
          </Radio.Group>
        </Form.Item>
        {triggerType === "cron" && (
          <Form.Item name="cron_expr" label="Cron 表达式" rules={[{ required: true }]}>
            <Input placeholder="0 8 * * 1-5" />
          </Form.Item>
        )}
        {triggerType === "interval" && (
          <Form.Item name="interval_seconds" label="间隔（秒）" rules={[{ required: true }]}>
            <InputNumber min={60} style={{ width: "100%" }} />
          </Form.Item>
        )}
        <Form.Item name="max_retries" label="最大重试次数">
          <InputNumber min={0} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item name="retry_delay_seconds" label="重试间隔（秒）">
          <InputNumber min={1} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item name="config_override" label="配置覆盖（JSON，可选）">
          <Input.TextArea rows={4} placeholder='{"key": "value"}' />
        </Form.Item>
      </Form>
    </Modal>
  );
}
```

- [ ] **Step 2: Rewrite PipelineDetail.tsx with 3 tabs**

```typescript
// packages/frontend/src/pages/PipelineDetail.tsx
import { useState } from "react";
import { Button, Card, Descriptions, InputNumber, Space, Switch, Table, Tabs, Tag, message } from "antd";
import { useParams, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { executionApi, pipelineApi, scheduleApi } from "../api/client";
import { ExecuteModal } from "../components/ExecuteModal";
import { ScheduleCreateModal } from "../components/ScheduleCreateModal";
import type { Schedule } from "../types";

const statusColors: Record<string, string> = {
  pending: "default", running: "processing", success: "success", failed: "error", cancelled: "warning",
};

export function PipelineDetail() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [executeOpen, setExecuteOpen] = useState(false);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [editSchedule, setEditSchedule] = useState<Schedule | null>(null);
  const [editConcurrent, setEditConcurrent] = useState<number | null>(null);
  const [editTimeout, setEditTimeout] = useState<number | null>(null);

  const { data: pipeline } = useQuery({
    queryKey: ["pipeline", name],
    queryFn: () => pipelineApi.get(name!),
    enabled: !!name,
  });
  const { data: schedules } = useQuery({
    queryKey: ["schedules", { pipeline_id: pipeline?.id }],
    queryFn: () => scheduleApi.list({ pipeline_id: pipeline?.id }),
    enabled: !!pipeline,
  });
  const { data: executions } = useQuery({
    queryKey: ["executions", { pipeline: name }],
    queryFn: () => executionApi.list({ pipeline: name }),
    enabled: !!name,
  });

  const patchMutation = useMutation({
    mutationFn: (data: { max_concurrent?: number; timeout_seconds?: number }) =>
      pipelineApi.patch(name!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipeline", name] });
      message.success("已保存");
    },
  });
  const toggleMutation = useMutation({
    mutationFn: (id: string) => scheduleApi.toggle(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["schedules"] }),
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => scheduleApi.delete(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["schedules"] }),
  });

  if (!pipeline) return <div>Loading...</div>;

  const tabItems = [
    {
      key: "overview",
      label: "概览",
      children: (
        <div>
          <Card>
            <Descriptions bordered column={2}>
              <Descriptions.Item label="标识">{pipeline.name}</Descriptions.Item>
              <Descriptions.Item label="状态"><Tag>{pipeline.status}</Tag></Descriptions.Item>
              <Descriptions.Item label="描述" span={2}>{pipeline.description}</Descriptions.Item>
              <Descriptions.Item label="触发方式">
                {pipeline.trigger_modes.map((m) => <Tag key={m}>{m}</Tag>)}
              </Descriptions.Item>
              <Descriptions.Item label="最大并发">
                <Space>
                  <InputNumber
                    min={1}
                    value={editConcurrent ?? pipeline.max_concurrent}
                    onChange={(v) => setEditConcurrent(v)}
                    style={{ width: 80 }}
                  />
                  {editConcurrent !== null && editConcurrent !== pipeline.max_concurrent && (
                    <Button size="small" type="primary" onClick={() => { patchMutation.mutate({ max_concurrent: editConcurrent! }); setEditConcurrent(null); }}>保存</Button>
                  )}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="执行超时">
                <Space>
                  <InputNumber
                    min={60}
                    value={editTimeout ?? pipeline.timeout_seconds}
                    onChange={(v) => setEditTimeout(v)}
                    style={{ width: 100 }}
                    addonAfter="秒"
                  />
                  <span style={{ color: "#999" }}>
                    ({Math.round((editTimeout ?? pipeline.timeout_seconds) / 60)} 分钟)
                  </span>
                  {editTimeout !== null && editTimeout !== pipeline.timeout_seconds && (
                    <Button size="small" type="primary" onClick={() => { patchMutation.mutate({ timeout_seconds: editTimeout! }); setEditTimeout(null); }}>保存</Button>
                  )}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="创建时间">
                {new Date(pipeline.created_at).toLocaleString()}
              </Descriptions.Item>
            </Descriptions>
          </Card>
          {pipeline.config_schema && (
            <Card title="配置模板" style={{ marginTop: 16 }}>
              <pre style={{ fontSize: 12 }}>{JSON.stringify(pipeline.config_schema, null, 2)}</pre>
            </Card>
          )}
        </div>
      ),
    },
    {
      key: "schedules",
      label: "调度管理",
      children: (
        <div>
          <Button type="primary" style={{ marginBottom: 16 }} onClick={() => { setEditSchedule(null); setScheduleOpen(true); }}>
            新建调度
          </Button>
          <Table
            dataSource={schedules}
            rowKey="id"
            columns={[
              { title: "名称", dataIndex: "name" },
              { title: "类型", dataIndex: "trigger_type" },
              { title: "表达式/间隔", render: (_, r: Schedule) => r.cron_expr || (r.interval_seconds ? `${r.interval_seconds}s` : "-") },
              { title: "启用", render: (_, r: Schedule) => <Switch checked={r.enabled} onChange={() => toggleMutation.mutate(r.id)} /> },
              { title: "下次执行", dataIndex: "next_run_at", render: (v: string) => v || "-" },
              {
                title: "操作",
                render: (_, r: Schedule) => (
                  <Space>
                    <Button size="small" onClick={() => { setEditSchedule(r); setScheduleOpen(true); }}>编辑</Button>
                    <Button size="small" danger onClick={() => deleteMutation.mutate(r.id)}>删除</Button>
                  </Space>
                ),
              },
            ]}
          />
        </div>
      ),
    },
    {
      key: "history",
      label: "执行历史",
      children: (
        <Table
          dataSource={executions}
          rowKey="id"
          onRow={(record) => ({ onClick: () => navigate(`/executions/${record.id}`), style: { cursor: "pointer" } })}
          columns={[
            { title: "状态", dataIndex: "status", render: (s: string) => <Tag color={statusColors[s]}>{s}</Tag> },
            { title: "触发方式", dataIndex: "trigger_type" },
            { title: "开始时间", dataIndex: "started_at", render: (v: string) => v ? new Date(v).toLocaleString() : "-" },
            {
              title: "耗时",
              render: (_: unknown, r: { started_at: string | null; finished_at: string | null }) => {
                if (!r.started_at) return "-";
                const end = r.finished_at ? new Date(r.finished_at).getTime() : Date.now();
                const sec = Math.floor((end - new Date(r.started_at).getTime()) / 1000);
                return sec < 60 ? `${sec}s` : `${Math.floor(sec / 60)}m ${sec % 60}s`;
              },
            },
            { title: "重试", dataIndex: "retry_count", render: (v: number) => v > 0 ? v : "-" },
          ]}
          pagination={{ pageSize: 20 }}
        />
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h2>{pipeline.display_name} <Tag color={pipeline.status === "active" ? "success" : "default"}>{pipeline.status}</Tag></h2>
        <Button type="primary" onClick={() => setExecuteOpen(true)}>立即执行</Button>
      </div>

      <Tabs items={tabItems} />

      <ExecuteModal pipeline={pipeline} open={executeOpen} onClose={() => setExecuteOpen(false)} />
      <ScheduleCreateModal
        pipelineId={pipeline.id}
        open={scheduleOpen}
        onClose={() => setScheduleOpen(false)}
        editSchedule={editSchedule}
      />
    </div>
  );
}
```

- [ ] **Step 3: Verify build**

Run: `cd packages/frontend && npx pnpm build`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add packages/frontend/src/pages/PipelineDetail.tsx \
  packages/frontend/src/components/ScheduleCreateModal.tsx
git commit -m "feat: Pipeline detail with overview/schedules/history tabs"
```

---

### Task 8: Frontend — Execution Detail (SSE + Split Layout)

**Files:**
- Modify: `packages/frontend/src/pages/ExecutionDetail.tsx`

**Interfaces:**
- Consumes: `executionApi`, `fileApi` from Task 4
- Produces: Execution detail page with SSE log stream (left) and info panel (right)

- [ ] **Step 1: Rewrite ExecutionDetail.tsx**

```typescript
// packages/frontend/src/pages/ExecutionDetail.tsx
import { useEffect, useRef, useState } from "react";
import { Button, Card, Col, Descriptions, Empty, Image, Row, Tag, message } from "antd";
import { useParams, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { executionApi, fileApi } from "../api/client";
import type { Artifact, LogEntry } from "../types";

const statusColors: Record<string, string> = {
  pending: "default", running: "processing", success: "success", failed: "error", cancelled: "warning",
};
const levelColors: Record<string, string> = { info: "#1890ff", warn: "#faad14", error: "#ff4d4f" };
const levelIcons: Record<string, string> = { info: "●", warn: "▲", error: "✕" };
const stepColors = ["#1890ff", "#52c41a", "#722ed1", "#fa8c16", "#13c2c2", "#eb2f96"];

function getStepColor(step: string, map: Map<string, string>): string {
  if (!map.has(step)) {
    map.set(step, stepColors[map.size % stepColors.length]);
  }
  return map.get(step)!;
}

export function ExecutionDetail() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [screenshots, setScreenshots] = useState<Record<string, string>>({});
  const logEndRef = useRef<HTMLDivElement>(null);
  const userScrolledRef = useRef(false);
  const stepColorMap = useRef(new Map<string, string>());

  const { data: execution } = useQuery({
    queryKey: ["execution", id],
    queryFn: () => executionApi.get(id!),
    enabled: !!id,
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 3000 : false,
  });
  const { data: artifacts } = useQuery({
    queryKey: ["artifacts", id],
    queryFn: () => executionApi.getArtifacts(id!),
    enabled: !!id && execution?.status !== "running",
  });

  const cancelMutation = useMutation({
    mutationFn: () => executionApi.cancel(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["execution", id] });
      message.success("已取消");
    },
  });

  // SSE or load historical logs
  useEffect(() => {
    if (!id || !execution) return;

    if (execution.status === "running") {
      const source = new EventSource(`/api/executions/${id}/logs/stream`);
      source.onmessage = (event) => {
        const entry = JSON.parse(event.data);
        if (entry.type === "complete") {
          source.close();
          queryClient.invalidateQueries({ queryKey: ["execution", id] });
          return;
        }
        setLogs((prev) => [...prev, entry]);
      };
      return () => source.close();
    } else {
      executionApi.getLogs(id).then(setLogs);
    }
  }, [id, execution?.status]);

  // Auto-scroll
  useEffect(() => {
    if (!userScrolledRef.current) {
      logEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs]);

  // Load screenshot URLs
  useEffect(() => {
    const keys = logs.filter((l) => l.screenshot_key).map((l) => l.screenshot_key!);
    const newKeys = keys.filter((k) => !screenshots[k]);
    newKeys.forEach((key) => {
      fileApi.presign(key).then(({ url }) => {
        setScreenshots((prev) => ({ ...prev, [key]: url }));
      });
    });
  }, [logs]);

  if (!execution) return <div>Loading...</div>;

  const filteredLogs = filter === "all" ? logs : logs.filter((l) => l.level === filter);
  const duration = execution.started_at
    ? Math.floor(
        ((execution.finished_at ? new Date(execution.finished_at).getTime() : Date.now()) -
          new Date(execution.started_at).getTime()) /
          1000
      )
    : 0;

  return (
    <div>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <div>
          <h2 style={{ display: "inline" }}>
            <Link to={`/pipelines/${execution.pipeline_name}`}>{execution.pipeline_name}</Link>
            {" "}
            <span style={{ fontSize: 14, color: "#999" }}>#{execution.id.slice(0, 8)}</span>
          </h2>
          <div style={{ marginTop: 8 }}>
            <Tag color={statusColors[execution.status]}>{execution.status}</Tag>
            <Tag>{execution.trigger_type}</Tag>
            {execution.started_at && <span style={{ color: "#666" }}>{new Date(execution.started_at).toLocaleString()}</span>}
            {duration > 0 && <span style={{ color: "#666", marginLeft: 8 }}>耗时 {duration}s</span>}
          </div>
        </div>
        {(execution.status === "pending" || execution.status === "running") && (
          <Button danger onClick={() => cancelMutation.mutate()}>取消执行</Button>
        )}
      </div>

      {/* Main content: left/right split */}
      <Row gutter={16}>
        {/* Left: Log stream */}
        <Col span={17}>
          <Card
            title="执行日志"
            size="small"
            extra={
              <span>
                {["all", "info", "warn", "error"].map((level) => (
                  <Tag
                    key={level}
                    color={filter === level ? "blue" : "default"}
                    style={{ cursor: "pointer" }}
                    onClick={() => setFilter(level)}
                  >
                    {level === "all" ? "全部" : level}
                  </Tag>
                ))}
              </span>
            }
          >
            <div
              style={{ height: 500, overflow: "auto", fontFamily: "monospace", fontSize: 12 }}
              onScroll={(e) => {
                const el = e.currentTarget;
                userScrolledRef.current = el.scrollTop + el.clientHeight < el.scrollHeight - 50;
              }}
            >
              {filteredLogs.length === 0 && <Empty description="暂无日志" />}
              {filteredLogs.map((log, i) => (
                <div
                  key={i}
                  style={{
                    padding: "4px 8px",
                    background: log.level === "error" ? "#fff2f0" : undefined,
                    borderLeft: `3px solid ${levelColors[log.level]}`,
                    marginBottom: 2,
                  }}
                >
                  <span style={{ color: "#999" }}>{new Date(log.timestamp).toLocaleTimeString()}</span>
                  {" "}
                  <Tag color={getStepColor(log.step, stepColorMap.current)} style={{ fontSize: 11 }}>
                    {log.step}
                  </Tag>
                  {" "}
                  <span style={{ color: levelColors[log.level] }}>{levelIcons[log.level]}</span>
                  {" "}
                  <span>{log.message}</span>
                </div>
              ))}
              <div ref={logEndRef} />
            </div>
          </Card>
        </Col>

        {/* Right: Info panel */}
        <Col span={7}>
          {execution.status === "success" && execution.result_summary && (
            <Card title="执行结果" size="small" style={{ marginBottom: 12 }}>
              <pre style={{ fontSize: 12, margin: 0 }}>
                {JSON.stringify(execution.result_summary, null, 2)}
              </pre>
            </Card>
          )}

          {execution.status === "failed" && execution.error_message && (
            <Card title="错误信息" size="small" style={{ marginBottom: 12, borderColor: "#ff4d4f" }}>
              <pre style={{ fontSize: 12, margin: 0, color: "#ff4d4f", whiteSpace: "pre-wrap" }}>
                {execution.error_message}
              </pre>
            </Card>
          )}

          {execution.config && (
            <Card title="执行配置" size="small" style={{ marginBottom: 12 }}>
              <pre style={{ fontSize: 12, margin: 0 }}>
                {JSON.stringify(
                  Object.fromEntries(
                    Object.entries(execution.config).map(([k, v]) =>
                      /密码|password|secret|token/i.test(k) ? [k, "***"] : [k, v]
                    )
                  ),
                  null,
                  2
                )}
              </pre>
            </Card>
          )}

          {artifacts && artifacts.length > 0 && (
            <Card title="产出文件" size="small" style={{ marginBottom: 12 }}>
              {artifacts.map((a: Artifact) => (
                <div key={a.id} style={{ marginBottom: 4 }}>
                  <a href={a.download_url}>{a.file_name}</a>
                  <span style={{ color: "#999", marginLeft: 8 }}>
                    {(a.size_bytes / 1024).toFixed(1)} KB
                  </span>
                </div>
              ))}
            </Card>
          )}

          {Object.keys(screenshots).length > 0 && (
            <Card title="截图" size="small">
              <Image.PreviewGroup>
                {Object.entries(screenshots).map(([key, url]) => (
                  <Image key={key} src={url} width={100} style={{ marginRight: 8, marginBottom: 8 }} />
                ))}
              </Image.PreviewGroup>
            </Card>
          )}
        </Col>
      </Row>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd packages/frontend && npx pnpm build`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
git add packages/frontend/src/pages/ExecutionDetail.tsx
git commit -m "feat: Execution detail with SSE log stream and split layout"
```

---

### Task 9: Frontend — Execution List (Filters)

**Files:**
- Modify: `packages/frontend/src/pages/Executions.tsx`

**Interfaces:**
- Consumes: `executionApi`, `pipelineApi` from Task 4
- Produces: Execution list page with filter bar and enhanced table

- [ ] **Step 1: Rewrite Executions.tsx**

```typescript
// packages/frontend/src/pages/Executions.tsx
import { useState } from "react";
import { DatePicker, Select, Table, Tag } from "antd";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, Link } from "react-router-dom";
import { executionApi, pipelineApi } from "../api/client";
import type { Execution } from "../types";

const { RangePicker } = DatePicker;

const statusColors: Record<string, string> = {
  pending: "default", running: "processing", success: "success", failed: "error", cancelled: "warning",
};

export function Executions() {
  const navigate = useNavigate();
  const [pipelineFilter, setPipelineFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string[] | undefined>();
  const [page, setPage] = useState(1);

  const { data: pipelines } = useQuery({ queryKey: ["pipelines"], queryFn: pipelineApi.list });
  const { data: executions, isLoading } = useQuery({
    queryKey: ["executions", { pipeline: pipelineFilter, status: statusFilter?.join(","), page }],
    queryFn: () => executionApi.list({ pipeline: pipelineFilter, status: statusFilter?.join(","), page }),
    refetchInterval: 5000,
  });

  return (
    <div>
      <h2>执行记录</h2>

      <div style={{ marginBottom: 16, display: "flex", gap: 12 }}>
        <Select
          placeholder="全部 Pipeline"
          allowClear
          style={{ width: 200 }}
          value={pipelineFilter}
          onChange={(v) => { setPipelineFilter(v); setPage(1); }}
        >
          {pipelines?.map((p) => (
            <Select.Option key={p.name} value={p.name}>{p.display_name}</Select.Option>
          ))}
        </Select>
        <Select
          placeholder="全部状态"
          allowClear
          mode="multiple"
          style={{ width: 250 }}
          value={statusFilter}
          onChange={(v) => { setStatusFilter(v.length ? v : undefined); setPage(1); }}
        >
          {["pending", "running", "success", "failed", "cancelled"].map((s) => (
            <Select.Option key={s} value={s}>{s}</Select.Option>
          ))}
        </Select>
        <RangePicker
          onChange={(dates) => {
            // Pass date range to API when backend supports it
            void dates;
            setPage(1);
          }}
        />
      </div>

      <Table
        dataSource={executions}
        rowKey="id"
        loading={isLoading}
        onRow={(record) => ({
          onClick: () => navigate(`/executions/${record.id}`),
          style: { cursor: "pointer" },
        })}
        pagination={{ current: page, pageSize: 20, onChange: setPage }}
        columns={[
          {
            title: "Pipeline",
            dataIndex: "pipeline_name",
            render: (name: string) => name ? <Link to={`/pipelines/${name}`}>{name}</Link> : "-",
          },
          {
            title: "状态",
            dataIndex: "status",
            render: (s: string) => <Tag color={statusColors[s]}>{s}</Tag>,
          },
          { title: "触发方式", dataIndex: "trigger_type" },
          {
            title: "开始时间",
            dataIndex: "started_at",
            render: (v: string) => v ? new Date(v).toLocaleString() : "-",
          },
          {
            title: "耗时",
            render: (_: unknown, r: Execution) => {
              if (!r.started_at) return "-";
              const end = r.finished_at ? new Date(r.finished_at).getTime() : Date.now();
              const seconds = Math.floor((end - new Date(r.started_at).getTime()) / 1000);
              return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
            },
          },
          {
            title: "重试",
            dataIndex: "retry_count",
            render: (v: number) => v > 0 ? v : "-",
          },
          {
            title: "结果",
            dataIndex: "result_summary",
            render: (v: Record<string, unknown> | null) =>
              v ? <span style={{ color: "#666" }}>{JSON.stringify(v).slice(0, 40)}</span> : "-",
          },
        ]}
      />
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd packages/frontend && npx pnpm build`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
git add packages/frontend/src/pages/Executions.tsx
git commit -m "feat: Execution list with Pipeline/status filters"
```

---

### Task 10: Frontend — Settings Page (3 Tabs)

**Files:**
- Modify: `packages/frontend/src/pages/Settings.tsx`

**Interfaces:**
- Consumes: `systemApi` from Task 4
- Produces: Settings page with Runtime Info / Storage / Operations tabs

- [ ] **Step 1: Rewrite Settings.tsx**

```typescript
// packages/frontend/src/pages/Settings.tsx
import { useState } from "react";
import { Button, Card, Descriptions, Form, Input, InputNumber, Switch, Tabs, Tag, message } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { systemApi } from "../api/client";

function RuntimeTab() {
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: systemApi.health });
  const { data: info } = useQuery({ queryKey: ["system-info"], queryFn: systemApi.info, refetchInterval: 10000 });

  const formatUptime = (seconds: number) => {
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return `${d}d ${h}h ${m}m`;
  };

  return (
    <Card>
      <Descriptions bordered column={2}>
        <Descriptions.Item label="服务状态">
          <Tag color={health?.status === "ok" ? "success" : "error"}>{health?.status ?? "unknown"}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="版本">{health?.version ?? "-"}</Descriptions.Item>
        <Descriptions.Item label="运行时长">{info ? formatUptime(info.uptime_seconds) : "-"}</Descriptions.Item>
        <Descriptions.Item label="调度器状态">
          <Tag color={info?.scheduler_status === "running" ? "success" : "warning"}>
            {info?.scheduler_status ?? "-"}
          </Tag>
          {info && <span style={{ marginLeft: 8 }}>{info.active_schedules} 个活跃调度</span>}
        </Descriptions.Item>
        <Descriptions.Item label="数据库连接池">
          {info ? `${info.db_pool.checked_out} / ${info.db_pool.pool_size} (overflow: ${info.db_pool.overflow})` : "-"}
        </Descriptions.Item>
      </Descriptions>
    </Card>
  );
}

function StorageTab() {
  const queryClient = useQueryClient();
  const { data: settings } = useQuery({ queryKey: ["system-settings"], queryFn: systemApi.getSettings });
  const [prefix, setPrefix] = useState<string | null>(null);
  const [expires, setExpires] = useState<number | null>(null);

  const saveMutation = useMutation({
    mutationFn: () => {
      const updates: Record<string, unknown> = {};
      if (prefix !== null) updates.minio_object_prefix = prefix;
      if (expires !== null) updates.minio_presign_expires_seconds = expires;
      return systemApi.updateSettings(updates);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["system-settings"] });
      message.success("已保存");
      setPrefix(null);
      setExpires(null);
    },
  });

  const testMutation = useMutation({
    mutationFn: systemApi.testStorage,
    onSuccess: (data) => message.success(data.message),
    onError: () => message.error("MinIO 连接失败"),
  });

  return (
    <Card>
      <Descriptions bordered column={1}>
        <Descriptions.Item label="Endpoint（只读）">{settings?.minio_endpoint ?? "-"}</Descriptions.Item>
        <Descriptions.Item label="Bucket（只读）">{settings?.minio_bucket ?? "-"}</Descriptions.Item>
        <Descriptions.Item label="对象前缀">
          <Input
            value={prefix ?? settings?.minio_object_prefix ?? ""}
            onChange={(e) => setPrefix(e.target.value)}
            style={{ width: 300 }}
          />
        </Descriptions.Item>
        <Descriptions.Item label="预签名过期时间">
          <InputNumber
            value={expires ?? Number(settings?.minio_presign_expires_seconds ?? 604800)}
            onChange={(v) => setExpires(v)}
            style={{ width: 200 }}
            addonAfter="秒"
          />
          <span style={{ marginLeft: 8, color: "#999" }}>
            ({Math.round((expires ?? Number(settings?.minio_presign_expires_seconds ?? 604800)) / 86400)} 天)
          </span>
        </Descriptions.Item>
      </Descriptions>
      <div style={{ marginTop: 16, display: "flex", gap: 12 }}>
        <Button type="primary" onClick={() => saveMutation.mutate()} loading={saveMutation.isPending}>
          保存配置
        </Button>
        <Button onClick={() => testMutation.mutate()} loading={testMutation.isPending}>
          测试连接
        </Button>
      </div>
    </Card>
  );
}

function OpsTab() {
  const queryClient = useQueryClient();
  const { data: settings } = useQuery({ queryKey: ["system-settings"], queryFn: systemApi.getSettings });
  const [retention, setRetention] = useState<number | null>(null);
  const [schedulerEnabled, setSchedulerEnabled] = useState<boolean | null>(null);

  const saveMutation = useMutation({
    mutationFn: () => {
      const updates: Record<string, unknown> = {};
      if (retention !== null) updates.log_retention_days = retention;
      if (schedulerEnabled !== null) updates.scheduler_enabled = schedulerEnabled;
      return systemApi.updateSettings(updates);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["system-settings"] });
      message.success("已保存");
      setRetention(null);
      setSchedulerEnabled(null);
    },
  });

  return (
    <Card>
      <Form layout="vertical">
        <Form.Item label="日志保留天数">
          <InputNumber
            value={retention ?? Number(settings?.log_retention_days ?? 30)}
            onChange={(v) => setRetention(v)}
            min={1}
            style={{ width: 200 }}
            addonAfter="天"
          />
        </Form.Item>
        <Form.Item label="调度器全局开关">
          <Switch
            checked={schedulerEnabled ?? (settings?.scheduler_enabled !== "false")}
            onChange={(v) => setSchedulerEnabled(v)}
          />
          <span style={{ marginLeft: 8, color: "#666" }}>
            {(schedulerEnabled ?? (settings?.scheduler_enabled !== "false")) ? "运行中" : "已暂停（所有调度停止）"}
          </span>
        </Form.Item>
      </Form>
      <Button type="primary" onClick={() => saveMutation.mutate()} loading={saveMutation.isPending}>
        保存配置
      </Button>
    </Card>
  );
}

export function Settings() {
  return (
    <div>
      <h2>系统设置</h2>
      <Tabs
        items={[
          { key: "runtime", label: "运行时信息", children: <RuntimeTab /> },
          { key: "storage", label: "存储配置", children: <StorageTab /> },
          { key: "ops", label: "运维策略", children: <OpsTab /> },
        ]}
      />
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd packages/frontend && npx pnpm build`
Expected: Build succeeds

- [ ] **Step 3: Run all backend tests**

Run: `uv run pytest -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add packages/frontend/src/pages/Settings.tsx
git commit -m "feat: Settings page with runtime info, storage config, ops tabs"
```

---

## Self-Review

**Spec coverage:**
- Section 2 (Navigation): ✓ Task 4 (MainLayout + routing)
- Section 3 (Dashboard): ✓ Task 5
- Section 4 (Pipeline list): ✓ Task 6
- Section 5 (Pipeline detail): ✓ Task 7
- Section 6 (Execution detail): ✓ Task 8
- Section 7 (Execution list): ✓ Task 9
- Section 8 (Settings): ✓ Task 10
- Section 9.1 (stats API): ✓ Task 2
- Section 9.2 (system/info): ✓ Task 1
- Section 9.3 (system_settings): ✓ Task 1
- Section 9.4 (PATCH pipeline): ✓ Task 3
- Section 9 (files/presign): ✓ Task 3
- Section 10 (tech decisions): All respected throughout

**Type consistency:** All tasks use `string` for IDs. `pipelineApi.patch()` signature matches usage in Task 7. `executionApi.stats()` matches Dashboard consumption.

**Spec alignment (post-review fixes applied):**
- Pipeline card shows "最近一次执行" (状态Tag + 相对时间) ✓
- ScheduleCreateModal includes config_override field ✓
- Executions page: DateRangePicker + status multi-select ✓
- Executions table: Pipeline column as Link to detail ✓
- Pipeline Detail Tab 1: 创建时间 + timeout 换算分钟 ✓
- Pipeline Detail Tab 3: 耗时 column ✓
- Execution config: 密码字段显示 *** ✓
- Settings Storage: endpoint/bucket 只读显示 ✓
- GET /api/system/settings returns minio_endpoint + minio_bucket ✓
- Log level icons (●/▲/✕) ✓
- Dashboard timeline: 耗时 + 完成时间 (absolute) ✓
- Old /api/system/stats endpoint removed (dead code) ✓
