class BrowserUseExecutor:
    """Execute browser automation via browser-use library.

    Requires: pip install browser-use
    Wraps browser-use's BrowserSession + DomService for deterministic operations.
    """

    async def navigate(self, url: str) -> None:
        raise NotImplementedError("Install browser-use and configure to use")

    async def extract_dom(self) -> str:
        raise NotImplementedError("Install browser-use and configure to use")

    async def click_element(self, selector: str) -> None:
        raise NotImplementedError("Install browser-use and configure to use")
