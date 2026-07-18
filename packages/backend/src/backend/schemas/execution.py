from datetime import datetime

from pydantic import BaseModel


class ExecutionCreate(BaseModel):
    pipeline: str  # pipeline name
    config: dict | None = None
    trigger_type: str = "api"  # "api" | "manual"


class ExecutionResponse(BaseModel):
    id: int
    pipeline_id: int
    pipeline_name: str | None = None
    schedule_id: int | None
    trigger_type: str
    status: str
    config: dict | None
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    result_summary: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}
