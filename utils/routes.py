from __future__ import annotations

import asyncio
import csv
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from database.supabase import supabase
from models.schemas import Filters, JobInput, LoginInput, ScrapeInput
from database.settings import settings

BACKEND = Path(__file__).resolve().parents[1]
from utils.exporter.finalize import VerifiedEmailFinalizer

DATA = settings.backend_data_dir if settings.backend_data_dir.is_absolute() else BACKEND / settings.backend_data_dir
RUNS = DATA / "runs"
PYTHON = settings.exporter_python or sys.executable
PROCESSES: dict[int, subprocess.Popen[str]] = {}

router = APIRouter()


def now() -> str:
    return datetime.now(UTC).isoformat()


def local_path(path: Path) -> Path:
    return path if path.is_absolute() else BACKEND / path


def safe_execute(query: Any) -> Any:
    try:
        return query.execute().data
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Supabase request failed: {error}") from error


def get_job(sid: int) -> dict[str, Any]:
    response = safe_execute(supabase.table("jobs").select("*").eq("id", sid).single())
    if response is None:
        raise HTTPException(404, "Session not found")
    return response


def folder(sid: int) -> Path:
    path = RUNS / str(sid)
    path.mkdir(parents=True, exist_ok=True)
    return path


def raw_output(sid: int) -> Path:
    return folder(sid) / "adapt_search_results.csv"


def output(sid: int) -> Path:
    return folder(sid) / "adapt_master_cleaned.csv"


def email_candidates_output(sid: int) -> Path:
    return folder(sid) / "adapt_email_candidates.csv"


def verified_upload(sid: int) -> Path:
    return folder(sid) / "mailtester_verified.csv"


def final_output(sid: int) -> Path:
    return folder(sid) / "salesforce_upload.csv"


def count_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8", errors="replace") as f:
        return max(sum(1 for _ in f) - 1, 0)


