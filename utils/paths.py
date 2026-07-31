"""Filesystem locations for ephemeral exporter artifacts.

Supabase owns application metadata; these files are runtime artifacts and should
be backed by a persistent volume in production.
"""

from pathlib import Path

from database.settings import settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = settings.backend_data_dir if settings.backend_data_dir.is_absolute() else BACKEND_DIR / settings.backend_data_dir
RUNS_DIR = DATA_DIR / "runs"


def run_dir(session_id: int) -> Path:
    path = RUNS_DIR / str(session_id)
    path.mkdir(parents=True, exist_ok=True)
    return path
