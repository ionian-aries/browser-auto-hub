import pytest

from engine.executors.playwright_cli import PlaywrightCliExecutor


def test_playwright_cli_executor_exists():
    executor = PlaywrightCliExecutor()
    assert hasattr(executor, "run_command")
    assert hasattr(executor, "open_page")
    assert hasattr(executor, "snapshot")
    assert hasattr(executor, "click")
