from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.config import get_settings

_engine = None
_session_factory = None


def get_engine():
    """进程级唯一 async engine（懒加载）。"""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.database_url, echo=False, pool_size=5)
    return _engine


def get_session_factory():
    """进程级唯一 session factory（与 get_engine 绑定，swap_engine 后随之更新）。"""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def swap_engine(new_url: str) -> None:
    """Validate new DB URL, swap engine + session factory, update scheduler, create_all."""
    global _engine, _session_factory
    from sqlalchemy import text
    from backend.models.base import Base

    new_engine = create_async_engine(new_url, echo=False, pool_size=5)
    try:
        async with new_engine.connect() as conn:  # validate before committing to swap
            await conn.execute(text("SELECT 1"))
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception:
        await new_engine.dispose()
        raise

    old_engine = _engine
    _engine = new_engine
    _session_factory = async_sessionmaker(new_engine, expire_on_commit=False)

    from backend.scheduler.manager import scheduler_manager
    if scheduler_manager is not None:
        scheduler_manager._session_factory = _session_factory

    if old_engine is not None:
        await old_engine.dispose()
