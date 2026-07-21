"""OA system login — supports login.jsp and IAM OAuth SSO."""

import re
import time

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PwTimeout


class LoginError(Exception):
    """Credentials invalid or login rejected (not retryable)."""


class LoginTimeout(Exception):
    """Page or element timed out (retryable)."""


async def oa_login(page: Page, config: dict) -> None:
    """
    Login to OA system.

    Required config keys: login_url, username, password
    Optional config keys: element_visible_timeout (ms), page_load_timeout (ms)

    Raises:
        LoginError: credentials invalid
        LoginTimeout: page/element timeout
    """
    username = config.get("username", "").strip()
    password = config.get("password", "").strip()
    login_url = config.get("login_url", "")

    if not username:
        raise LoginError("username is required")
    if not password:
        raise LoginError("password is required")
    if not login_url:
        raise LoginError("login_url is required")

    element_timeout = config.get("element_visible_timeout", 5000)
    page_timeout = config.get("page_load_timeout", 15000)

    # Navigate to login page
    try:
        await page.goto(login_url, wait_until="domcontentloaded", timeout=page_timeout)
    except PwTimeout:
        raise LoginTimeout(f"Login page load timeout: {login_url}")

    # Find and fill username field
    username_input = page.get_by_role("textbox", name="用户名")
    try:
        await username_input.wait_for(state="visible", timeout=element_timeout)
    except PwTimeout:
        raise LoginTimeout("Username input not visible within timeout")

    await username_input.fill(username)

    # Fill password
    password_input = page.get_by_role("textbox", name="密码")
    await password_input.fill(password)

    # Click login button (could be <a> or <button>)
    login_btn = page.get_by_role("link", name="登录").or_(
        page.get_by_role("button", name="登录")
    )
    await login_btn.click()

    # Poll URL for success/failure
    deadline = time.time() + page_timeout / 1000
    while time.time() < deadline:
        url = page.url
        if "/sys/portal/page.jsp" in url:
            return  # Login success

        if "login.jsp" in url and "login_error" in url:
            # Extract error message from page
            body_text = await page.inner_text("body")
            match = re.search(r"系统提示[:：]\s*(.+?)(?:\n|$)", body_text)
            error_msg = match.group(1).strip() if match else "Login failed"
            raise LoginError(error_msg)

        await page.wait_for_timeout(300)

    raise LoginTimeout("Login did not complete within timeout")
