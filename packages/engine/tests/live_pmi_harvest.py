"""手动直连运行 port_maritime_info.harvest（不经 backend runner）。

用法（repo 根目录）:
    uv run python packages/engine/tests/live_pmi_harvest.py [start_date] [end_date] [--force]

自建 AsyncSession + 内存 StepLogger，日志直接打印到终端。
pytest 不会收集本文件（文件名不以 test_ 开头）。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "packages" / "engine" / "src"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "backend" / "src"))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from engine.context import ExecutionContext  # noqa: E402
from engine.logger import StepLogger  # noqa: E402
from engine.registry import PipelineRegistry  # noqa: E402
from backend.config import get_settings  # noqa: E402


class PrintLogger(StepLogger):
    async def step(self, name, message, level="info", data=None):
        await super().step(name, message, level, data)
        print(f"[{level:5}] [{name:7}] {message}")


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    start = args[0] if len(args) > 0 else "2026-07-23"
    end = args[1] if len(args) > 1 else start
    force = "--force" in sys.argv

    PipelineRegistry._pipelines.clear()
    PipelineRegistry.discover()
    cls = PipelineRegistry.get("port_maritime_info.harvest")
    assert cls is not None, "pipeline 未注册"

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False, pool_size=5)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        ctx = ExecutionContext(
            logger=PrintLogger("live-manual"),
            db=session,
            minio=None,
            settings=settings,
            execution_id="live-manual",
        )
        config = {
            "sources": ["交通运输部"],
            "start_date": start,
            "end_date": end,
            "force": force,
        }
        result = await cls().execute(config, ctx)
        await session.commit()

    await engine.dispose()
    print(f"\nsuccess={result.success} error={result.error}")
    print(f"summary={result.summary}")
    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    asyncio.run(main())
