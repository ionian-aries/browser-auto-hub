from engine.executors.playwright_cli import PlaywrightCliExecutor


async def get_snapshot(executor: PlaywrightCliExecutor, session: str = "default") -> str:
    return await executor.snapshot(session=session)
