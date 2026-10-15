from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str = "postgresql+psycopg://kr:kr@localhost:5432/kr"
    polygon_api_key: str = ""
    polygon_base_url: str = "https://api.polygon.io"
    polygon_calls_per_minute: int = 5
    app_user_id: str = "analyst"
    universe_file: Path = REPO_ROOT / "universe" / "sp100.csv"
    seed_dir: Path = REPO_ROOT / "seed"
    history_years: int = 2
    gap_fill_cooldown_seconds: int = 900


settings = Settings()
