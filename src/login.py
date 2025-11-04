"""Credential loader for LinkedIn authentication."""

from __future__ import annotations

from dataclasses import dataclass
from getpass import getpass
from pathlib import Path
from typing import Optional, Tuple


@dataclass
class Credentials:
    """Holds LinkedIn login credentials."""

    username: str
    password: str


def load_credentials(
    username_arg: Optional[str],
    password_arg: Optional[str],
    *,
    login_file: Path = Path("secure/login.txt"),
    prompt_if_missing: bool = True,
) -> Credentials:
    """Resolve credentials from CLI args, login file, or interactive prompts.

    Args:
        username_arg: Username provided via CLI argument.
        password_arg: Password provided via CLI argument.
        login_file: Path to file containing username/password on separate lines.
        prompt_if_missing: Whether to fall back to interactive prompts when
            credentials are not fully resolved.

    Returns:
        Credentials object with username and password.

    Raises:
        ValueError: If credentials cannot be resolved and prompting is disabled.
    """

    username, password = username_arg, password_arg

    if (username is None or password is None) and login_file.exists():
        file_username, file_password = _read_login_file(login_file)
        username = username or file_username
        password = password or file_password

    if prompt_if_missing:
        if not username:
            username = input("LinkedIn username: ").strip()
        if not password:
            password = getpass("LinkedIn password: ")

    if not username or not password:
        raise ValueError("LinkedIn credentials are required. Provide CLI args or populate secure/login.txt.")

    return Credentials(username=username, password=password)


def _read_login_file(login_file: Path) -> Tuple[Optional[str], Optional[str]]:
    with login_file.open("r", encoding="utf-8") as handle:
        lines = [line.strip() for line in handle.readlines()]

    username = lines[0] if len(lines) >= 1 and lines[0] else None
    password = lines[1] if len(lines) >= 2 and lines[1] else None
    return username, password
