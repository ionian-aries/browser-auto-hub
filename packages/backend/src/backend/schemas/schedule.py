from datetime import datetime

from pydantic import BaseModel


class ScheduleCreate(BaseModel):
    pipeline_name: str
    name: str
    trigger_type: str  # "cron" | "interval" | "once"
    cron_expr: str | None = None
    interval_seconds: int | None = None
    config_override: dict | None = None
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    name: str | None = None
    trigger_type: str | None = None
    cron_expr: str | None = None
    interval_seconds: int | None = None
    config_override: dict | None = None
    enabled: bool | None = None


class ScheduleResponse(BaseModel):
    id: int
    pipeline_id: int
    pipeline_name: str | None = None
    name: str
    trigger_type: str
    cron_expr: str | None
    interval_seconds: int | None
    config_override: dict | None
    enabled: bool
    next_run_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
