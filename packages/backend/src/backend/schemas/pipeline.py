from datetime import datetime

from pydantic import BaseModel


class PipelineResponse(BaseModel):
    id: str
    name: str
    display_name: str
    description: str
    trigger_modes: list[str]
    config_schema: dict | None = None
    max_concurrent: int
    timeout_seconds: int
    status: str
    version: str = "1.0.0"
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