def count_email_candidates(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8-sig", newline="") as source:
        return sum(
            any((row.get(f"Email Combination {number}") or "").strip() for number in range(1, 9))
            for row in csv.DictReader(source)
        )


def build_filters(j: dict[str, Any]) -> Filters:
    split = lambda v: [x.strip() for x in (v or "").split(",") if x.strip()]
    return Filters(
        job_titles=split(j.get("target_keywords") or j["name"]),
        industries=split(j.get("industry")),
        country=j["location"],
        employee_counts=split(j.get("employee_count")),
    )


def tail_log(sid: int, lines: int = 30) -> str:
    path = folder(sid) / "process.log"
    if not path.exists():
        return ""
    with path.open("r", encoding="utf-8", errors="replace") as f:
        content = f.readlines()
    return "".join(content[-lines:]).strip()


def finish(sid: int, process: subprocess.Popen[str]) -> None:
    PROCESSES.pop(sid, None)
    run_session = folder(sid) / "playwright_storage_state.json"
    shared_session = DATA / "playwright_storage_state.json"
    if run_session.exists():
        shutil.copy2(run_session, shared_session)

    ok = process.returncode == 0 and output(sid).exists()
    status = "cleaned" if ok else "error"
    log_tail = tail_log(sid) if not ok else ""
    error_msg = None
    if not ok:
        error_msg = f"Exporter exited with code {process.returncode}"
        if log_tail:
            error_msg += f" | Details: {log_tail}"
    update_values = {
        "status": status,
        "error": error_msg,
        "finished_at": now(),
    }
    safe_execute(supabase.table("pipelines").update(update_values).eq("session_id", sid))
    safe_execute(supabase.table("jobs").update({"status": status}).eq("id", sid))


async def monitor(sid: int, process: subprocess.Popen[str]) -> None:
    while process.poll() is None:
        await asyncio.sleep(1)
    finish(sid, process)


def stats(sid: int) -> dict[str, Any]:
    j = get_job(sid)
    p = PROCESSES.get(sid)
    if p and p.poll() is not None:
        finish(sid, p)
    row = safe_execute(supabase.table("pipelines").select("status,error").eq("session_id", sid).single())
    total = count_rows(output(sid))
    final_rows = count_rows(final_output(sid))
    return {
        "session_id": sid,
        "session_name": j["name"],
        "status": row["status"] if row else j["status"],
        "total_rows": total,
        "email_combinations_count": count_email_candidates(email_candidates_output(sid)),
        "verified_count": final_rows,
        "final_count": final_rows,
        "error": row["error"] if row else None,
    }


@router.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/api/auth/login")
async def login(payload: LoginInput) -> dict[str, str]:
    return {"access_token": "local-adapt-session", "token_type": "bearer"}


def get_job(sid: int) -> dict[str, Any]:
    response = safe_execute(supabase.table("jobs").select("*").eq("id", sid).single())
    if response is None:
        raise HTTPException(404, "Session not found")
    return response


def folder(sid: int) -> Path:
    path = RUNS / str(sid)
    path.mkdir(parents=True, exist_ok=True)
    return path


def raw_output(sid: int) -> Path:
    return folder(sid) / "adapt_search_results.csv"


def output(sid: int) -> Path:
    return folder(sid) / "adapt_master_cleaned.csv"


def email_candidates_output(sid: int) -> Path:
    return folder(sid) / "adapt_email_candidates.csv"


def verified_upload(sid: int) -> Path:
    return folder(sid) / "mailtester_verified.csv"


def final_output(sid: int) -> Path:
    return folder(sid) / "salesforce_upload.csv"


def count_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8", errors="replace") as f:
        return max(sum(1 for _ in f) - 1, 0)


def count_email_candidates(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8-sig", newline="") as source:
        return sum(
            any((row.get(f"Email Combination {number}") or "").strip() for number in range(1, 9))
            for row in csv.DictReader(source)
        )


def build_filters(j: dict[str, Any]) -> Filters:
    split = lambda v: [x.strip() for x in (v or "").split(",") if x.strip()]
    return Filters(
        job_titles=split(j.get("target_keywords") or j["name"]),
        industries=split(j.get("industry")),
        country=j["location"],
        employee_counts=split(j.get("employee_count")),
    )


def tail_log(sid: int, lines: int = 30) -> str:
    path = folder(sid) / "process.log"
    if not path.exists():
        return ""
    with path.open("r", encoding="utf-8", errors="replace") as f:
        content = f.readlines()
    return "".join(content[-lines:]).strip()


def finish(sid: int, process: subprocess.Popen[str]) -> None:
    PROCESSES.pop(sid, None)
    run_session = folder(sid) / "playwright_storage_state.json"
    shared_session = DATA / "playwright_storage_state.json"
    if run_session.exists():
        shutil.copy2(run_session, shared_session)

    ok = process.returncode == 0 and output(sid).exists()
    status = "cleaned" if ok else "error"
    log_tail = tail_log(sid) if not ok else ""
    error_msg = None
    if not ok:
        error_msg = f"Exporter exited with code {process.returncode}"
        if log_tail:
            error_msg += f" | Details: {log_tail}"
    update_values = {
        "status": status,
        "error": error_msg,
        "finished_at": now(),
    }
    safe_execute(supabase.table("pipelines").update(update_values).eq("session_id", sid))
    safe_execute(supabase.table("jobs").update({"status": status}).eq("id", sid))


async def monitor(sid: int, process: subprocess.Popen[str]) -> None:
    while process.poll() is None:
        await asyncio.sleep(1)
    finish(sid, process)


def stats(sid: int) -> dict[str, Any]:
    j = get_job(sid)
    p = PROCESSES.get(sid)
    if p and p.poll() is not None:
        finish(sid, p)
    row = safe_execute(supabase.table("pipelines").select("status,error").eq("session_id", sid).single())
    total = count_rows(output(sid))
    final_rows = count_rows(final_output(sid))
    return {
        "session_id": sid,
        "session_name": j["name"],
        "status": row["status"] if row else j["status"],
        "total_rows": total,
        "email_combinations_count": count_email_candidates(email_candidates_output(sid)),
        "verified_count": final_rows,
        "final_count": final_rows,
        "error": row["error"] if row else None,
    }


@router.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/api/auth/login")
async def login(payload: LoginInput) -> dict[str, str]:
    return {"access_token": "local-adapt-session", "token_type": "bearer"}


@router.post("/api/jobs")
async def create(payload: JobInput) -> dict[str, Any]:
    values = payload.model_dump()
    values["created_at"] = now()
    job_response_list = safe_execute(supabase.table("jobs").insert(values).select("*"))
    if not job_response_list:
        raise HTTPException(500, "Failed to create job")
    job_response = job_response_list[0]
    safe_execute(
        supabase.table("pipelines").insert(
            {"session_id": job_response["id"], "status": job_response["status"]}
        )
    )
    return job_response


@router.get("/api/jobs")
async def list_jobs(skip: int = 0, limit: int = 100) -> list[dict[str, Any]]:
    return safe_execute(
        supabase.table("jobs").select("*").order("id", desc=True).range(skip, skip + limit - 1)
    )


@router.get("/api/jobs/{sid}")
async def get(sid: int) -> dict[str, Any]:
    return get_job(sid)


@router.put("/api/jobs/{sid}")
async def update(sid: int, payload: JobInput) -> dict[str, Any]:
    get_job(sid)
    values = payload.model_dump()
    updated_list = safe_execute(
        supabase.table("jobs").update(values).eq("id", sid).select("*")
    )
    if not updated_list:
        raise HTTPException(404, "Session not found")
    updated = updated_list[0]
    return updated


@router.delete("/api/jobs/{sid}", status_code=204)
async def delete(sid: int) -> None:
    process = PROCESSES.pop(sid, None)
    if process and process.poll() is None:
        process.terminate()
    get_job(sid)
    safe_execute(supabase.table("pipelines").delete().eq("session_id", sid))
    safe_execute(supabase.table("jobs").delete().eq("id", sid))


@router.post("/api/pipeline/{sid}/scrape")
async def scrape(sid: int, payload: ScrapeInput) -> dict[str, str]:
    j = get_job(sid)
    active = PROCESSES.get(sid)
    if active and active.poll() is None:
        return {"message": "Scraping is already running."}
    run = folder(sid)
    filters = payload.filters or build_filters(j)
    filter_file = run / "filters.json"
    filter_file.write_text(filters.model_dump_json(indent=2), encoding="utf-8")

    shared_session = DATA / "playwright_storage_state.json"
    if shared_session.exists():
        shutil.copy2(shared_session, run / "playwright_storage_state.json")

    env = os.environ.copy()
    lib_dirs = [BACKEND / p for p in ("usr/lib/x86_64-linux-gnu", "lib/x86_64-linux-gnu", "usr/lib", "lib")]
    extra = [str(d) for d in lib_dirs if d.is_dir()]
    if extra:
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = ":".join(extra) + (":" + existing if existing else "")
    command = [
        PYTHON,
        "-m",
        "utils.exporter_cli",
        "--filters-file",
        str(filter_file),
        "--data-dir",
        str(run),
    ]
    if payload.email and payload.password:
        credentials_file = run / "credentials.json"
        credentials_file.write_text(
            json.dumps({"email": payload.email, "password": payload.password}), encoding="utf-8"
        )
        command.extend(["--credentials-file", str(credentials_file)])

    process_log = run / "process.log"
    with process_log.open("a", encoding="utf-8") as log:
        log.write(f"[{now()}] Starting exporter subprocess: {' '.join(command)}\n")
        log.flush()
        process = subprocess.Popen(command, cwd=BACKEND, env=env, stdout=log, stderr=subprocess.STDOUT, text=True)
        log.write(f"[{now()}] Subprocess started with pid={process.pid}\n")
        log.flush()

    PROCESSES[sid] = process
    safe_execute(
        supabase.table("pipelines").update(
            {"status": "scraping", "error": None, "started_at": now(), "finished_at": None}
        ).eq("session_id", sid)
    )
    safe_execute(supabase.table("jobs").update({"status": "scraping"}).eq("id", sid))
    asyncio.create_task(monitor(sid, process))
    return {"message": "Adapt scraping started."}


@router.post("/api/pipeline/{sid}/cancel-scrape")
async def cancel(sid: int) -> dict[str, str]:
    get_job(sid)
    process = PROCESSES.pop(sid, None)
    if process and process.poll() is None:
        process.terminate()
    safe_execute(supabase.table("pipelines").update({"status": "inactive", "finished_at": now()}).eq("session_id", sid))
    safe_execute(supabase.table("jobs").update({"status": "inactive"}).eq("id", sid))
    return {"message": "Scrape cancelled; checkpoints are retained."}


@router.get("/api/pipeline/{sid}/stats")
async def get_stats(sid: int) -> dict[str, Any]:
    get_job(sid)
    return stats(sid)


@router.get("/api/pipeline/{sid}/logs")
async def get_logs(sid: int, lines: int = 100) -> dict[str, Any]:
    get_job(sid)
    return {
        "session_id": sid,
        "logs": tail_log(sid, lines=max(1, min(lines, 500))),
    }


@router.get("/api/pipeline/{sid}/preview")
async def preview(sid: int, limit: int = 50) -> dict[str, Any]:
    get_job(sid)
    path = output(sid)
    if not path.exists():
        return {"total_rows": 0, "columns": [], "rows": []}
    frame = pd.read_csv(path, nrows=min(max(limit, 1), 500), dtype=str).fillna("")
    return {"total_rows": count_rows(path), "columns": list(frame.columns), "rows": frame.to_dict(orient="records")}


@router.get("/api/pipeline/{sid}/download-master")
async def download(sid: int) -> FileResponse:
    path = output(sid)
    if not path.exists():
        raise HTTPException(404, "No completed CSV is available yet")
    return FileResponse(path, media_type="text/csv", filename=f"adapt_session_{sid}_master.csv")


@router.get("/api/pipeline/{sid}/download-raw")
async def download_raw(sid: int) -> FileResponse:
    path = raw_output(sid)
    if not path.exists():
        raise HTTPException(404, "No raw Adapt CSV is available yet")
    return FileResponse(path, media_type="text/csv", filename=f"adapt_session_{sid}_raw.csv")


@router.get("/api/pipeline/{sid}/download-emails")
async def download_emails(sid: int) -> FileResponse:
    path = email_candidates_output(sid)
    if not path.exists():
        raise HTTPException(404, "No email-candidate CSV is available yet")
    return FileResponse(path, media_type="text/csv", filename=f"adapt_session_{sid}_email_candidates.csv")


@router.post("/api/pipeline/{sid}/upload-verified")
async def upload_verified(sid: int, file: UploadFile = File(...)) -> dict[str, int | str]:
    get_job(sid)
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Upload the CSV exported by MailTester Ninja.")
    destination = verified_upload(sid)
    content = await file.read()
    if not content:
        raise HTTPException(400, "The verified CSV is empty.")
    destination.write_bytes(content)
    accepted, final_rows = VerifiedEmailFinalizer(
        email_candidates_output(sid), destination, final_output(sid), folder(sid) / "finalize.sqlite3"
    ).build()
    return {"message": "Verified emails matched and Salesforce CSV created.", "accepted_rows": accepted, "final_rows": final_rows}


@router.post("/api/pipeline/{sid}/finalize")
async def finalize(sid: int) -> dict[str, int | str]:
    get_job(sid)
    accepted, final_rows = VerifiedEmailFinalizer(
        email_candidates_output(sid), verified_upload(sid), final_output(sid), folder(sid) / "finalize.sqlite3"
    ).build()
    return {"message": "Salesforce CSV created.", "accepted_rows": accepted, "final_rows": final_rows}


@router.get("/api/pipeline/{sid}/download-final")
async def download_final(sid: int) -> FileResponse:
    path = final_output(sid)
    if not path.exists():
        raise HTTPException(404, "Upload a MailTester Ninja verified CSV first.")
    return FileResponse(path, media_type="text/csv", filename=f"adapt_session_{sid}_salesforce_upload.csv")
