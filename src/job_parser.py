"""LinkedIn job scraper using Playwright and SQLite persistence."""

from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import (
    ParseResult,
    parse_qsl,
    quote_plus,
    urlencode,
    urlparse,
    urlunparse,
)

import yaml
from playwright.sync_api import Browser
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .login import load_credentials

LOGGER = logging.getLogger(__name__)
LOGIN_URL = "https://www.linkedin.com/login"


@dataclass
class JobPosting:
    """Container for scraped job posting details."""

    job_id: str
    title: str
    company: str
    description: str
    url: str
    recruiter_url: Optional[str]
    company_url: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None


@dataclass
class ScrapingConfig:
    """Configuration derived from config/scraping.yaml."""

    base_url: str
    start_param: str
    page_size: int
    extra_params: Dict[str, str]
    page_delay_seconds: float

    @classmethod
    def load(cls, path: Path) -> "ScrapingConfig":
        if not path.exists():
            raise FileNotFoundError(f"Scraping config not found at {path}")

        with path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}

        search = raw.get("search") or {}
        rate_limits = raw.get("rate_limits") or {}
        base_url = str(
            search.get("base_url") or "https://www.linkedin.com/jobs/search/"
        )
        start_param = str(search.get("start_param") or "start")
        page_size = int(search.get("page_size") or 25)
        extra_params = {
            str(key): str(value)
            for key, value in (search.get("extra_params") or {}).items()
        }

        page_delay_seconds = float(rate_limits.get("page_delay_seconds") or 3.0)

        return cls(
            base_url=base_url,
            start_param=start_param,
            page_size=page_size,
            extra_params=extra_params,
            page_delay_seconds=page_delay_seconds,
        )


