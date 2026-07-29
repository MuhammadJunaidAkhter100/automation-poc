from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class JobInput(BaseModel):
    name: str
    location: str
    status: str = "inactive"
    description: str | None = None
    annual_budget: str | None = None
    primary_skills: str | None = None
    target_keywords: str | None = None
    industry: str | None = None
    min_experience: str | None = None
    connection_degree: str | None = None
    employee_count: str | None = None


class Filters(BaseModel):
    job_titles: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    country: str = ""
    employee_counts: list[str] = Field(default_factory=list)


class ScrapeInput(BaseModel):
    email: str = ""
    password: str = ""
    filters: Filters | None = None


class LoginInput(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class JobRecord(JobInput):
    id: int
    created_at: str
    model_config = ConfigDict(from_attributes=True)
