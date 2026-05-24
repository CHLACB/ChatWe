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
    ai_config: Path
    ai_base_url: str
    ai_api_key: str
    ai_model: str
    ai_temperature: float
    ai_max_tokens: int
    ai_timeout_seconds: float
    ai_system_prompt: str
    ai_core_prompt_path: Path
    ai_prompt_path: Path
    ai_style_path: Path
    ai_proactive_mode: str
    ai_max_messages_per_turn: int
    ai_strict_turn_json: bool
    ai_turn_quiet_seconds: float
    ai_duplicate_guard_seconds: float
    diagnostics_context_chars: int
    ai_extra_body: str
    contact_policies_path: Path
    history_mode: str
    history_db_path: Path
    wechat_locators: Path


def load_settings() -> Settings:
    load_dotenv()
    ai_config = Path(os.getenv("APP_AI_CONFIG", "./config/ai.local.env"))
    if ai_config.exists():
        load_dotenv(ai_config, override=False)
    return Settings(
        driver_mode=os.getenv("APP_DRIVER_MODE", "mock").strip().lower(),
        db_path=Path(os.getenv("APP_DB_PATH", "./data/app.sqlite3")),
        poll_interval_seconds=float(os.getenv("APP_POLL_INTERVAL_SECONDS", "1.0")),
        ai_mode=os.getenv("APP_AI_MODE", "dummy").strip().lower(),
        ai_config=ai_config,
        ai_base_url=os.getenv("APP_AI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").strip(),
        ai_api_key=os.getenv("APP_AI_API_KEY", "").strip(),
        ai_model=os.getenv("APP_AI_MODEL", "deepseek-v4-flash").strip(),
        ai_temperature=float(os.getenv("APP_AI_TEMPERATURE", "0.3")),
        ai_max_tokens=int(os.getenv("APP_AI_MAX_TOKENS", "800")),
        ai_timeout_seconds=float(os.getenv("APP_AI_TIMEOUT_SECONDS", "30")),
        ai_system_prompt=os.getenv(
            "APP_AI_SYSTEM_PROMPT",
            "你是一个微信私聊助手。请只输出 JSON，不要输出分析过程。",
        ).strip(),
        ai_core_prompt_path=Path(os.getenv("APP_AI_CORE_PROMPT_PATH", "./config/prompts/system.core.md")),
        ai_prompt_path=Path(os.getenv("APP_AI_PROMPT_PATH", "./config/prompts/system.wechat_turn.md")),
        ai_style_path=Path(os.getenv("APP_AI_STYLE_PATH", "./config/prompts/styles/natural_short.md")),
        ai_proactive_mode=os.getenv("APP_AI_PROACTIVE_MODE", "off").strip().lower(),
        ai_max_messages_per_turn=int(os.getenv("APP_AI_MAX_MESSAGES_PER_TURN", "3")),
        ai_strict_turn_json=os.getenv("APP_AI_STRICT_TURN_JSON", "true").strip().lower() in {"1", "true", "yes", "on"},
        ai_turn_quiet_seconds=float(os.getenv("APP_AI_TURN_QUIET_SECONDS", "5.0")),
        ai_duplicate_guard_seconds=float(os.getenv("APP_AI_DUPLICATE_GUARD_SECONDS", "120.0")),
        diagnostics_context_chars=int(os.getenv("APP_DIAGNOSTICS_CONTEXT_CHARS", "1200")),
        ai_extra_body=os.getenv("APP_AI_EXTRA_BODY", "").strip(),
        contact_policies_path=Path(os.getenv("APP_CONTACT_POLICIES_PATH", "./config/contact_policies.local.json")),
        history_mode=os.getenv("APP_HISTORY_MODE", "normalized_sqlite").strip().lower(),
        history_db_path=Path(os.getenv("APP_HISTORY_DB_PATH", "./data/history_normalized.sqlite3")),
        wechat_locators=Path(os.getenv("APP_WECHAT_LOCATORS", "./config/wechat_locators.local.json")),
    )