class JobParserAgent:
    """Scrapes LinkedIn job postings and stores them in SQLite."""

    TITLE_SELECTORS: Iterable[str] = ("a.job-card-container__link strong",)
    COMPANY_SELECTORS: Iterable[str] = (
        "a.job-card-container__company-name",
        "span.job-card-container__primary-description",
        "a.base-card__subtitle",
    )
    COMPANY_LINK_SELECTORS: Tuple[str, ...] = (
        "a[href*='linkedin.com/company/']",
        "a[href*='/company/']",
        "a[data-tracking-control-name*='company']",
        ".jobs-unified-top-card__primary-description a[href*='linkedin.com/company/']",
    )
    JOB_CARD_LIST_SELECTORS: Iterable[str] = ("[data-occludable-job-id]",)

    def __init__(
        self,
        job_title: str,
        username: str,
        password: str,
        *,
        scraping_config: ScrapingConfig,
        max_jobs: int,
        salary_band: int,
        posted_time: str,
        database_path: Path = Path("data/jobs.db"),
        headless: bool = False,
        wait_timeout: float = 20.0,
    ) -> None:
        self.job_title = job_title
        self.username = username
        self.password = password
        self.config = scraping_config
        self.database_path = database_path
        self.headless = headless
        self.wait_timeout = wait_timeout
        self.max_jobs = max(1, max_jobs)
        self.salary_band = max(1, min(salary_band, 9))
        self.posted_time = posted_time.strip()
        self._base_search_parts: Optional[ParseResult] = None
        self._base_query: Dict[str, str] = {}
        self._initial_offset: int = 0

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def run(self) -> List[JobPosting]:
        """Execute the full scraping pipeline."""
        with sync_playwright() as playwright:
            browser = self._start_browser(playwright)
            context = browser.new_context()
            page = context.new_page()
            try:
                LOGGER.info("Logging into LinkedIn.")
                self._login(page)
                LOGGER.info("Preparing job search for: %s", self.job_title)
                self._initialize_job_search(page)
                LOGGER.info("Collecting job postings for: %s", self.job_title)
                postings = self._collect_jobs(page)
            finally:
                context.close()
                browser.close()

        LOGGER.info("Collected %d job postings this run.", len(postings))
        return postings

    def _start_browser(self, playwright) -> Browser:
        return playwright.chromium.launch(headless=self.headless, slow_mo=0)

    def _login(self, page: Page) -> None:
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        page.fill("input#username", self.username)
        page.fill("input#password", self.password)
        try:
            with page.expect_navigation(
                wait_until="domcontentloaded", timeout=self.wait_timeout * 1000
            ):
                page.click("button[type='submit']")
        except PlaywrightTimeoutError:
            LOGGER.debug(
                "Navigation did not complete during login submit; continuing with current page."
            )

        try:
            page.wait_for_url(
                re.compile(r"linkedin\.com\/(feed|jobs|search)"),
                timeout=self.wait_timeout * 1000,
            )
        except PlaywrightTimeoutError:
            LOGGER.debug("Login redirect did not reach feed/search within timeout.")

        page.wait_for_load_state("domcontentloaded")

        if "login" in page.url:
            LOGGER.warning(
                "Still on login page after attempting to authenticate. Check credentials or MFA status."
            )

    def _initialize_job_search(self, page: Page) -> None:
        search_url = self._build_search_url(self._initial_offset)
        LOGGER.info("Navigating to LinkedIn job search: %s", search_url)
        page.goto(search_url, wait_until="domcontentloaded", timeout=self.wait_timeout * 1000)
        page.wait_for_load_state("domcontentloaded")
        time.sleep(self.config.page_delay_seconds)
        LOGGER.info("Arrived at job search page: %s", page.url)
        self._update_base_search_from_url(page.url)

    def _collect_jobs(self, page: Page) -> List[JobPosting]:
        collected: List[JobPosting] = []
        seen_job_ids: set[str] = set()
        offset = self._initial_offset
        first_iteration = True

        while len(collected) < self.max_jobs:
            search_url = self._build_search_url(offset)
            if first_iteration:
                LOGGER.info(
                    "Processing existing search results page (offset=%d): %s",
                    offset,
                    page.url,
                )
            else:
                LOGGER.info("Loading search results page: %s", search_url)
                try:
                    page.goto(
                        search_url,
                        wait_until="domcontentloaded",
                        timeout=self.wait_timeout * 1000,
                    )
                except PlaywrightTimeoutError:
                    LOGGER.debug(
                        "Timeout loading search results; retrying with relaxed wait."
                    )
                    page.goto(search_url, wait_until="domcontentloaded")
                page.wait_for_load_state("domcontentloaded")

            loaded_count = self._ensure_job_cards_loaded(page, len(collected))
            LOGGER.debug("Job cards discovered after load: %d", loaded_count)
            time.sleep(self.config.page_delay_seconds)

            scraped_this_page = self._scrape_jobs_on_page(page, collected, seen_job_ids)
            LOGGER.info(
                "Captured %d jobs from current page (offset=%d). Total collected: %d.",
                scraped_this_page,
                offset,
                len(collected),
            )

            if scraped_this_page == 0:
                LOGGER.warning(
                    "No job cards processed on this page; stopping pagination."
                )
                break

            if len(collected) >= self.max_jobs:
                break

            first_iteration = False
            offset += self.config.page_size

        return collected

    def _scrape_jobs_on_page(
        self,
        page: Page,
        collected: List[JobPosting],
        seen_job_ids: set[str],
    ) -> int:
        collected_before = len(collected)
        expected_on_page = min(self.config.page_size, self.max_jobs - collected_before)

        card_locator = self._locate_job_cards(page)
        total_cards = card_locator.count()
        LOGGER.debug("Located %d job cards on current page.", total_cards)

        if total_cards == 0:
            return 0

        total_cards = min(total_cards, self.config.page_size)
        scraped = 0

        for index in range(total_cards):
            if len(collected) >= self.max_jobs:
                break

            card = card_locator.nth(index)
            job_id = self._resolve_job_id(card)
            if not job_id:
                LOGGER.debug("Skipping job card without job id at index %d.", index)
                continue
            if job_id in seen_job_ids:
                LOGGER.debug("Skipping duplicate job id %s at index %d.", job_id, index)
                continue

            posting = self._scrape_job_card(page, card, job_id)
            if posting is None:
                continue

            collected.append(posting)
            seen_job_ids.add(job_id)
            scraped += 1
            inserted = self._persist_job(posting)

            log_company = posting.company_url or posting.company
            recruiter_log = posting.recruiter_url or "(no recruiter)"
            salary_log = "-"
            if posting.salary_min is not None:
                if posting.salary_max is not None and posting.salary_max != posting.salary_min:
                    salary_log = f"{int(posting.salary_min)}-{int(posting.salary_max)}"
                else:
                    salary_log = f"{int(posting.salary_min)}"

            if inserted:
                LOGGER.info(
                    "Captured job %s: %s @ %s recruiter: %s salary: %s",
                    job_id,
                    posting.title,
                    log_company,
                    recruiter_log,
                    salary_log,
                )
            else:
                LOGGER.info(
                    "Captured job %s already stored @ %s recruiter: %s salary: %s",
                    job_id,
                    log_company,
                    recruiter_log,
                    salary_log,
                )

            self._wait_between_jobs(page)

        if scraped < expected_on_page and len(collected) < self.max_jobs:
            message = f"Only captured {scraped} jobs from current page (expected {expected_on_page})."
            LOGGER.error(message)
            raise RuntimeError(message)

        return scraped

    def _locate_job_cards(self, page: Page) -> Locator:
        for selector in self.JOB_CARD_LIST_SELECTORS:
            locator = page.locator(selector)
            if locator.count() > 0:
                return locator
        return page.locator("[data-job-id], [data-occludable-job-id]")

    def _resolve_job_id(self, card: Locator) -> Optional[str]:
        job_id = card.get_attribute("data-job-id") or card.get_attribute(
            "data-occludable-job-id"
        )
        if job_id:
            return job_id
        descendant = card.locator("[data-job-id]").first
        if descendant.count() > 0:
            return descendant.get_attribute("data-job-id")
        return None

    def _scrape_job_card(
        self, page: Page, card: Locator, job_id: str
    ) -> Optional[JobPosting]:
        card.scroll_into_view_if_needed()
        try:
            card.click(timeout=self.wait_timeout * 1000)
        except PlaywrightTimeoutError:
            LOGGER.debug("Timeout clicking job card %s.", job_id)
            return None

        try:
            page.wait_for_selector("#job-details", timeout=self.wait_timeout * 1000)
            page.wait_for_timeout(500)
        except PlaywrightTimeoutError:
            LOGGER.debug("Timed out waiting for job details for %s.", job_id)
            return None

        detail_panel = page.locator("#job-details").first

        raw_title = self._extract_text(card, self.TITLE_SELECTORS) or "Unknown Title"
        title = self._clean_title(raw_title)
        company_name, company_url = self._resolve_company_info(page, card, detail_panel)
        if company_name is None:
            company_name = (
                self._extract_text(card, self.COMPANY_SELECTORS) or "Unknown Company"
            )

        try:
            description = detail_panel.inner_text().strip()
        except (PlaywrightTimeoutError, PlaywrightError):
            LOGGER.debug("Unable to read description for %s.", job_id)
            description = ""

        recruiter_url = self._extract_recruiter_url(page)
        salary_min, salary_max = self._extract_salary_range(page)

        return JobPosting(
            job_id=job_id,
            title=title,
            company=company_name,
            company_url=company_url,
            recruiter_url=recruiter_url,
            salary_min=salary_min,
            salary_max=salary_max,
            description=description,
            url=f"https://www.linkedin.com/jobs/view/{job_id}/",
        )

    def _extract_salary_range(self, page: Page) -> Tuple[Optional[float], Optional[float]]:
        selector = (
            ".job-details-fit-level-preferences > "
            "button:nth-child(1) > span:nth-child(1) > strong:nth-child(1)"
        )
        locator = page.locator(selector).first
        if locator.count() == 0:
            return None, None
        try:
            text = locator.inner_text().strip()
        except (PlaywrightTimeoutError, PlaywrightError):
            return None, None

        if not text:
            return None, None

        clean_text = text.split("+")[0]
        matches = re.findall(r"\$?\s*([0-9]+(?:\.[0-9]+)?)([kKmM]?)", clean_text)
        if not matches:
            return None, None

        def to_number(value: str, suffix: str) -> float:
            number = float(value)
            suffix = suffix.lower()
            if suffix == "m":
                number *= 1_000_000
            elif suffix == "k":
                number *= 1_000
            return number

        min_value = to_number(*matches[0])
        max_value = (
            to_number(*matches[1]) if len(matches) > 1 else min_value
        )
        return min_value, max_value

    def _extract_recruiter_url(self, page: Page) -> Optional[str]:
        selector = (
            ".job-details-people-who-can-help__section--two-pane > "
            "div:nth-child(2) > div:nth-child(1) > a:nth-child(1)"
        )
        locator = page.locator(selector).first
        if locator.count() == 0:
            return None
        try:
            href = locator.get_attribute("href") or None
        except (PlaywrightTimeoutError, PlaywrightError):
            return None
        if href:
            return href.split("?")[0]
        return None

    def _resolve_company_info(
        self,
        page: Page,
        card: Locator,
        detail_panel: Locator,
    ) -> Tuple[Optional[str], Optional[str]]:
        scopes: List[Locator] = [
            card,
            detail_panel,
            page.locator(".jobs-unified-top-card__primary-description"),
            page.locator(".jobs-unified-top-card__content-container"),
            page.locator(".jobs-unified-top-card__subtitle"),
            page.locator(".jobs-details-top-card__company-url"),
        ]

        for scope in scopes:
            name, url = self._extract_company_from_scope(scope)
            if name or url:
                return name, url

        fallback = page.locator(self.COMPANY_LINK_SELECTORS[0]).first
        if fallback.count() > 0:
            return self._extract_company_from_link(fallback)
        return None, None

    def _extract_company_from_scope(
        self, scope: Locator
    ) -> Tuple[Optional[str], Optional[str]]:
        if scope.count() == 0:
            return None, None
        for selector in self.COMPANY_LINK_SELECTORS:
            link = scope.locator(selector).first
            if link.count() == 0:
                continue
            name, url = self._extract_company_from_link(link)
            if name or url:
                return name, url
        return None, None

    def _extract_company_from_link(
        self, link: Locator
    ) -> Tuple[Optional[str], Optional[str]]:
        href = None
        try:
            href = link.get_attribute("href") or None
        except (PlaywrightTimeoutError, PlaywrightError):
            href = None

        normalized_url, slug = self._normalize_company_url(href)

        link_text = None
        try:
            link_text = link.inner_text().strip() or None
        except (PlaywrightTimeoutError, PlaywrightError):
            link_text = None

        name = slug or link_text
        return name, normalized_url

    def _normalize_company_url(
        self, url: Optional[str]
    ) -> Tuple[Optional[str], Optional[str]]:
        if not url:
            return None, None

        cleaned = url.strip()
        if cleaned.startswith("//"):
            cleaned = f"https:{cleaned}"
        elif cleaned.startswith("/"):
            cleaned = f"https://www.linkedin.com{cleaned}"

        parsed = urlparse(cleaned)
        scheme = parsed.scheme or "https"
        netloc = parsed.netloc or "www.linkedin.com"
        path_segments = [segment for segment in parsed.path.split("/") if segment]

        slug: Optional[str] = None
        if "company" in path_segments:
            idx = path_segments.index("company")
            if idx + 1 < len(path_segments):
                slug = path_segments[idx + 1]
                normalized_path = f"/company/{slug}/"
                parsed = parsed._replace(
                    path=normalized_path,
                    params="",
                    query="",
                    fragment="",
                )
        else:
            parsed = parsed._replace(params="", query="", fragment="")

        normalized = urlunparse(
            ParseResult(
                scheme=scheme,
                netloc=netloc,
                path=parsed.path,
                params="",
                query="",
                fragment="",
            )
        )

        return normalized, slug

    @staticmethod
    def _clean_title(raw_title: str) -> str:
        lines = [line.strip() for line in raw_title.splitlines() if line.strip()]
        if not lines:
            return raw_title.strip()
        seen: set[str] = set()
        deduped: List[str] = []
        for line in lines:
            if line not in seen:
                deduped.append(line)
                seen.add(line)
        if len(deduped) == 1:
            return deduped[0]
        return " ".join(deduped)

    def _ensure_job_cards_loaded(self, page: Page, collected_so_far: int) -> int:
        del collected_so_far
        return self._locate_job_cards(page).count()

    def _wait_between_jobs(self, page: Page) -> None:
        per_job_delay = min(self.config.page_delay_seconds / 2, 1.5)
        delay_ms = int(max(per_job_delay, 0) * 1000)
        if delay_ms > 0:
            page.wait_for_timeout(delay_ms)

    def _build_search_url(self, offset: int) -> str:
        if self._base_search_parts:
            parsed_base = self._base_search_parts
            base_query = dict(self._base_query)
        else:
            parsed_base = urlparse(self.config.base_url)
            base_query = {
                key: value
                for key, value in parse_qsl(parsed_base.query)
                if key != self.config.start_param
            }
            base_query.update(self.config.extra_params)

        base_query["keywords"] = self.job_title
        base_query["origin"] = "JOB_SEARCH_PAGE_JOB_FILTER"
        base_query["f_SB2"] = str(self.salary_band)
        if self.posted_time:
            base_query["f_TPR"] = self.posted_time
        else:
            base_query.pop("f_TPR", None)

        params: Dict[str, str] = {
            **base_query,
            self.config.start_param: str(offset),
        }

        query = urlencode(params, doseq=True)
        new_parts = ParseResult(
            scheme=parsed_base.scheme,
            netloc=parsed_base.netloc,
            path=parsed_base.path,
            params=parsed_base.params,
            query=query,
            fragment=parsed_base.fragment,
        )
        return urlunparse(new_parts)

    def _extract_text(
        self, locator: Locator, selectors: Iterable[str]
    ) -> Optional[str]:
        for selector in selectors:
            try:
                element = locator.locator(selector).first
                if element.count() == 0:
                    continue
                text = element.inner_text().strip()
                if text:
                    return text
            except PlaywrightTimeoutError:
                continue
        return None

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self.database_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS job_postings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    company_url TEXT,
                    recruiter_url TEXT,
                    salary_min REAL,
                    salary_max REAL,
                    description TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_job_postings_job_id
                    ON job_postings(job_id)
                    WHERE job_id IS NOT NULL;
                """
            )
            conn.commit()

    def _persist_job(self, job: JobPosting) -> bool:
        params = self._job_to_params(job)
        with sqlite3.connect(self.database_path) as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO job_postings (
                    job_id,
                    title,
                    company,
                    company_url,
                    recruiter_url,
                    salary_min,
                    salary_max,
                    description,
                    url
                )
                VALUES (
                    :job_id,
                    :title,
                    :company,
                    :company_url,
                    :recruiter_url,
                    :salary_min,
                    :salary_max,
                    :description,
                    :url
                )
                """,
                params,
            )
            conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _job_to_params(job: JobPosting) -> Dict[str, Optional[str]]:
        return {
            "job_id": job.job_id,
            "title": job.title,
            "company": job.company,
            "company_url": job.company_url,
            "recruiter_url": job.recruiter_url,
            "salary_min": job.salary_min,
            "salary_max": job.salary_max,
            "description": job.description,
            "url": job.url,
        }

    @staticmethod
    def _derive_job_id_from_url(url: str) -> Optional[str]:
        if not url:
            return None
        match = re.search(r"/view/(\d+)", url)
        if match:
            return match.group(1)
        digits = re.findall(r"\d+", url)
        return digits[0] if digits else None

    def _update_base_search_from_url(self, url: str) -> None:
        parsed = urlparse(url)
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        self._base_search_parts = ParseResult(
            scheme=parsed.scheme,
            netloc=parsed.netloc,
            path=parsed.path,
            params=parsed.params,
            query="",
            fragment=parsed.fragment,
        )
        self._base_query = {
            key: value
            for key, value in query_pairs
            if key not in {self.config.start_param, "currentJobId"}
        }
        offset_value = next(
            (value for key, value in query_pairs if key == self.config.start_param),
            "0",
        )
        try:
            self._initial_offset = int(offset_value or 0)
        except ValueError:
            LOGGER.debug(
                "Unable to parse start offset '%s'; defaulting to 0.", offset_value
            )
            self._initial_offset = 0
        if "keywords" not in self._base_query or not self._base_query["keywords"]:
            self._base_query["keywords"] = self.job_title
        if self.config.extra_params:
            for key, value in self.config.extra_params.items():
                self._base_query.setdefault(key, value)


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape LinkedIn job listings with Playwright."
    )
    parser.add_argument(
        "--job-title",
        dest="job_title",
        required=True,
        help="Job title or keywords to search for.",
    )
    parser.add_argument("--username", help="LinkedIn username (email).")
    parser.add_argument("--password", help="LinkedIn password.")
    parser.add_argument(
        "--headless", action="store_true", help="Run browser in headless mode."
    )
    parser.add_argument(
        "--max-jobs",
        dest="max_jobs",
        type=int,
        required=True,
        help="Total number of jobs to scrape before stopping.",
    )
    parser.add_argument(
        "--login-file",
        default="secure/login.txt",
        help="Path to login file with username/password (default: secure/login.txt).",
    )
    parser.add_argument(
        "--chromedriver",
        default="/opt/homebrew/bin/chromedriver",
        help="Deprecated; ignored. Present for backwards compatibility.",
    )
    parser.add_argument(
        "--scrape-config",
        default="config/scraping.yaml",
        help="Path to YAML file containing scraping properties (default: config/scraping.yaml).",
    )
    parser.add_argument(
        "--salary-band",
        dest="salary_band",
        type=int,
        default=9,
        help="LinkedIn salary band filter value for f_SB2 (1-9, default 9).",
    )
    parser.add_argument(
        "--posted-time",
        dest="posted_time",
        default="",
        help="LinkedIn posted time filter value for f_TPR (e.g., r86400). Empty string means any time.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    args = _parse_args(argv)

    if args.chromedriver:
        LOGGER.debug(
            "Chromedriver argument ignored: Playwright no longer relies on Selenium."
        )

    credentials = load_credentials(
        args.username,
        args.password,
        login_file=Path(args.login_file),
    )

    scraping_config = ScrapingConfig.load(Path(args.scrape_config))

    agent = JobParserAgent(
        job_title=args.job_title,
        username=credentials.username,
        password=credentials.password,
        scraping_config=scraping_config,
        max_jobs=args.max_jobs,
        headless=args.headless,
        salary_band=args.salary_band,
        posted_time=args.posted_time,
    )

    jobs = agent.run()
    LOGGER.info("Scraped %d jobs.", len(jobs))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        LOGGER.info("Job scraping interrupted by user.")
        sys.exit(1)
