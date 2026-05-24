from __future__ import annotations

import argparse
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wx_ai_assistant.application.app_service import WechatApplicationService  # noqa: E402
from wx_ai_assistant.application.ai_turn import AiTurnParser  # noqa: E402
from wx_ai_assistant.application.context_builder import ContextBuilder  # noqa: E402
from wx_ai_assistant.application.listener_manager import ListenerManager  # noqa: E402
from wx_ai_assistant.application.message_ingestion import MessageIngestionService  # noqa: E402
from wx_ai_assistant.application.send_queue import SendQueue  # noqa: E402
from wx_ai_assistant.core.config import load_settings  # noqa: E402
from wx_ai_assistant.domain.enums import ConversationType, ListenStatus, SendTaskStatus  # noqa: E402
from wx_ai_assistant.identity.verifier import ConversationVerifier  # noqa: E402
from wx_ai_assistant.infrastructure.ai.factory import build_ai_gateway  # noqa: E402
from wx_ai_assistant.infrastructure.history.normalized_sqlite_history_reader import NormalizedSqliteHistoryReader  # noqa: E402
from wx_ai_assistant.infrastructure.persistence.sqlite_repository import SqliteRepository  # noqa: E402
from wx_ai_assistant.infrastructure.wechat.uia_driver import UiaWechatDriver  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run continuous UIA friend listener and serial send queue.")
    parser.add_argument("targets", nargs="+", help="好友私聊名称，可传多个，例如 AAxc 文件传输助手")
    parser.add_argument("--interval", type=float, default=None, help="监听轮询间隔秒数，默认读取 APP_POLL_INTERVAL_SECONDS")
    parser.add_argument("--status-interval", type=float, default=10.0, help="状态输出间隔秒数")
    parser.add_argument("--ai-mode", default=None, help="覆盖 APP_AI_MODE，例如 echo/openai_compatible")
    parser.add_argument("--max-seconds", type=float, default=0.0, help="调试用最大运行秒数；默认 0 表示一直运行")
    parser.add_argument("--retry-stopped", action=argparse.BooleanOptionalAction, default=True, help="临时 UIA 切换/标题读取失败时自动重试")
    parser.add_argument("--retry-interval", type=float, default=8.0, help="自动重试 stopped 监听对象的最小间隔秒数")
    parser.add_argument("--resume-pending", action="store_true", help="保留上次遗留的 pending/sending 发送任务；默认启动时标记失败避免旧回复补发")
    parser.add_argument("--debug-turns", action="store_true", help="状态输出时打印最近监听快照和最近 AI 输入/输出摘要")
    args = parser.parse_args()

    settings = load_settings()
    poll_interval = args.interval if args.interval is not None else settings.poll_interval_seconds

    repo = SqliteRepository(settings.db_path)
    repo.initialize_schema()
    if not args.resume_pending:
        cleared = repo.fail_unfinished_send_tasks("启动常驻监听时清理未完成旧任务；如需恢复旧任务请使用 --resume-pending")
        if cleared:
            print(f"startup_cleared_unfinished_send_tasks={cleared}", flush=True)
    driver = UiaWechatDriver(settings.wechat_locators)
    status = driver.initialize()
    print(status, flush=True)
    if not status.ok:
        return 2

    verifier = ConversationVerifier()
    ingestion = MessageIngestionService(repo, driver, verifier)
    context_builder = ContextBuilder(repo, NormalizedSqliteHistoryReader(settings.history_db_path))
    driver_lock = threading.RLock()
    send_queue = SendQueue(repo, driver, verifier, on_sent=ingestion.insert_sent_message, driver_lock=driver_lock)
    service = WechatApplicationService(
        repo,
        driver,
        ingestion,
        context_builder,
        build_ai_gateway(settings, force_mode=args.ai_mode),
        send_queue,
        AiTurnParser(max_messages=settings.ai_max_messages_per_turn, strict_json=settings.ai_strict_turn_json),
        ai_turn_quiet_seconds=settings.ai_turn_quiet_seconds,
        ai_duplicate_guard_seconds=settings.ai_duplicate_guard_seconds,
        diagnostics_context_chars=settings.diagnostics_context_chars,
    )
    listener = ListenerManager(
        repo=repo,
        driver=driver,
        poll_interval_seconds=poll_interval,
        on_messages=service.handle_realtime_messages,
        on_baseline_messages=service.handle_baseline_messages,
        on_after_poll=service.flush_ready_ai_turns,
        driver_lock=driver_lock,
    )
    service.bind_listener_controls(listener.start_target, listener.stop_target, listener.poll_once)
    send_queue.on_failed = lambda conversation_id, error: listener.stop_target(conversation_id, error)

    for target_name in args.targets:
        target = service.add_listen_target(target_name, ConversationType.FRIEND, remark_name=target_name, local_id=target_name)
        service.start_listen_target(target.conversation.conversation_id)
        print(f"listening target={target_name!r} conversation_id={target.conversation.conversation_id}", flush=True)

    send_queue.start()
    print(
        "running=true "
        f"ai_mode={args.ai_mode or settings.ai_mode} "
        f"model={settings.ai_model} "
        f"api_key_configured={bool(settings.ai_api_key)} "
        f"turn_quiet_seconds={settings.ai_turn_quiet_seconds} "
        f"duplicate_guard_seconds={settings.ai_duplicate_guard_seconds} "
        f"db={settings.db_path}",
        flush=True,
    )
    print("按 Ctrl+C 停止。首次轮询只建立基线，不会回复旧消息。", flush=True)

    exit_code = 0
    last_status_at = 0.0
    last_retry_at = 0.0
    deadline = time.time() + args.max_seconds if args.max_seconds > 0 else None
    try:
        while True:
            now = time.time()
            if deadline is not None and now >= deadline:
                print(f"stopping=max_seconds elapsed={args.max_seconds}", flush=True)
                break
            if now - last_status_at >= args.status_interval:
                last_status_at = now
                _print_status(repo, driver, service, args.debug_turns)
                targets = repo.list_listen_targets()
                if targets and all(target.status != ListenStatus.LISTENING for target in targets):
                    if args.retry_stopped and now - last_retry_at >= args.retry_interval:
                        restarted = _restart_transient_stopped_targets(repo, listener)
                        last_retry_at = now
                        if restarted:
                            print(f"retry_restarted_targets={restarted}", flush=True)
                            continue
                    print("all_targets_stopped=true", flush=True)
                    exit_code = 3
                    break
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("stopping=keyboard_interrupt", flush=True)
    finally:
        listener.stop_worker()
        send_queue.stop()
    return exit_code


