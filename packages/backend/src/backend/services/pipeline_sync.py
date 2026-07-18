from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.pipeline import Pipeline
from engine.registry import PipelineRegistry


async def sync_pipelines_to_db(session: AsyncSession) -> None:
    """Sync registered pipelines from engine registry to database."""
    PipelineRegistry.discover()
    registered = PipelineRegistry.all()

    for name, cls in registered.items():
        meta = cls.metadata
        stmt = select(Pipeline).where(Pipeline.name == name)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is None:
            pipeline = Pipeline(
                name=meta.name,
                display_name=meta.display_name,
                description=meta.description,
                trigger_modes=meta.trigger_modes,
                config_schema=meta.config_schema,
                status="active",
            )
            session.add(pipeline)
        else:
            existing.display_name = meta.display_name
            existing.description = meta.description
            existing.trigger_modes = meta.trigger_modes
            existing.config_schema = meta.config_schema

    await session.commit()
