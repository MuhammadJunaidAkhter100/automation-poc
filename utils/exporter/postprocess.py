"""Create MailTester-ready CSV files from Adapt's raw result export."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from urllib.parse import urlparse


REQUIRED_COLUMNS = (
    "First Name", "Last Name", "Job Title", "Company Name", "LinkedIn URL",
    "Domain", "Industry", "Email", "Headcount", "Location",
)
EMAIL_COLUMNS = tuple(f"Email Combination {number}" for number in range(1, 9))


class CsvPostProcessor:
    """Normalise raw Adapt rows without exposing locked data or fabricating source fields."""

    def __init__(self, raw_path: Path, cleaned_path: Path, candidates_path: Path) -> None:
        self.raw_path = raw_path
        self.cleaned_path = cleaned_path
        self.candidates_path = candidates_path

    def process(self) -> tuple[int, int]:
        if not self.raw_path.exists():
            raise FileNotFoundError(f"Raw Adapt export does not exist: {self.raw_path}")
        self.cleaned_path.parent.mkdir(parents=True, exist_ok=True)
        cleaned_count = 0
        candidate_count = 0
        with (
            self.raw_path.open("r", encoding="utf-8-sig", newline="") as source,
            self.cleaned_path.open("w", encoding="utf-8", newline="") as cleaned_file,
            self.candidates_path.open("w", encoding="utf-8", newline="") as candidates_file,
        ):
            cleaned_writer = csv.DictWriter(cleaned_file, fieldnames=REQUIRED_COLUMNS)
            candidates_writer = csv.DictWriter(candidates_file, fieldnames=(*REQUIRED_COLUMNS, *EMAIL_COLUMNS))
            cleaned_writer.writeheader()
            candidates_writer.writeheader()
            for source_row in csv.DictReader(source):
                row = self._normalise(source_row)
                cleaned_writer.writerow(row)
                candidates = self._email_candidates(row)
                candidates_writer.writerow({**row, **candidates})
                cleaned_count += 1
                candidate_count += sum(bool(value) for value in candidates.values())
        return cleaned_count, candidate_count

    def _normalise(self, source: dict[str, str]) -> dict[str, str]:
        lookup = {self._key(key): self._value(value) for key, value in source.items()}
        result = {column: self._lookup(lookup, column) for column in REQUIRED_COLUMNS}
        first, last = self._split_name(result["First Name"], result["Last Name"], self._lookup(lookup, "Name"))
        result["First Name"], result["Last Name"] = first, last
        result["Domain"] = self._domain(result["Domain"], result["LinkedIn URL"], self._lookup(lookup, "Company Website"))
        # Adapt's free tier masks email addresses (for example ******@example.com).
        # Preserve only a real address; candidates remain separate for verification.
        if not self._is_real_email(result["Email"]):
            result["Email"] = ""
        return result

    def _lookup(self, values: dict[str, str], column: str) -> str:
        aliases = {
            "First Name": ("first name", "firstname", "first"),
            "Last Name": ("last name", "lastname", "last"),
            "Job Title": ("job title", "title", "position"),
            "Company Name": ("company name", "company", "organization"),
            "LinkedIn URL": ("linkedin url", "linkedin", "linkedin profile"),
            "Domain": ("domain", "company domain", "website"),
            "Company Website": ("company website", "website", "company url"),
            "Industry": ("industry",),
            "Email": ("email", "email address"),
            "Headcount": ("headcount", "employee count", "employees", "company size"),
            "Location": ("location", "country", "city"),
            "Name": ("name", "contact name"),
        }
        for alias in aliases[column]:
            value = values.get(self._key(alias), "")
            if value:
                return value
        return ""

    @staticmethod
    def _split_name(first: str, last: str, full: str) -> tuple[str, str]:
        if first or last:
            return first, last
        parts = re.split(r"\s+", full.strip()) if full else []
        return (parts[0] if parts else "", " ".join(parts[1:]))

    @staticmethod
    def _domain(domain: str, linkedin: str, website: str) -> str:
        value = domain or website
        if not value:
            return ""
        if "@" in value:
            value = value.rsplit("@", 1)[1]
        if "://" in value:
            value = urlparse(value).hostname or ""
        return value.lower().removeprefix("www.").strip("/ ")

    @staticmethod
    def _email_candidates(row: dict[str, str]) -> dict[str, str]:
        first = CsvPostProcessor._email_part(row["First Name"])
        last = CsvPostProcessor._email_part(row["Last Name"])
        domain = CsvPostProcessor._domain(row["Domain"], "", "")
        if not first or not last or not domain:
            return {column: "" for column in EMAIL_COLUMNS}
        values = (
            f"{first}.{last}@{domain}", f"{first}{last}@{domain}",
            f"{first[0]}{last}@{domain}", f"{first}.{last[0]}@{domain}",
            f"{last}.{first}@{domain}", f"{last}{first}@{domain}",
            f"{first[0]}.{last}@{domain}", f"{first}{last[0]}@{domain}",
        )
        return dict(zip(EMAIL_COLUMNS, values, strict=True))

    @staticmethod
    def _email_part(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.lower())

    @staticmethod
    def _is_real_email(value: str) -> bool:
        return bool(re.fullmatch(r"[^\s*@]+@[^\s*@]+\.[^\s*@]+", value))

    @staticmethod
    def _key(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    @staticmethod
    def _value(value: str | None) -> str:
        return re.sub(r"\s+", " ", value or "").strip()
