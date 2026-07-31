"""Orchestration of login, resume, extraction, checkpointing, and final merge."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
import subprocess
import sys
from pathlib import Path
from typing import Awaitable, Callable, TypeVar

from playwright.async_api import async_playwright

from .browser import AdaptBrowser
from .checkpoint import CheckpointStore
from .config import Settings
from .filters import AdaptFilterApplier
from .merge import CsvMerger
from .models import AdaptCredentials, Manifest, SearchFilters
from .postprocess import CsvPostProcessor


T = TypeVar("T")


class AdaptExporter:
    def __init__(self, settings: Settings, logger: logging.Logger, filters: SearchFilters | None = None, credentials: AdaptCredentials | None = None) -> None:
        self.settings = settings
        self.logger = logger
        self.store = CheckpointStore(settings.data_dir, settings.pages_dir, settings.manifest_path)
        self.filters = filters or SearchFilters()
        self.credentials = credentials or AdaptCredentials()

    async def run(self) -> None:
        manifest = self.store.load()
        if manifest.is_complete:
            self.logger.info("Existing run is complete; regenerating final CSV from checkpoints.")
            self._merge(manifest)
            return
        async with async_playwright() as playwright:
            launch_kwargs = {
                "headless": self.settings.headless,
                "args": ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            }
            if self.settings.browser_executable_path:
                launch_kwargs["executable_path"] = str(self.settings.browser_executable_path)
                self.logger.info("Using local browser executable: %s", self.settings.browser_executable_path)
            elif self.settings.browser_channel:
                launch_kwargs["channel"] = self.settings.browser_channel
            try:
                browser = await playwright.chromium.launch(**launch_kwargs)
            except Exception as e:
                if "Executable doesn't exist" in str(e):
                    self.logger.warning("Playwright browser missing. Attempting to install...")
                    result = subprocess.run(
                        [sys.executable, "-m", "playwright", "install", "chromium"],
                        capture_output=True, text=True,
                    )
                    if result.returncode != 0:
                        self.logger.warning("playwright install failed, trying with system deps: %s", result.stderr[:500])
                        result = subprocess.run(
                            [sys.executable, "-m", "playwright", "install", "chromium", "--with-deps"],
                            capture_output=True, text=True,
                        )
                    if result.returncode != 0:
                        raise RuntimeError(f"playwright install failed: {result.stderr[:500]}") from e
                    self.logger.info("Browser installed. Retrying launch.")
                    browser = await playwright.chromium.launch(**launch_kwargs)
                else:
                    raise
            context = await browser.new_context(
                storage_state=str(self.settings.session_path) if self.settings.session_path.exists() else None,
                viewport={"width": self.settings.viewport_width, "height": self.settings.viewport_height},
                user_agent=self.settings.user_agent,
            )
            page = await context.new_page()
            page.on("console", lambda message: self.logger.warning("Browser console: %s", message.text) if message.type == "error" else None)
            page.on("requestfailed", lambda request: self.logger.warning("Browser request failed: %s (%s)", request.url, request.failure))
            page.on("response", lambda response: self.logger.warning("Browser HTTP %s: %s", response.status, response.url) if response.status >= 400 else None)
            client = AdaptBrowser(browser, context, page, self.settings, self.logger)
            try:
                if self.settings.session_path.exists():
                    self.logger.info("Loaded saved Playwright session.")
                elif self.settings.headless and not self.credentials.email:
                    raise RuntimeError(
                        "Headless Playwright requires saved session state or Adapt email and password."
                    )
                else:
                    self.logger.info("No saved session. Signing in with supplied Adapt credentials.")
                await self._retry(
                    "opening search",
                    lambda: client.open_search(
                        manual_login=not self.settings.session_path.exists() and not bool(self.credentials.email),
                        credentials=self.credentials,
                        wait_for_results=not any((self.filters.job_titles, self.filters.industries, self.filters.country, self.filters.employee_counts)),
                    ),
                )
                with suppress(Exception):
                    await context.storage_state(path=str(self.settings.session_path))
                    self.logger.info("Session state saved immediately after opening search/login to %s", self.settings.session_path)
                try:
                    # Retrying the whole filter flow can click an already selected
                    # checkbox a second time and remove it. Individual UI actions
                    # have their own timeouts; preserve the user's selections.
                    await AdaptFilterApplier(page, self.settings, self.logger).apply(self.filters)
                except Exception:
                    screenshot_path = self.settings.data_dir / "filter_failure.png"
                    html_path = self.settings.data_dir / "filter_failure.html"
                    with suppress(Exception):
                        await page.screenshot(path=str(screenshot_path), full_page=True)
                    with suppress(Exception):
                        html_path.write_text(await page.content(), encoding="utf-8")
                    self.logger.error("Saved filter diagnostics to %s and %s", screenshot_path, html_path)
                    raise
                await self._retry("waiting for filtered Adapt results", lambda: self._wait_for_filtered_results(client, page))
                if not self.settings.session_path.exists():
                    await context.storage_state(path=str(self.settings.session_path))
                    self.logger.info("Manual login detected; session saved to %s", self.settings.session_path)
                await self._export_pages(client, manifest)
                manifest.is_complete = True
                self.store.save_manifest(manifest)
                self._merge(manifest)
            finally:
                # Preserve the original failure if the user/browser closed the window.
                with suppress(Exception):
                    await context.storage_state(path=str(self.settings.session_path))
                with suppress(Exception):
                    await context.close()
                with suppress(Exception):
                    await browser.close()

    async def _export_pages(self, client: AdaptBrowser, manifest: Manifest) -> None:
        target_page = manifest.next_page
        current_page = 1
        self.logger.info("Resume target: page %s. Previously saved pages: %s", target_page, len(manifest.completed_pages))
        while current_page < target_page:
            signature = await self._retry("reading resume-page signature", client.row_signature)
            advanced = await self._retry("advancing while resuming", lambda: client.click_next_and_wait(signature))
            if not advanced:
                raise RuntimeError(
                    "Saved checkpoint extends beyond available pagination. The search URL or its result set may have changed; "
                    "review data/manifest.json before resuming."
                )
            current_page += 1
        previous_signature: str | None = None
        while True:
            await client.human_scroll()
            signature = await self._retry("reading page signature", client.row_signature)
            if signature == previous_signature:
                self.logger.warning("Page %s has no new rows; stopping to prevent a pagination loop.", current_page)
                break
            frame = await self._retry("extracting page", client.extract_table)
            manifest = self.store.save_page(current_page, frame, manifest)
            self.logger.info("Saved page %s: %s rows. Checkpoint count: %s", current_page, len(frame), len(manifest.completed_pages))
            with suppress(Exception):
                await client.context.storage_state(path=str(self.settings.session_path))
                self.logger.info("Session state updated after scraping page %s", current_page)
            previous_signature = signature
            advanced = await self._retry("clicking next page", lambda: client.click_next_and_wait(signature))
            if not advanced:
                self.logger.info("No enabled Next Page button after page %s.", current_page)
                break
            current_page += 1

    def _merge(self, manifest) -> None:
        rows, _ = CsvMerger(self.settings.pages_dir, self.settings.output_path, self.settings.merge_database_path).merge(manifest)
        cleaned, candidates = CsvPostProcessor(
            self.settings.output_path,
            self.settings.cleaned_output_path,
            self.settings.email_candidates_output_path,
        ).process()
        self.logger.info(
            "Completed: %s checkpoint pages, %s unique rows. raw=%s cleaned=%s candidates=%s (%s generated)",
            len(manifest.completed_pages), rows, self.settings.output_path,
            self.settings.cleaned_output_path, self.settings.email_candidates_output_path, candidates,
        )

    async def _wait_for_filtered_results(self, client: AdaptBrowser, page) -> None:
        try:
            await client.wait_for_table()
        except Exception:
            screenshot_path = self.settings.data_dir / "results_failure.png"
            html_path = self.settings.data_dir / "results_failure.html"
            with suppress(Exception):
                await page.screenshot(path=str(screenshot_path), full_page=True)
            with suppress(Exception):
                html_path.write_text(await page.content(), encoding="utf-8")
            self.logger.error("Saved results diagnostics to %s and %s", screenshot_path, html_path)
            raise

    async def _retry(self, action_name: str, operation: Callable[[], Awaitable[T]]) -> T:
        last_error: Exception | None = None
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                return await operation()
            except Exception as error:  # Browser/network/DOM failures must be recoverable.
                last_error = error
                if attempt == self.settings.max_retries:
                    break
                delay = self.settings.retry_base_seconds * (2 ** (attempt - 1))
                self.logger.warning("%s failed (attempt %s/%s): %s. Retrying in %.1fs", action_name, attempt, self.settings.max_retries, error, delay)
                await asyncio.sleep(delay)
        raise RuntimeError(f"{action_name} failed after {self.settings.max_retries} attempts") from last_error
