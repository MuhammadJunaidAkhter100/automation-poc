"""Human-paced Playwright table interaction."""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time

import pandas as pd
from playwright.async_api import Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

from .config import SELECTORS, Settings
from .models import AdaptCredentials


class AdaptBrowser:
    def __init__(self, browser: Browser, context: BrowserContext, page: Page, settings: Settings, logger: logging.Logger) -> None:
        self.browser = browser
        self.context = context
        self.page = page
        self.settings = settings
        self.logger = logger

    async def open_search(
        self,
        manual_login: bool = False,
        credentials: AdaptCredentials | None = None,
        wait_for_results: bool = True,
    ) -> None:
        await self.page.goto(self.settings.search_url, wait_until="domcontentloaded", timeout=self.settings.timeout_ms)
        if await self._is_login_page():
            if credentials and credentials.email and credentials.password:
                await self._login(credentials)
            elif manual_login:
                self.logger.info("Adapt login is required. Complete it in the visible Chromium window.")
                await self._wait_for_login_to_finish()
            else:
                raise RuntimeError("The saved Adapt session expired and no app login credentials were supplied.")
        await self._go_to_prospect_search()
        if not wait_for_results:
            # A new contact search intentionally has no result rows yet. Wait for
            # the filter shell, not a table that can only exist after submission.
            await self.page.locator(SELECTORS.filters_root).first.wait_for(state="visible", timeout=self.settings.timeout_ms)
            return
        timeout = self.settings.manual_login_timeout_seconds * 1000 if manual_login else self.settings.timeout_ms
        await self.wait_for_table(timeout)

    async def _is_login_page(self) -> bool:
        for _ in range(10):
            url = self.page.url.lower()
            if "login" in url or "signin" in url:
                return True
            email = self.page.locator(SELECTORS.login_email).first
            if await email.count() > 0 and await email.is_visible():
                return True
            filters = self.page.locator(SELECTORS.filters_root).first
            if await filters.count() > 0 and await filters.is_visible():
                return False
            await asyncio.sleep(0.5)
        url = self.page.url.lower()
        return "login" in url or "signin" in url

    async def _wait_for_login_to_finish(self) -> None:
        deadline = time.monotonic() + self.settings.manual_login_timeout_seconds
        while time.monotonic() < deadline:
            if not await self._is_login_page():
                return
            await asyncio.sleep(0.5)
        raise PlaywrightTimeoutError("Manual Adapt login did not complete before the configured timeout.")

    async def _login(self, credentials: AdaptCredentials) -> None:
        email = self.page.locator(SELECTORS.login_email).first
        password = self.page.locator(SELECTORS.login_password).first
        await email.wait_for(state="visible", timeout=self.settings.timeout_ms)
        await email.fill(credentials.email)
        await password.fill(credentials.password)
        await self._human_pause()
        await self.page.locator(SELECTORS.login_submit).first.click(timeout=self.settings.timeout_ms)
        await self._wait_for_login_to_finish()
        self.logger.info("Submitted Adapt login form using the app credentials.")

    async def _go_to_prospect_search(self) -> None:
        if "/advanced-search/contact" in self.page.url:
            return
        prospect_search = self.page.locator(SELECTORS.prospect_search_nav).first
        if await prospect_search.count() > 0 and await prospect_search.is_visible():
            await prospect_search.click(timeout=self.settings.timeout_ms)
            await self.page.wait_for_url("**/advanced-search/contact**", timeout=self.settings.timeout_ms)
            self.logger.info("Navigated from the Adapt dashboard to Prospect Search.")
            return
        await self.page.goto(self.settings.search_url, wait_until="domcontentloaded", timeout=self.settings.timeout_ms)
        await self.page.wait_for_url("**/advanced-search/contact**", timeout=self.settings.timeout_ms)
        self.logger.info("Opened Prospect Search directly because the navigation link was unavailable.")

    async def wait_for_table(self, timeout_ms: int | None = None) -> None:
        timeout = timeout_ms or self.settings.timeout_ms
        table = self.page.locator(SELECTORS.results_table).first
        await table.wait_for(state="visible", timeout=timeout)
        await self.page.locator(SELECTORS.body_rows).first.wait_for(state="visible", timeout=timeout)
        await self.page.wait_for_timeout(int(self.settings.page_load_settle_seconds * 1000))

    async def extract_table(self) -> pd.DataFrame:
        table = self.page.locator(SELECTORS.results_table).first
        headers = await table.locator(SELECTORS.header_cells).all_inner_texts()
        headers = [self._clean(value) for value in headers]
        if not headers:
            raise RuntimeError("Results table has no visible header cells. Update SELECTORS.header_cells.")
        headers = self._unique_headers(headers)
        rows = table.locator(SELECTORS.body_rows)
        row_count = await rows.count()
        records: list[dict[str, str]] = []
        for index in range(row_count):
            row = rows.nth(index)
            cells = await row.locator(SELECTORS.row_cells).all_inner_texts()
            values = [self._clean(value) for value in cells]
            if not values:
                continue
            record = {header: values[position] if position < len(values) else "" for position, header in enumerate(headers)}
            # Adapt's result rows contain useful fields in nested divs/links rather
            # than separate table columns. Keep the visible columns above and add
            # these machine-readable fields for the final CSV normaliser.
            record.update(await self._adapt_row_fields(row))
            records.append(record)
        if not records:
            raise RuntimeError("No visible table rows were extracted; the table may be virtualized or selectors changed.")
        columns = self._unique_headers(headers + [
            "First Name", "Last Name", "Job Title", "Company Name", "LinkedIn URL",
            "Domain", "Industry", "Email", "Headcount", "Location",
        ])
        return pd.DataFrame.from_records(records, columns=columns)

    async def _adapt_row_fields(self, row) -> dict[str, str]:
        """Read known nested Adapt fields without clicking View/Find or bypassing access."""
        values = await row.evaluate(
            """element => {
                const text = selector => (element.querySelector(selector)?.getAttribute('title') ||
                    element.querySelector(selector)?.textContent || '').replace(/\\s+/g, ' ').trim();
                const href = selector => element.querySelector(selector)?.getAttribute('href') || '';
                const links = Array.from(element.querySelectorAll('a[href]'));
                const linkedin = links.find(link => /linkedin\\.com\\/in\\//i.test(link.href))?.href || '';
                const website = links.find(link => /^https?:/i.test(link.href) &&
                    !/(linkedin|facebook|twitter|x\\.com)/i.test(link.href))?.href || '';
                const rawDetails = text('.company-details-wrapper, .company-detail-wrapper, .company-details') || '';
                const name = text('.contact-name');
                const parts = name.split(/\\s+/).filter(Boolean);
                let domain = '';
                try { domain = website ? new URL(website).hostname.replace(/^www\\./i, '') : ''; } catch (_) {}
                return {
                    'First Name': parts[0] || '',
                    'Last Name': parts.slice(1).join(' '),
                    'Job Title': text('.contact-name-wrapper .title'),
                    'Company Name': text('.company-name'),
                    'LinkedIn URL': linkedin,
                    'Domain': domain,
                    'Industry': text('.company-details .industry, .company-details-wrapper .industry'),
                    'Email': text('.contact-email .info-detail'),
                    'Headcount': text('.company-details .employee-count, .company-details-wrapper .employee-count'),
                    'Location': text('.contact-name-wrapper .location-wrapper .info-detail'),
                    '__company_details': rawDetails,
                };
            }"""
        )
        return {key: self._clean(value) for key, value in values.items() if key != "__company_details"}

    async def next_is_available(self) -> bool:
        next_button = self.page.locator(SELECTORS.next_page).first
        if await next_button.count() == 0 or not await next_button.is_visible():
            await self._raise_if_pagination_is_incomplete()
            return False
        if await self.page.locator(SELECTORS.disabled_next_page).count() > 0:
            return False
        return not await next_button.is_disabled()

    async def _raise_if_pagination_is_incomplete(self) -> None:
        """Never report a one-page success when Adapt itself reports more pages."""
        text = await self._pagination_text()
        if not text:
            return
        match = re.search(r"Pages\s+(\d+)\s+of\s+(\d+)", text, flags=re.IGNORECASE)
        if match and int(match.group(1)) < int(match.group(2)):
            raise RuntimeError(
                f"Adapt reports {text!r}, but its enabled Next control was not found. "
                "Stopping would lose pages; update the pagination selector."
            )

    async def _pagination_text(self) -> str:
        pagination = self.page.locator(".pagination").last
        if await pagination.count() == 0:
            return ""
        return self._clean(await pagination.inner_text())

    async def click_next_and_wait(self, prior_signature: str) -> bool:
        if not await self.next_is_available():
            return False
        next_button = self.page.locator(SELECTORS.next_page).first
        await self._human_pause()
        await next_button.scroll_into_view_if_needed()
        box = await next_button.bounding_box()
        if box:
            await self.page.mouse.move(box["x"] + random.uniform(2, box["width"] - 2), box["y"] + random.uniform(2, box["height"] - 2), steps=random.randint(4, 10))
        before_page = await self._pagination_text()
        # React renders Next as a span. A normal Playwright click can be accepted
        # by the DOM without invoking this app's handler, so use a forced click
        # and a native event fallback before declaring a pagination failure.
        await next_button.click(timeout=self.settings.timeout_ms, force=True)
        await asyncio.sleep(0.75)
        if await self.row_signature() == prior_signature and await self._pagination_text() == before_page:
            await next_button.dispatch_event("click")
            self.logger.info("Dispatched native click fallback for Adapt Next Page (%s).", before_page)
        await self._wait_for_changed_rows(prior_signature)
        return True

    async def human_scroll(self) -> None:
        await self.page.mouse.wheel(0, random.randint(180, 420))
        await self._human_pause()
        await self.page.mouse.wheel(0, random.randint(-160, -60))

    async def _wait_for_changed_rows(self, prior_signature: str) -> None:
        deadline = time.monotonic() + self.settings.timeout_ms / 1000
        while time.monotonic() < deadline:
            try:
                if await self.row_signature() != prior_signature:
                    await self.wait_for_table()
                    return
            except PlaywrightTimeoutError:
                pass
            await asyncio.sleep(0.25)
        raise PlaywrightTimeoutError("The results table did not change after clicking Next Page.")

    async def row_signature(self) -> str:
        rows = await self.page.locator(SELECTORS.body_rows).all_inner_texts()
        return "\n".join(self._clean(row) for row in rows)

    async def _human_pause(self) -> None:
        await asyncio.sleep(random.uniform(self.settings.min_action_delay_seconds, self.settings.max_action_delay_seconds))

    @staticmethod
    def _clean(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _unique_headers(headers: list[str]) -> list[str]:
        seen: dict[str, int] = {}
        output: list[str] = []
        for header in headers:
            base = header or "Unnamed column"
            seen[base] = seen.get(base, 0) + 1
            output.append(base if seen[base] == 1 else f"{base} ({seen[base]})")
        return output
