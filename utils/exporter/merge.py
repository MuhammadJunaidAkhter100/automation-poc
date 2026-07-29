"""Streaming final CSV merge with SQLite-backed duplicate protection."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path

from .models import Manifest


PREFERRED_KEYS = ("email", "linkedin", "adapt id", "adapt_id")


class CsvMerger:
    def __init__(self, pages_dir: Path, output_path: Path, database_path: Path) -> None:
        self.pages_dir = pages_dir
        self.output_path = output_path
        self.database_path = database_path

    def merge(self, manifest: Manifest) -> tuple[int, int]:
        self.database_path.unlink(missing_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.execute("CREATE TABLE records (dedupe_key TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        inserted = 0
        try:
            for page_number in manifest.completed_pages:
                page_path = self.pages_dir / f"page_{page_number:07d}.csv"
                if not page_path.exists():
                    continue
                with page_path.open("r", encoding="utf-8", newline="") as source:
                    for row in csv.DictReader(source):
                        key = self._dedupe_key(row, manifest.columns)
                        cursor = connection.execute(
                            "INSERT OR IGNORE INTO records (dedupe_key, payload) VALUES (?, ?)",
                            (key, json.dumps(row, ensure_ascii=False)),
                        )
                        inserted += cursor.rowcount
            connection.commit()
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            with self.output_path.open("w", encoding="utf-8", newline="") as destination:
                writer = csv.DictWriter(destination, fieldnames=manifest.columns, extrasaction="ignore")
                writer.writeheader()
                for (payload,) in connection.execute("SELECT payload FROM records ORDER BY rowid"):
                    writer.writerow(json.loads(payload))
            total = connection.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            return total, inserted
        finally:
            connection.close()
            self.database_path.unlink(missing_ok=True)

    @staticmethod
    def _dedupe_key(row: dict[str, str], columns: list[str]) -> str:
        lowered = {column.lower().strip(): value.strip() for column, value in row.items() if value}
        for preferred in PREFERRED_KEYS:
            for column, value in lowered.items():
                if preferred in column and value:
                    return f"{preferred}:{value.lower()}"
        stable_value = "\x1f".join(row.get(column, "") for column in columns)
        return "row:" + hashlib.sha256(stable_value.encode("utf-8")).hexdigest()
