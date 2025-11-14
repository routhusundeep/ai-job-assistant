"""LinkedIn scraping utilities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .login import Credentials, load_credentials, login_to_linkedin

__all__ = [
    "JobParserAgent",
    "ScrapingConfig",
    "Credentials",
    "load_credentials",
    "login_to_linkedin",
]


if TYPE_CHECKING:  # pragma: no cover - used for static analysis only
    from .job_parser import JobParserAgent, ScrapingConfig


def __getattr__(name: str):
    if name in {"JobParserAgent", "ScrapingConfig"}:
        from .job_parser import JobParserAgent as JP, ScrapingConfig as SC

        mapping = {
            "JobParserAgent": JP,
            "ScrapingConfig": SC,
        }
        return mapping[name]
    raise AttributeError(f"module 'src.scrape' has no attribute {name!r}")
