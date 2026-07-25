import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.pipeline import Pipeline
from engine.registry import PipelineRegistry

logger = logging.getLogger(__name__)


async def sync_pipelines_to_db(session: AsyncSession) -> None:
    """Sync registered pipelines from engine registry to database (spec 1 §4.5).

    生命周期语义：
    - 新增：registry 有、DB 无 → 插入
    - 更新：定义字段内容对比，任一不同 → 覆盖定义字段 + version（二十七次修订：
      内容对比取代 version 触发，忘 bump version 不再导致 DB 漂移）；
      全部一致 → 跳过
    - 恢复：DB archived 但代码回归 → 回 active（系统标记复位）
    - 归档：DB 有、registry 无（代码已删除）→ status=archived，绝不删行
    """
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
                version=meta.version,
                status="active",
            )
            session.add(pipeline)
            continue

        if existing.status == "archived":
            # 代码回归：系统归档标记复位（用户手动 disabled 意图无法区分，见 spec 边界说明）
            existing.status = "active"
            logger.info("Pipeline %s 代码回归，archived → active", name)

        changed = (
            existing.display_name != meta.display_name
            or existing.description != meta.description
            or list(existing.trigger_modes or []) != list(meta.trigger_modes)
            or (existing.config_schema or None) != (meta.config_schema or None)
            or existing.version != meta.version
        )
        if changed:
            existing.display_name = meta.display_name
            existing.description = meta.description
            existing.trigger_modes = meta.trigger_modes
            existing.config_schema = meta.config_schema
            logger.info(
                "Pipeline %s 定义字段变更（内容对比），同步定义字段", name,
            )
            existing.version = meta.version

    # 软归档：registry 里找不到的 DB pipeline（代码已删除）
    result = await session.execute(
        select(Pipeline).where(Pipeline.status != "archived")
    )
    for pipeline in result.scalars().all():
        if pipeline.name not in registered:
            pipeline.status = "archived"
            logger.info("Pipeline %s 代码已删除，软归档为 archived", pipeline.name)

    await session.commit()
