"""CLI entry point."""

from __future__ import annotations

import asyncio
import argparse
import json
import logging
import os
from pathlib import Path

from utils.exporter.config import Settings
from utils.exporter.exporter import AdaptExporter
from utils.exporter.logging_setup import configure_logging
from utils.exporter.models import AdaptCredentials, SearchFilters


def main() -> int:
    project_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Export an Adapt search with optional UI-supplied filters.")
    parser.add_argument("--filters-file", type=Path)
    parser.add_argument("--credentials-file", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--search-url")
    args = parser.parse_args()
    try:
        settings = Settings.from_env(
            project_dir,
            search_url_override=args.search_url,
            data_dir_override=args.data_dir,
        )
        filters = SearchFilters()
        if args.filters_file:
            filters = SearchFilters.from_mapping(json.loads(args.filters_file.read_text(encoding="utf-8")))
        credentials = AdaptCredentials()
        if args.credentials_file:
            credentials = AdaptCredentials.from_mapping(json.loads(args.credentials_file.read_text(encoding="utf-8")))
            args.credentials_file.unlink(missing_ok=True)
        elif os.getenv("ADAPT_EMAIL") and os.getenv("ADAPT_PASSWORD"):
            credentials = AdaptCredentials(
                email=os.getenv("ADAPT_EMAIL", ""),
                password=os.getenv("ADAPT_PASSWORD", ""),
            )
    except ValueError as error:
        print(f"Configuration error: {error}")
        return 2
    logger = configure_logging(project_dir / "data" / "logs", settings.log_level)
    try:
        asyncio.run(AdaptExporter(settings, logger, filters, credentials).run())
    except KeyboardInterrupt:
        logger.warning("Interrupted. Completed pages are checkpointed; rerun main.py to resume.")
        return 130
    except Exception:
        logger.exception("Export failed. Completed pages are checkpointed; rerun main.py to resume.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
