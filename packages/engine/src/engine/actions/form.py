from engine.executors.playwright_cli import PlaywrightCliExecutor


async def fill_field(executor: PlaywrightCliExecutor, ref: str, value: str, session: str = "default") -> None:
    await executor.fill(ref, value, session=session)
