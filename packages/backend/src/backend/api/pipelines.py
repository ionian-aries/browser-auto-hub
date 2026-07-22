from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models.pipeline import Pipeline
from backend.schemas.pipeline import PipelineResponse

router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])


class PipelineUpdate(BaseModel):
    max_concurrent: int | None = None
    timeout_seconds: int | None = None
    status: str | None = None

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: str | None) -> str | None:
        if v is not None and v not in ("active", "disabled"):
            raise ValueError("status 必须为 active 或 disabled")
        return v


@router.get("", response_model=list[PipelineResponse])
async def list_pipelines(session: AsyncSession = Depends(get_session)):
    # 返回全部状态：停用项必须可见可管理（spec 4 §4.6）
    result = await session.execute(select(Pipeline).order_by(Pipeline.name))
    return result.scalars().all()


@router.get("/{name}", response_model=PipelineResponse)
async def get_pipeline(name: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Pipeline).where(Pipeline.name == name))
    pipeline = result.scalar_one_or_none()
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline '{name}' not found")
    return pipeline


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
