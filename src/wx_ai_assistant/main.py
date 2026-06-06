import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from wx_ai_assistant.api.routes_admin import router as admin_router
from wx_ai_assistant.api.routes_listen import router as listen_router
from wx_ai_assistant.api.routes_messages import router as messages_router
from wx_ai_assistant.api.routes_send import router as send_router
from wx_ai_assistant.api.routes_strategy_analysis import router as strategy_analysis_router
from wx_ai_assistant.api.routes_system import router as system_router
from wx_ai_assistant.application.app_service import WechatApplicationService
from wx_ai_assistant.application.ai_turn import AiTurnParser
from wx_ai_assistant.application.automation_worker import WechatRuntimeWorker
from wx_ai_assistant.application.context_builder import ContextBuilder
from wx_ai_assistant.application.listener_manager import ListenerManager
from wx_ai_assistant.application.media_recognition import MediaRecognitionService
from wx_ai_assistant.application.message_ingestion import MessageIngestionService
from wx_ai_assistant.application.send_queue import SendQueue
from wx_ai_assistant.application.strategy_analysis import (
    DashScopeMultimodalTextEmbeddingProvider,
    OpenAICompatibleStrategyAnalysisAi,
    StrategyAnalysisAiConfig,
    StrategyEmbeddingConfig,
    StrategyAnalysisService,
)
from wx_ai_assistant.application.uia_worker import UiaCommandWorker
from wx_ai_assistant.core.config import load_settings
from wx_ai_assistant.core.response import ok
from wx_ai_assistant.identity.verifier import ConversationVerifier
from wx_ai_assistant.infrastructure.ai.factory import build_ai_gateway
from wx_ai_assistant.infrastructure.ai.vision_openai_compatible import (
    OpenAICompatibleVisionConfig,
    OpenAICompatibleVisionGateway,
)
from wx_ai_assistant.infrastructure.ai.speech_openai_compatible import (
    OpenAICompatibleSpeechConfig,
    OpenAICompatibleSpeechGateway,
)
from wx_ai_assistant.infrastructure.history.normalized_sqlite_history_reader import NormalizedSqliteHistoryReader
from wx_ai_assistant.infrastructure.persistence.strategy_analysis_store import SqliteStrategyKnowledgeStore
from wx_ai_assistant.infrastructure.persistence.sqlite_repository import SqliteRepository
from wx_ai_assistant.infrastructure.wechat.mock_driver import MockWechatDriver
from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(title="WeChat AI Assistant Core", version="0.1.0")

    repo = SqliteRepository(settings.db_path)
    repo.initialize_schema()
    strategy_knowledge_store = SqliteStrategyKnowledgeStore(settings.db_path)
    strategy_knowledge_store.initialize_schema()

    if settings.driver_mode == "uia":
        driver = UiaWechatDriver(settings.wechat_locators)
    else:
        driver = MockWechatDriver()

    history_reader = NormalizedSqliteHistoryReader(settings.history_db_path)
    ai = build_ai_gateway(settings, repository=repo)
    vision_gateway = None
    if settings.vision_ai_enabled:
        vision_gateway = OpenAICompatibleVisionGateway(
            OpenAICompatibleVisionConfig(
                base_url=settings.vision_ai_base_url,
                api_key=settings.vision_ai_api_key,
                model=settings.vision_ai_model,
                temperature=settings.vision_ai_temperature,
                max_tokens=settings.vision_ai_max_tokens,
                timeout_seconds=settings.vision_ai_timeout_seconds,
                system_prompt=settings.vision_ai_system_prompt,
                extra_body=settings.vision_ai_extra_body,
            )
        )
    speech_gateway = None
    if settings.speech_ai_enabled:
        speech_gateway = OpenAICompatibleSpeechGateway(
            OpenAICompatibleSpeechConfig(
                base_url=settings.speech_ai_base_url,
                api_key=settings.speech_ai_api_key,
                model=settings.speech_ai_model,
                language=settings.speech_ai_language,
                prompt=settings.speech_ai_prompt,
                timeout_seconds=settings.speech_ai_timeout_seconds,
            )
        )
    verifier = ConversationVerifier()
    media_recognition = MediaRecognitionService(
        vision_gateway=vision_gateway,
        enable_vision=settings.vision_ai_enabled,
        speech_gateway=speech_gateway,
        enable_speech=settings.speech_ai_enabled,
    )
    ingestion = MessageIngestionService(repo, driver, verifier, media_recognition)
    context_builder = ContextBuilder(repo, history_reader)
    driver_lock = threading.RLock()
    uia_worker = UiaCommandWorker(driver, verifier, driver_lock=driver_lock)

    # app_service is assigned after send_queue/listener to avoid circular callback issues.
    send_queue = SendQueue(repo, driver, verifier, on_sent=ingestion.insert_sent_message, driver_lock=driver_lock, uia_worker=uia_worker)
    app_service = WechatApplicationService(
        repo,
        driver,
        ingestion,
        context_builder,
        ai,
        send_queue,
        AiTurnParser(max_messages=settings.ai_max_messages_per_turn, strict_json=settings.ai_strict_turn_json),
        ai_turn_quiet_seconds=settings.ai_turn_quiet_seconds,
        ai_duplicate_guard_seconds=settings.ai_duplicate_guard_seconds,
        diagnostics_context_chars=settings.diagnostics_context_chars,
        driver_lock=driver_lock,
        async_ai=True,
        ai_worker_count=4,
        uia_worker=uia_worker,
        auto_send_enabled=settings.auto_send_enabled,
    )

    listener_manager = ListenerManager(
        repo=repo,
        driver=driver,
        poll_interval_seconds=settings.poll_interval_seconds,
        on_messages=app_service.handle_realtime_messages,
        on_baseline_messages=app_service.handle_baseline_messages,
        on_after_poll=app_service.flush_ready_ai_turns,
        driver_lock=driver_lock,
        auto_start_worker=False,
        uia_worker=uia_worker,
    )
    app_service.bind_listener_controls(
        listener_manager.start_target,
        listener_manager.stop_target,
        listener_manager.poll_once,
        listener_manager.snapshot,
    )
    runtime_worker = WechatRuntimeWorker(app_service, poll_interval_seconds=settings.poll_interval_seconds)
    app_service.bind_runtime_worker(runtime_worker.enqueue, runtime_worker.snapshot)
    strategy_analysis_service = StrategyAnalysisService(
        repo,
        strategy_knowledge_store,
        OpenAICompatibleStrategyAnalysisAi(
            StrategyAnalysisAiConfig(
                base_url=settings.ai_base_url,
                api_key=settings.ai_api_key,
                model=settings.ai_model,
                temperature=settings.ai_temperature,
                max_tokens=settings.ai_max_tokens,
                timeout_seconds=settings.ai_timeout_seconds,
                extra_body=settings.ai_extra_body,
            )
        ),
        upload_dir=settings.db_path.parent / "knowledge" / "uploads",
        embedding_provider=DashScopeMultimodalTextEmbeddingProvider(
            StrategyEmbeddingConfig(
                base_url=settings.embedding_base_url,
                api_key=settings.embedding_api_key,
                model=settings.embedding_model,
                dimensions=settings.embedding_dimensions,
                timeout_seconds=settings.embedding_timeout_seconds,
            )
        ),
    )

    # now connect failure callback
    send_queue.on_failed = lambda conversation_id, error: listener_manager.stop_target(conversation_id, error)
    uia_worker.start()
    send_queue.start()
    runtime_worker.start()
    runtime_worker.enqueue("initialize")

    app.state.settings = settings
    app.state.repo = repo
    app.state.driver = driver
    app.state.app_service = app_service
    app.state.listener_manager = listener_manager
    app.state.send_queue = send_queue
    app.state.runtime_worker = runtime_worker
    app.state.uia_worker = uia_worker
    app.state.strategy_analysis_service = strategy_analysis_service

    app.include_router(system_router)
    app.include_router(listen_router)
    app.include_router(messages_router)
    app.include_router(send_router)
    app.include_router(admin_router)
    app.include_router(strategy_analysis_router)
    web_dir = Path(__file__).resolve().parent / "web"
    if web_dir.exists():
        app.mount("/web", StaticFiles(directory=web_dir), name="web")

    @app.get("/health")
    def health():
        return ok({"status": "ok", "driver_mode": settings.driver_mode, "ai_mode": settings.ai_mode})

    @app.get("/")
    @app.get("/admin")
    def admin_page():
        return FileResponse(web_dir / "admin.html")

    @app.on_event("shutdown")
    def shutdown():
        runtime_worker.stop()
        app_service.shutdown()
        listener_manager.stop_worker()
        send_queue.stop()
        uia_worker.stop()

    return app


app = create_app()
