from datetime import datetime

from pydantic import BaseModel


class ExecutionCreate(BaseModel):
    pipeline: str  # pipeline name
    config: dict | None = None
    trigger_type: str = "api"  # "api" | "manual"


class ExecutionResponse(BaseModel):
    id: str
    pipeline_id: str
    pipeline_name: str | None = None  # 标识符，用于路由
    pipeline_display_name: str | None = None  # 中文显示名，用于展示
    schedule_id: str | None = None
    trigger_type: str
    status: str
    config: dict | None = None
    retry_count: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    result_summary: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
