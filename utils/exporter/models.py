"""Small data objects shared by the exporter."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Manifest:
    completed_pages: list[int] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    is_complete: bool = False

    @property
    def next_page(self) -> int:
        return max(self.completed_pages, default=0) + 1


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """Values supplied by the UI and applied through the visible Adapt filter panel."""

    job_titles: tuple[str, ...] = ()
    industries: tuple[str, ...] = ()
    country: str = ""
    employee_counts: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, values: dict[str, object]) -> "SearchFilters":
        def strings(name: str) -> tuple[str, ...]:
            raw = values.get(name, [])
            return tuple(str(value).strip() for value in raw if str(value).strip()) if isinstance(raw, list) else ()

        return cls(
            job_titles=strings("job_titles"),
            industries=strings("industries"),
            country=str(values.get("country", "")).strip(),
            employee_counts=strings("employee_counts"),
        )


@dataclass(frozen=True, slots=True)
class AdaptCredentials:
    """Ephemeral credentials used only to establish the first browser session."""

    email: str = ""
    password: str = ""

    @classmethod
    def from_mapping(cls, values: dict[str, object]) -> "AdaptCredentials":
        return cls(email=str(values.get("email", "")).strip(), password=str(values.get("password", "")))
