import asyncio


class PlaywrightCliError(Exception):
    pass


class PlaywrightCliExecutor:
    """Execute browser automation via playwright-cli subprocess."""

    async def run_command(self, command: str, args: list[str] | None = None) -> str:
        cmd_args = ["playwright-cli", command] + (args or [])
        proc = await asyncio.create_subprocess_exec(
            *cmd_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise PlaywrightCliError(stderr.decode())
        return stdout.decode()

    async def open_page(self, url: str, session: str = "default") -> None:
        await self.run_command("goto", [url, f"--session={session}"])

    async def snapshot(self, session: str = "default") -> str:
        return await self.run_command("snapshot", [f"--session={session}"])

    async def click(self, ref: str, session: str = "default") -> None:
        await self.run_command("click", [ref, f"--session={session}"])

    async def fill(self, ref: str, value: str, session: str = "default") -> None:
        await self.run_command("fill", [ref, value, f"--session={session}"])
