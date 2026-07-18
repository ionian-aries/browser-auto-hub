from engine.executors.playwright_cli import PlaywrightCliExecutor


async def take_screenshot(executor: PlaywrightCliExecutor, session: str = "default") -> bytes:
    """Take screenshot via playwright-cli. Returns PNG bytes."""
    output = await executor.run_command("screenshot", [f"--session={session}"])
    return output.encode()  # Placeholder - real impl decodes base64
