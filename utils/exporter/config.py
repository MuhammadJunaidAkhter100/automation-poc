"""Application settings and the single source of truth for page selectors."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


def _resolve_browser_executable_path() -> Path | None:
    env_names = [
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH",
        "BROWSER_EXECUTABLE_PATH",
        "CHROME_PATH",
        "CHROME_EXECUTABLE_PATH",
        "MSEDGE_PATH",
        "MSEDGE_EXECUTABLE_PATH",
    ]
    for name in env_names:
        value = os.getenv(name, "").strip()
        if value:
            candidate = Path(value)
            if candidate.exists():
                return candidate
    if os.name == "nt":
        home = Path.home()
        candidates = [
            Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
            Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
            Path("C:/Program Files/Chromium/Application/chrome.exe"),
            Path("C:/Program Files (x86)/Chromium/Application/chrome.exe"),
            Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
            Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
            home / "AppData" / "Local" / "Google" / "Chrome" / "Application" / "chrome.exe",
            home / "AppData" / "Local" / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            home / "AppData" / "Local" / "Chromium" / "Application" / "chrome.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
    return None


# Keep Adapt DOM knowledge here. Verify/update these with Playwright Inspector if Adapt changes.
@dataclass(frozen=True, slots=True)
class AdaptSelectors:
    # Verified against Adapt Advanced Contact Search's current div-based result list.
    results_table: str = '.contact-list'
    header_cells: str = '.contact-header > div:not(.contact-check-box-wrap)'
    body_rows: str = '.contact-list-wrap .contact-item'
    row_cells: str = ':scope > div:not(.contact-check-box-wrap)'
    loading_indicator: str = '[role="progressbar"], .loading, .spinner'
    # Adapt currently renders span.next-page / span.previous-page, not arrows.
    # Keep the older arrow classes as a fallback for future UI variants.
    next_page: str = '.pagination .next-page:not(.disable), .pagination .right-arrow:not(.disable)'
    disabled_next_page: str = '.pagination .next-page.disable, .pagination .right-arrow.disable'
    filters_button: str = 'button:has-text("Filters"), [role="button"]:has-text("Filters")'
    clear_all_filters: str = 'text=Clear All'
    filters_root: str = '.filter-wrapper'
    job_title_filter: str = '.filter-item.jobTitle'
    location_filter: str = '.filter-item.contactLocation'
    industry_filter: str = '.filter-item.industry'
    employee_count_filter: str = '.filter-item.employeeCount, .filter-item.headCount'
    contact_criteria: str = 'button:has-text("Contact Criteria"), [role="button"]:has-text("Contact Criteria")'
    company_criteria: str = 'button:has-text("Company Criteria"), [role="button"]:has-text("Company Criteria")'
    filter_section_template: str = 'button:has-text("{label}"), [role="button"]:has-text("{label}")'
    filter_section_text_template: str = 'text={label}'
    filter_search_input: str = 'input[placeholder*="Search" i]:visible'
    industry_search_input: str = '.accordion-checkbox-list input[placeholder="Search"]:visible'
    industry_option_template: str = '.accordion-checkbox-list label:has-text("{value}")'
    job_title_input: str = 'input[placeholder="Title"]:visible'
    job_title_suggestion_template: str = 'text={query}'
    location_country_tab: str = '.filter-content-section .tab:has-text("Country")'
    location_country_input: str = 'input[placeholder="Country"]:visible'
    filter_option_template: str = 'label:has-text("{value}"), [role="option"]:has-text("{value}")'
    filter_option_text_template: str = 'text={value}'
    see_matching_contacts: str = 'button:has-text("See Matching Contacts")'
    login_email: str = '#siEmailInput:visible, input[type="email"]:visible, input[name="email"]:visible'
    login_password: str = '#siPasswordInput:visible, input[type="password"]:visible'
    login_submit: str = 'button[type="submit"]:visible, input[type="submit"]:visible'
    prospect_search_nav: str = 'a:has-text("Prospect Search"), [role="link"]:has-text("Prospect Search")'


SELECTORS = AdaptSelectors()
DEFAULT_ADAPT_SEARCH_URL = "https://leads.adapt.io/advanced-search/contact#search"


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    search_url: str
    headless: bool
    browser_channel: str | None
    browser_executable_path: Path | None
    viewport_width: int
    viewport_height: int
    user_agent: str | None
    manual_login_timeout_seconds: int
    timeout_ms: int
    max_retries: int
    retry_base_seconds: float
    min_action_delay_seconds: float
    max_action_delay_seconds: float
    page_load_settle_seconds: float
    data_dir: Path
    output_filename: str
    log_level: str

    @property
    def session_path(self) -> Path:
        return self.data_dir / "playwright_storage_state.json"

    @property
    def pages_dir(self) -> Path:
        return self.data_dir / "pages"

    @property
    def manifest_path(self) -> Path:
        return self.data_dir / "manifest.json"

    @property
    def output_path(self) -> Path:
        return self.data_dir / self.output_filename

    @property
    def merge_database_path(self) -> Path:
        return self.data_dir / "merge_dedup.sqlite3"

    @property
    def cleaned_output_path(self) -> Path:
        return self.data_dir / "adapt_master_cleaned.csv"

    @property
    def email_candidates_output_path(self) -> Path:
        return self.data_dir / "adapt_email_candidates.csv"

    @classmethod
    def from_env(
        cls,
        project_dir: Path,
        *,
        search_url_override: str | None = None,
        data_dir_override: Path | None = None,
    ) -> "Settings":
        # The exporter is part of the backend deployment, so it shares the
        # backend's one environment file instead of maintaining a second one.
        load_dotenv(project_dir / ".env")
        # A saved search URL is optional. The normal flow starts from Adapt's base
        # search page and applies the filters supplied by the application.
        search_url = search_url_override or os.getenv("ADAPT_SEARCH_URL", "").strip() or DEFAULT_ADAPT_SEARCH_URL
        raw_data_dir = data_dir_override or Path(os.getenv("DATA_DIR", "data"))
        data_dir = raw_data_dir if raw_data_dir.is_absolute() else project_dir / raw_data_dir
        channel = os.getenv("BROWSER_CHANNEL", "chromium").strip() or None
        user_agent = os.getenv("USER_AGENT", "").strip() or None
        executable_path = _resolve_browser_executable_path()
        return cls(
            search_url=search_url,
            headless=_as_bool(os.getenv("HEADLESS", "true")),
            browser_channel=channel,
            browser_executable_path=executable_path,
            viewport_width=int(os.getenv("VIEWPORT_WIDTH", "1440")),
            viewport_height=int(os.getenv("VIEWPORT_HEIGHT", "1000")),
            user_agent=user_agent,
            manual_login_timeout_seconds=int(os.getenv("MANUAL_LOGIN_TIMEOUT_SECONDS", "900")),
            timeout_ms=int(os.getenv("TIMEOUT_MS", "45000")),
            max_retries=int(os.getenv("MAX_RETRIES", "4")),
            retry_base_seconds=float(os.getenv("RETRY_BASE_SECONDS", "2.0")),
            min_action_delay_seconds=float(os.getenv("MIN_ACTION_DELAY_SECONDS", "0.7")),
            max_action_delay_seconds=float(os.getenv("MAX_ACTION_DELAY_SECONDS", "1.8")),
            page_load_settle_seconds=float(os.getenv("PAGE_LOAD_SETTLE_SECONDS", "1.2")),
            data_dir=data_dir,
            output_filename=os.getenv("OUTPUT_FILENAME", "adapt_search_results.csv"),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
