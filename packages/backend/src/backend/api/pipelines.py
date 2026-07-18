from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models.pipeline import Pipeline
from backend.schemas.pipeline import PipelineResponse

router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])


@router.get("", response_model=list[PipelineResponse])
async def list_pipelines(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Pipeline).where(Pipeline.status == "active").order_by(Pipeline.name)
    )
    return result.scalars().all()


@router.get("/{name}", response_model=PipelineResponse)
async def get_pipeline(name: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Pipeline).where(Pipeline.name == name))
    pipeline = result.scalar_one_or_none()
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline '{name}' not found")
    return pipeline
