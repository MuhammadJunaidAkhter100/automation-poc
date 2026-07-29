"""Crash-safe page checkpoints and run manifest management."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .models import Manifest


class CheckpointStore:
    def __init__(self, data_dir: Path, pages_dir: Path, manifest_path: Path) -> None:
        self.data_dir = data_dir
        self.pages_dir = pages_dir
        self.manifest_path = manifest_path
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.pages_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> Manifest:
        if not self.manifest_path.exists():
            return Manifest()
        raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        return Manifest(
            completed_pages=sorted(set(int(page) for page in raw.get("completed_pages", []))),
            columns=list(raw.get("columns", [])),
            is_complete=bool(raw.get("is_complete", False)),
        )

    def save_page(self, page_number: int, frame: pd.DataFrame, manifest: Manifest) -> Manifest:
        page_path = self.pages_dir / f"page_{page_number:07d}.csv"
        temporary_path = page_path.with_suffix(".tmp")
        frame.to_csv(temporary_path, index=False, encoding="utf-8", lineterminator="\n")
        temporary_path.replace(page_path)
        manifest.completed_pages = sorted(set(manifest.completed_pages + [page_number]))
        for column in frame.columns:
            if column not in manifest.columns:
                manifest.columns.append(column)
        self.save_manifest(manifest)
        return manifest

    def save_manifest(self, manifest: Manifest) -> None:
        temporary_path = self.manifest_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(
                {
                    "completed_pages": manifest.completed_pages,
                    "columns": manifest.columns,
                    "is_complete": manifest.is_complete,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary_path.replace(self.manifest_path)
