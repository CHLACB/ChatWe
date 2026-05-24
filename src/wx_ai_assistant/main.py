import threading

from fastapi import FastAPI

from wx_ai_assistant.api.routes_listen import router as listen_router
from wx_ai_assistant.api.routes_messages import router as messages_router
from wx_ai_assistant.api.routes_send import router as send_router
from wx_ai_assistant.api.routes_system import router as system_router
from wx_ai_assistant.application.app_service import WechatApplicationService
from wx_ai_assistant.application.ai_turn import AiTurnParser
from wx_ai_assistant.application.context_builder import ContextBuilder
from wx_ai_assistant.application.listener_manager import ListenerManager
from wx_ai_assistant.application.message_ingestion import MessageIngestionService
from wx_ai_assistant.application.send_queue import SendQueue
from wx_ai_assistant.core.config import load_settings
from wx_ai_assistant.core.response import ok
from wx_ai_assistant.identity.verifier import ConversationVerifier
from wx_ai_assistant.infrastructure.ai.factory import build_ai_gateway
from wx_ai_assistant.infrastructure.history.normalized_sqlite_history_reader import NormalizedSqliteHistoryReader
from wx_ai_assistant.infrastructure.persistence.sqlite_repository import SqliteRepository
from wx_ai_assistant.infrastructure.wechat.mock_driver import MockWechatDriver
from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(title="WeChat AI Assistant Core", version="0.1.0")

    repo = SqliteRepository(settings.db_path)
    repo.initialize_schema()

    if settings.driver_mode == "uia":
        driver = UiaWechatDriver(settings.wechat_locators)
    else:
        driver = MockWechatDriver()

    history_reader = NormalizedSqliteHistoryReader(settings.history_db_path)
    ai = build_ai_gateway(settings)
    verifier = ConversationVerifier()
    ingestion = MessageIngestionService(repo, driver, verifier)
    context_builder = ContextBuilder(repo, history_reader)
    driver_lock = threading.RLock()

    # app_service is assigned after send_queue/listener to avoid circular callback issues.
    send_queue = SendQueue(repo, driver, verifier, on_sent=ingestion.insert_sent_message, driver_lock=driver_lock)
    app_service = WechatApplicationService(
        repo,
        driver,
        ingestion,
        context_builder,
        ai,
        send_queue,
        AiTurnParser(max_messages=settings.ai_max_messages_per_turn, strict_json=settings.ai_strict_turn_json),
    )

    listener_manager = ListenerManager(
        repo=repo,
        driver=driver,
        poll_interval_seconds=settings.poll_interval_seconds,
        on_messages=app_service.handle_realtime_messages,
        on_baseline_messages=app_service.handle_baseline_messages,
        driver_lock=driver_lock,
    )
    app_service.bind_listener_controls(listener_manager.start_target, listener_manager.stop_target, listener_manager.poll_once)

    # now connect failure callback
    send_queue.on_failed = lambda conversation_id, error: listener_manager.stop_target(conversation_id, error)
    send_queue.start()

    app.state.settings = settings
    app.state.repo = repo
    app.state.driver = driver
    app.state.app_service = app_service
    app.state.listener_manager = listener_manager
    app.state.send_queue = send_queue

    app.include_router(system_router)
    app.include_router(listen_router)
    app.include_router(messages_router)
    app.include_router(send_router)

    @app.get("/health")
    def health():
        return ok({"status": "ok", "driver_mode": settings.driver_mode, "ai_mode": settings.ai_mode})

    @app.on_event("shutdown")
    def shutdown():
        listener_manager.stop_worker()
        send_queue.stop()

    return app


app = create_app()
