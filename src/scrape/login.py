"""Credential and authentication helpers for LinkedIn."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from playwright.sync_api import Browser, BrowserContext, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


@dataclass
class Credentials:
    """Holds LinkedIn login credentials."""

    username: str
    password: str


def load_credentials(login_file: Path = Path("secure/login.txt")) -> Credentials:
    """Load credentials from the given login file."""

    if not login_file.exists():
        raise FileNotFoundError(f"Login file not found at {login_file}")

    username, password = _read_login_file(login_file)
    if not username or not password:
        raise ValueError(
            f"Login file {login_file} must contain username and password on separate lines."
        )

    return Credentials(username=username, password=password)


def _read_login_file(login_file: Path) -> Tuple[Optional[str], Optional[str]]:
    with login_file.open("r", encoding="utf-8") as handle:
        lines = [line.strip() for line in handle.readlines()]

    username = lines[0] if len(lines) >= 1 and lines[0] else None
    password = lines[1] if len(lines) >= 2 and lines[1] else None
    return username, password


LOGIN_URL = "https://www.linkedin.com/login"
FEED_URL = "https://www.linkedin.com/feed/"
DEFAULT_LOGIN_FILE = Path("secure/login.txt")
DEFAULT_SESSION_FILE = Path("secure/session.json")
LOGGER = logging.getLogger(__name__)


def login_to_linkedin(
    browser: Browser,
    *,
    wait_timeout: float,
    login_file: Path = DEFAULT_LOGIN_FILE,
    storage_path: Path = DEFAULT_SESSION_FILE,
) -> tuple[BrowserContext, Page]:
    """Return an authenticated Playwright context/page, reusing cached storage when possible."""

    storage_kwargs = {}
    if storage_path.exists():
        storage_kwargs["storage_state"] = storage_path.as_posix()

    context = browser.new_context(**storage_kwargs)
    page = context.new_page()

    if _session_active(page, wait_timeout):
        LOGGER.info(
            "Reusing cached LinkedIn session from %s.",
            storage_kwargs.get("storage_state", "memory"),
        )
        return context, page

    LOGGER.info("LinkedIn session invalid or missing; performing login.")
    _perform_login(page, wait_timeout=wait_timeout, login_file=login_file)
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=storage_path.as_posix())
    LOGGER.info("Stored LinkedIn session to %s.", storage_path)
    return context, page


def _session_active(page: Page, wait_timeout: float) -> bool:
    try:
        page.goto(FEED_URL, wait_until="domcontentloaded", timeout=wait_timeout * 1000)
        page.wait_for_load_state("domcontentloaded")
    except PlaywrightTimeoutError:
        LOGGER.debug("Feed check timed out; assuming login required.")

    if "login" in page.url or page.locator("input#username").count() > 0:
        return False
    return True


def _perform_login(
    page: Page,
    *,
    wait_timeout: float,
    login_file: Path,
) -> None:
    creds = load_credentials(login_file)

    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    page.fill("input#username", creds.username)
    page.fill("input#password", creds.password)
    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=wait_timeout * 1000):
            page.click("button[type='submit']")
    except PlaywrightTimeoutError:
        LOGGER.debug(
            "Navigation did not complete during login submit; continuing with current page."
        )

    try:
        page.wait_for_url(
            re.compile(r"linkedin\\.com/(feed|jobs|search)"), timeout=wait_timeout * 1000
        )
    except PlaywrightTimeoutError:
        LOGGER.debug("Login redirect did not reach feed/search within timeout.")

    page.wait_for_load_state("domcontentloaded")

    if "login" in page.url:
        LOGGER.warning(
            "Still on login page after attempting to authenticate. Check credentials or MFA status."
        )
