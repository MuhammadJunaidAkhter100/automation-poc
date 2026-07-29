"""Match a verified-email export back to Adapt candidates for CRM upload."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from pathlib import Path


SALESFORCE_COLUMNS = (
    "First Name", "Last Name", "Title", "Company", "LinkedIn URL", "Domain",
    "Industry", "Email", "Headcount", "Location",
)


class VerifiedEmailFinalizer:
    """Accept verified addresses only and emit deduplicated Salesforce CSV rows."""

    def __init__(self, candidates_path: Path, verified_path: Path, output_path: Path, database_path: Path) -> None:
        self.candidates_path = candidates_path
        self.verified_path = verified_path
        self.output_path = output_path
        self.database_path = database_path

    def build(self) -> tuple[int, int]:
        if not self.candidates_path.exists():
            raise FileNotFoundError("Email candidates CSV does not exist. Complete the Adapt export first.")
        if not self.verified_path.exists():
            raise FileNotFoundError("Upload the MailTester Ninja verified CSV before finalizing.")
        self.database_path.unlink(missing_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.execute("CREATE TABLE candidate_lookup (email TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        connection.execute("CREATE TABLE final_records (dedupe_key TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        try:
            self._index_candidates(connection)
            accepted, inserted = self._match_verified(connection)
            connection.commit()
            self._write_output(connection)
            return accepted, inserted
        finally:
            connection.close()
            self.database_path.unlink(missing_ok=True)

    def _index_candidates(self, connection: sqlite3.Connection) -> None:
        with self.candidates_path.open("r", encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source):
                payload = json.dumps(row, ensure_ascii=False)
                emails = [row.get("Email", ""), *(row.get(f"Email Combination {number}", "") for number in range(1, 9))]
                for email in emails:
                    normal = self._email(email)
                    if normal:
                        connection.execute("INSERT OR IGNORE INTO candidate_lookup (email, payload) VALUES (?, ?)", (normal, payload))

    def _match_verified(self, connection: sqlite3.Connection) -> tuple[int, int]:
        accepted = inserted = 0
        with self.verified_path.open("r", encoding="utf-8-sig", newline="") as source:
            for verified in csv.DictReader(source):
                if not self._is_accepted(verified):
                    continue
                email = self._email(self._find_email(verified))
                if not email:
                    continue
                accepted += 1
                match = connection.execute("SELECT payload FROM candidate_lookup WHERE email=?", (email,)).fetchone()
                if not match:
                    continue
                candidate = json.loads(match[0])
                record = self._salesforce_record(candidate, email)
                key = self._dedupe_key(record)
                cursor = connection.execute("INSERT OR IGNORE INTO final_records (dedupe_key, payload) VALUES (?, ?)", (key, json.dumps(record, ensure_ascii=False)))
                inserted += cursor.rowcount
        return accepted, inserted

    def _write_output(self, connection: sqlite3.Connection) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("w", encoding="utf-8", newline="") as destination:
            writer = csv.DictWriter(destination, fieldnames=SALESFORCE_COLUMNS)
            writer.writeheader()
            for (payload,) in connection.execute("SELECT payload FROM final_records ORDER BY rowid"):
                writer.writerow(json.loads(payload))

    @staticmethod
    def _salesforce_record(candidate: dict[str, str], verified_email: str) -> dict[str, str]:
        return {"First Name": candidate.get("First Name", "").strip(), "Last Name": candidate.get("Last Name", "").strip(), "Title": candidate.get("Job Title", "").strip(), "Company": candidate.get("Company Name", "").strip(), "LinkedIn URL": candidate.get("LinkedIn URL", "").strip(), "Domain": candidate.get("Domain", "").strip(), "Industry": candidate.get("Industry", "").strip(), "Email": verified_email, "Headcount": candidate.get("Headcount", "").strip(), "Location": candidate.get("Location", "").strip()}

    @staticmethod
    def _find_email(row: dict[str, str]) -> str:
        aliases = {"email", "email address", "verified email", "mail"}
        for name, value in row.items():
            if re.sub(r"[^a-z]+", " ", name.lower()).strip() in aliases and value:
                return value
        for value in row.values():
            if VerifiedEmailFinalizer._email(value):
                return value
        return ""

    @staticmethod
    def _is_accepted(row: dict[str, str]) -> bool:
        status_fields = {"status", "result", "verification status", "email status", "state"}
        status = ""
        for name, value in row.items():
            if re.sub(r"[^a-z]+", " ", name.lower()).strip() in status_fields:
                status = value.lower().strip()
                break
        if not status:
            return True
        return any(re.search(rf"\b{value}\b", status) for value in ("accepted", "valid", "verified", "deliverable", "safe", "ok"))

    @staticmethod
    def _email(value: str | None) -> str:
        candidate = (value or "").strip().lower()
        return candidate if re.fullmatch(r"[^\s*@]+@[^\s*@]+\.[^\s*@]+", candidate) else ""

    @staticmethod
    def _dedupe_key(row: dict[str, str]) -> str:
        linkedin = row["LinkedIn URL"].lower()
        return f"linkedin:{linkedin}" if linkedin else f"email:{row['Email'].lower()}"
