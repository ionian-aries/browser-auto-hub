from datetime import datetime

from pydantic import BaseModel


class PipelineResponse(BaseModel):
    id: int
    name: str
    display_name: str
    description: str
    trigger_modes: list[str]
    config_schema: dict | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
