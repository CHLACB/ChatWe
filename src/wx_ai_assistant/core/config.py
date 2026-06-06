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
    ai_extensions_path: Path
    ai_proactive_mode: str
    ai_max_messages_per_turn: int
    ai_strict_turn_json: bool
    ai_turn_quiet_seconds: float
    ai_duplicate_guard_seconds: float
    diagnostics_context_chars: int
    ai_extra_body: str
    auto_send_enabled: bool
    embedding_base_url: str
    embedding_api_key: str
    embedding_model: str
    embedding_dimensions: int
    embedding_timeout_seconds: float
    langgraph_nodes_path: Path
    history_mode: str
    history_db_path: Path
    wechat_locators: Path
    vision_ai_enabled: bool = False
    vision_ai_base_url: str = ""
    vision_ai_api_key: str = ""
    vision_ai_model: str = "qwen3-vl-plus"
    vision_ai_temperature: float = 0.1
    vision_ai_max_tokens: int = 300
    vision_ai_timeout_seconds: float = 30
    vision_ai_system_prompt: str = (
        "你是微信图片和表情包识别器。只描述图片/表情包里能看见的内容、文字和表达的情绪。不要生成聊天回复。"
    )
    vision_ai_extra_body: str = ""
    speech_ai_enabled: bool = False
    speech_ai_base_url: str = ""
    speech_ai_api_key: str = ""
    speech_ai_model: str = "gpt-4o-mini-transcribe"
    speech_ai_language: str = "zh"
    speech_ai_prompt: str = "这是一条微信语音消息，请转写为简体中文。"
    speech_ai_timeout_seconds: float = 30


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
        ai_extensions_path=Path(os.getenv("APP_AI_EXTENSIONS_PATH", "./config/prompts/extensions.local.json")),
        ai_proactive_mode=os.getenv("APP_AI_PROACTIVE_MODE", "off").strip().lower(),
        ai_max_messages_per_turn=int(os.getenv("APP_AI_MAX_MESSAGES_PER_TURN", "3")),
        ai_strict_turn_json=os.getenv("APP_AI_STRICT_TURN_JSON", "true").strip().lower() in {"1", "true", "yes", "on"},
        ai_turn_quiet_seconds=float(os.getenv("APP_AI_TURN_QUIET_SECONDS", "5.0")),
        ai_duplicate_guard_seconds=float(os.getenv("APP_AI_DUPLICATE_GUARD_SECONDS", "120.0")),
        diagnostics_context_chars=int(os.getenv("APP_DIAGNOSTICS_CONTEXT_CHARS", "1200")),
        ai_extra_body=os.getenv("APP_AI_EXTRA_BODY", "").strip(),
        auto_send_enabled=os.getenv("APP_AUTO_SEND_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
        embedding_base_url=os.getenv(
            "APP_EMBEDDING_BASE_URL",
            "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding",
        ).strip(),
        embedding_api_key=(
            os.getenv("APP_EMBEDDING_API_KEY")
            or os.getenv("DASHSCOPE_API_KEY")
            or os.getenv("APP_AI_API_KEY", "")
        ).strip(),
        embedding_model=os.getenv("APP_EMBEDDING_MODEL", "tongyi-embedding-vision-flash-2026-03-06").strip(),
        embedding_dimensions=int(os.getenv("APP_EMBEDDING_DIMENSIONS", "768")),
        embedding_timeout_seconds=float(os.getenv("APP_EMBEDDING_TIMEOUT_SECONDS", "30")),
        vision_ai_enabled=os.getenv("APP_VISION_AI_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
        vision_ai_base_url=os.getenv("APP_VISION_AI_BASE_URL", os.getenv("APP_AI_BASE_URL", "")).strip(),
        vision_ai_api_key=(os.getenv("APP_VISION_AI_API_KEY") or os.getenv("APP_AI_API_KEY", "")).strip(),
        vision_ai_model=os.getenv("APP_VISION_AI_MODEL", "qwen3-vl-plus").strip(),
        vision_ai_temperature=float(os.getenv("APP_VISION_AI_TEMPERATURE", "0.1")),
        vision_ai_max_tokens=int(os.getenv("APP_VISION_AI_MAX_TOKENS", "300")),
        vision_ai_timeout_seconds=float(os.getenv("APP_VISION_AI_TIMEOUT_SECONDS", "30")),
        vision_ai_system_prompt=os.getenv(
            "APP_VISION_AI_SYSTEM_PROMPT",
            "你是微信图片和表情包识别器。只描述图片/表情包里能看见的内容、文字和表达的情绪。不要生成聊天回复。",
        ).strip(),
        vision_ai_extra_body=os.getenv("APP_VISION_AI_EXTRA_BODY", "").strip(),
        speech_ai_enabled=os.getenv("APP_SPEECH_AI_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
        speech_ai_base_url=os.getenv("APP_SPEECH_AI_BASE_URL", os.getenv("APP_AI_BASE_URL", "")).strip(),
        speech_ai_api_key=(os.getenv("APP_SPEECH_AI_API_KEY") or os.getenv("APP_AI_API_KEY", "")).strip(),
        speech_ai_model=os.getenv("APP_SPEECH_AI_MODEL", "gpt-4o-mini-transcribe").strip(),
        speech_ai_language=os.getenv("APP_SPEECH_AI_LANGUAGE", "zh").strip(),
        speech_ai_prompt=os.getenv("APP_SPEECH_AI_PROMPT", "这是一条微信语音消息，请转写为简体中文。").strip(),
        speech_ai_timeout_seconds=float(os.getenv("APP_SPEECH_AI_TIMEOUT_SECONDS", "30")),
        langgraph_nodes_path=Path(os.getenv("APP_LANGGRAPH_NODES_PATH", "./config/langgraph_nodes.local.json")),
        history_mode=os.getenv("APP_HISTORY_MODE", "normalized_sqlite").strip().lower(),
        history_db_path=Path(os.getenv("APP_HISTORY_DB_PATH", "./data/history_normalized.sqlite3")),
        wechat_locators=Path(os.getenv("APP_WECHAT_LOCATORS", "./config/wechat_locators.local.json")),
    )
