from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    driver_mode: str
    db_path: Path
    poll_interval_seconds: float
    ai_mode: str
    history_mode: str
    history_db_path: Path
    wechat_locators: Path


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        driver_mode=os.getenv("APP_DRIVER_MODE", "mock").strip().lower(),
        db_path=Path(os.getenv("APP_DB_PATH", "./data/app.sqlite3")),
        poll_interval_seconds=float(os.getenv("APP_POLL_INTERVAL_SECONDS", "1.0")),
        ai_mode=os.getenv("APP_AI_MODE", "dummy").strip().lower(),
        history_mode=os.getenv("APP_HISTORY_MODE", "normalized_sqlite").strip().lower(),
        history_db_path=Path(os.getenv("APP_HISTORY_DB_PATH", "./data/history_normalized.sqlite3")),
        wechat_locators=Path(os.getenv("APP_WECHAT_LOCATORS", "./config/wechat_locators.local.json")),
    )
