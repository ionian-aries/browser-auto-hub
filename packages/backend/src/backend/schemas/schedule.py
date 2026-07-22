from datetime import datetime

from pydantic import BaseModel


class ScheduleCreate(BaseModel):
    pipeline_id: str
    name: str
    trigger_type: str  # "cron" | "interval" | "once"
    cron_expr: str | None = None
    interval_seconds: int | None = None
    run_at: datetime | None = None
    config_override: dict | None = None
    enabled: bool = True
    max_retries: int = 0
    retry_delay_seconds: int = 60


class ScheduleUpdate(BaseModel):
    name: str | None = None
    trigger_type: str | None = None
    cron_expr: str | None = None
    interval_seconds: int | None = None
    run_at: datetime | None = None
    config_override: dict | None = None
    enabled: bool | None = None
    max_retries: int | None = None
    retry_delay_seconds: int | None = None


class ScheduleResponse(BaseModel):
    id: str
    pipeline_id: str
    pipeline_name: str | None = None  # 标识符，用于路由
    pipeline_display_name: str | None = None  # 中文显示名，用于展示
    name: str
    trigger_type: str
    cron_expr: str | None = None
    interval_seconds: int | None = None
    run_at: datetime | None = None
    config_override: dict | None = None
    enabled: bool
    next_run_at: datetime | None = None
    max_retries: int
    retry_delay_seconds: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
