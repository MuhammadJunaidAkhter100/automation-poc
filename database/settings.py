from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    supabase_url: str
    supabase_key: str
    adapt_search_url: str = ""
    exporter_python: str | None = None
    backend_data_dir: Path = Path("data")
    cors_origins: list[str] = [
        "https://data-scraping-mhuzaifabilal576-9348s-projects.vercel.app",
        "https://data-scraping-wine.vercel.app",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