def _print_status(repo: SqliteRepository, driver: UiaWechatDriver, service: WechatApplicationService | None = None, debug_turns: bool = False) -> None:
    try:
        current = driver.get_current_conversation()
        current_name = current.display_name if current else None
    except Exception:
        current_name = None
    tasks = repo.list_send_tasks(limit=50)
    pending = sum(1 for task in tasks if task.status == SendTaskStatus.PENDING)
    sending = sum(1 for task in tasks if task.status == SendTaskStatus.SENDING)
    failed = sum(1 for task in tasks if task.status == SendTaskStatus.FAILED)
    success = sum(1 for task in tasks if task.status == SendTaskStatus.SUCCESS)
    print(
        f"status current={current_name!r} tasks=pending:{pending},sending:{sending},success:{success},failed:{failed}",
        flush=True,
    )
    for target in repo.list_listen_targets():
        message_count = len(repo.list_recent_messages(target.conversation.conversation_id, 500))
        print(
            "target "
            f"name={target.conversation.display_name!r} "
            f"status={target.status.value} "
            f"messages={message_count} "
            f"error={target.last_error!r}",
            flush=True,
        )
    if debug_turns and service is not None:
        snapshot = service.diagnostics_snapshot()
        pending = snapshot.get("pending_ai_turns", [])
        print(f"debug pending_ai_turns={len(pending)}", flush=True)
        if pending:
            latest_pending = pending[-1]
            print(
                "debug pending "
                f"target={latest_pending.get('display_name')!r} "
                f"age={latest_pending.get('age_seconds')} "
                f"trigger={latest_pending.get('trigger_content')!r}",
                flush=True,
            )
        visible = snapshot.get("last_visible_snapshots", [])
        if visible:
            latest_visible = visible[-1]
            tail = latest_visible.get("messages", [])[-5:]
            print(f"debug visible_tail={tail!r}", flush=True)
        turns = snapshot.get("last_ai_turns", [])
        if turns:
            latest_turn = turns[-1]
            raw = str(latest_turn.get("raw_reply", ""))
            context_tail = str(latest_turn.get("context_tail", ""))
            print(
                "debug last_ai_turn "
                f"target={latest_turn.get('display_name')!r} "
                f"trigger={latest_turn.get('trigger_content')!r} "
                f"parsed={latest_turn.get('parsed_messages')!r} "
                f"raw={raw[:500]!r} "
                f"context_tail={context_tail[-500:]!r}",
                flush=True,
            )


def _restart_transient_stopped_targets(repo: SqliteRepository, listener: ListenerManager) -> int:
    restarted = 0
    for target in repo.list_listen_targets():
        if target.status == ListenStatus.LISTENING:
            continue
        if not _is_transient_listener_error(target.last_error):
            continue
        listener.start_target(target.conversation.conversation_id)
        restarted += 1
    return restarted


def _is_transient_listener_error(error: str | None) -> bool:
    if not error:
        return False
    transient_markers = [
        "切换会话后无法读取当前聊天标题",
        "无法读取当前会话身份",
        "Ctrl+F",
        "焦点未落到左侧搜索框",
        "未找到 chat_title 控件",
        "未找到 message_list 控件",
    ]
    return any(marker in error for marker in transient_markers)


if __name__ == "__main__":
    raise SystemExit(main())
