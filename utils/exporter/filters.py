"""Visible Adapt filter-panel interaction for UI-supplied search filters."""

from __future__ import annotations

import asyncio
import logging
import time

from playwright.async_api import Page

from .config import SELECTORS, Settings
from .models import SearchFilters


class AdaptFilterApplier:
    def __init__(self, page: Page, settings: Settings, logger: logging.Logger) -> None:
        self.page = page
        self.settings = settings
        self.logger = logger
        self.root = page.locator(SELECTORS.filters_root).first

    async def apply(self, filters: SearchFilters) -> None:
        if not any((filters.job_titles, filters.industries, filters.country, filters.employee_counts)):
            return
        button = self.page.locator(SELECTORS.filters_button).first
        if await button.count() > 0 and await button.is_visible():
            await button.click(timeout=self.settings.timeout_ms)
        await self.root.wait_for(state="visible", timeout=self.settings.timeout_ms)
        await self._clear_existing_filters()
        await self._expand(SELECTORS.contact_criteria)
        await self._select_many("Job Title", filters.job_titles)
        if filters.country:
            await self._select_many("Location", (filters.country,))
        await self._expand(SELECTORS.company_criteria)
        await self._select_many("Industry", filters.industries)
        await self._select_many("Employee Count", filters.employee_counts)
        await self.page.screenshot(path=str(self.settings.data_dir / "filters_ready.png"), full_page=True)
        submit = self.root.locator(SELECTORS.see_matching_contacts).first
        if await submit.count() > 0 and await submit.is_visible():
            await self._wait_for_matching_contacts(submit)
            # Adapt's sticky filter content overlaps this enabled footer button in
            # Playwright's hit test; dispatch the click to the verified button.
            await submit.click(timeout=self.settings.timeout_ms, force=True)
            await asyncio.sleep(self.settings.page_load_settle_seconds)
            self.logger.info("Submitted the Adapt filters and requested matching contacts.")
        else:
            raise RuntimeError("Adapt's 'See Matching Contacts' button was not available after applying filters.")

    async def _expand(self, selector: str) -> None:
        group = self.root.locator(selector).first
        # Accordion headings that are already open must not be clicked again.
        if (
            await group.count() > 0
            and await group.is_visible()
            and await group.get_attribute("aria-expanded") == "false"
        ):
            await group.click(timeout=self.settings.timeout_ms)

    async def _clear_existing_filters(self) -> None:
        """Every new app session owns its filter state; never inherit Adapt's old chips."""
        clear = self.root.locator(SELECTORS.clear_all_filters).first
        if await clear.count() > 0 and await clear.is_visible():
            await clear.click(timeout=self.settings.timeout_ms, force=True)
            await asyncio.sleep(0.5)
            self.logger.info("Cleared pre-existing Adapt filters before applying this session.")

    async def _select_many(self, label: str, values: tuple[str, ...]) -> None:
        if not values:
            return
        selector_by_label = {
            "Job Title": SELECTORS.job_title_filter,
            "Location": SELECTORS.location_filter,
            "Industry": SELECTORS.industry_filter,
            "Employee Count": SELECTORS.employee_count_filter,
        }
        section = self.root.locator(selector_by_label[label]).first
        await section.click(timeout=self.settings.timeout_ms)
        if label == "Job Title":
            query = self.root.locator(SELECTORS.job_title_input).first
            for value in values:
                await query.fill(value)
                await asyncio.sleep(0.5)
                suggestion = self.root.locator(SELECTORS.job_title_suggestion_template.format(query=value)).last
                await suggestion.click(timeout=min(self.settings.timeout_ms, 5_000))
                self.logger.info("Applied Adapt filter Job Title=%s", value)
            return
        if label == "Location":
            country_tab = self.root.locator(SELECTORS.location_country_tab).first
            await country_tab.click(timeout=self.settings.timeout_ms)
            country_search = self.root.locator(SELECTORS.location_country_input).first
            await country_search.fill(values[0])
            option = await self._wait_for_option(values[0])
            await option.click(timeout=min(self.settings.timeout_ms, 5_000))
            self.logger.info("Applied Adapt filter Location=%s", values[0])
            return
        if label == "Industry":
            search = self.root.locator(SELECTORS.industry_search_input).first
            await search.wait_for(state="visible", timeout=self.settings.timeout_ms)
            for value in values:
                option = await self._find_industry_option(search, value)
                await option.click(timeout=min(self.settings.timeout_ms, 5_000))
                self.logger.info("Applied Adapt filter Industry=%s", value)
                await search.fill("")
            return
        for value in values:
            search = self.root.locator(SELECTORS.filter_search_input).last
            if await search.count() > 0 and await search.is_visible():
                await search.fill(value)
                await asyncio.sleep(0.25)
            option = await self._wait_for_option(value)
            # A missing option indicates a different picker layout; fail quickly so
            # the exporter can save diagnostics instead of appearing stuck.
            already_selected = await option.evaluate(
                """element => {
                    const input = element.matches('input[type=checkbox]') ? element :
                        element.querySelector('input[type=checkbox]') ||
                        element.parentElement?.querySelector('input[type=checkbox]');
                    return Boolean(input?.checked);
                }"""
            )
            if already_selected:
                self.logger.info("Adapt filter %s=%s was already selected; leaving it selected.", label, value)
                continue
            await option.click(timeout=min(self.settings.timeout_ms, 5_000))
            self.logger.info("Applied Adapt filter %s=%s", label, value)

    async def _find_industry_option(self, search, value: str):
        """Adapt's labels changed from '&' to 'and' for some industry names."""
        candidates = (value, value.replace(" & ", " and "))
        last_error: RuntimeError | None = None
        for candidate in dict.fromkeys(candidates):
            await search.fill(candidate)
            try:
                return await self._wait_for_option(candidate, SELECTORS.industry_option_template, timeout_seconds=7)
            except RuntimeError as error:
                last_error = error
        raise RuntimeError(f"Adapt did not show an Industry option for {value!r} or its Adapt label variant.") from last_error

    async def _wait_for_option(self, value: str, selector_template: str | None = None, timeout_seconds: float | None = None):
        """Adapt replaces its suggestion loader asynchronously; wait for the item."""
        deadline = time.monotonic() + (timeout_seconds or min(self.settings.timeout_ms / 1000, 15))
        while time.monotonic() < deadline:
            template = selector_template or SELECTORS.filter_option_template
            option = self.root.locator(template.format(value=value)).last
            if await option.count() == 0 and selector_template is None:
                option = self.root.locator(SELECTORS.filter_option_text_template.format(value=value)).last
            if await option.count() > 0 and await option.is_visible():
                return option
            await asyncio.sleep(0.25)
        raise RuntimeError(f"Adapt did not show an option for {value!r}; no filter was changed.")

    async def _wait_for_matching_contacts(self, submit) -> None:
        deadline = time.monotonic() + self.settings.timeout_ms / 1000
        while time.monotonic() < deadline:
            if not await submit.is_disabled():
                return
            await asyncio.sleep(0.5)
        raise RuntimeError("Adapt did not enable 'See Matching Contacts' before the configured timeout.")
