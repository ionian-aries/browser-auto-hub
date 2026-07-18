from engine.executors.playwright_cli import PlaywrightCliExecutor


async def goto(executor: PlaywrightCliExecutor, url: str, session: str = "default") -> None:
    await executor.open_page(url, session=session)
