from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Optional

from backend.services.config import get_config_service
from backend.utils.tg_session import get_account_profile

try:
    import httpx
except ImportError:  # pragma: no cover - exercised via monkeypatch in tests
    class _HttpxStub:
        class AsyncClient:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("httpx is not installed")

    httpx = _HttpxStub()  # type: ignore[assignment]


logger = logging.getLogger("backend.notifications")
DEFAULT_NOTIFICATION_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class NotificationTarget:
    channel: str
    bot_token: Optional[str]
    chat_id: Optional[str]


def _clean_optional(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _truncate_text(text: str, limit: int = 3500) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _format_time(value: Optional[datetime]) -> str:
    if not isinstance(value, datetime):
        value = datetime.utcnow()
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _coerce_summary(summary: Optional[str], output: Optional[str], default: str) -> str:
    normalized_summary = _clean_optional(summary)
    if normalized_summary:
        return normalized_summary

    if isinstance(output, str):
        for line in output.splitlines():
            line = line.strip()
            if line:
                return line[:200] if len(line) <= 200 else line[:197] + "..."

    return default


def _recent_message_lines(
    message_events: Optional[list[dict[str, Any]]], max_items: int = 3
) -> list[str]:
    if not isinstance(message_events, list):
        return []

    selected = message_events[-max_items:]
    lines: list[str] = []
    for event in selected:
        if not isinstance(event, dict):
            continue
        summary = _clean_optional(event.get("summary"))
        if not summary:
            summary = _clean_optional(event.get("text")) or _clean_optional(
                event.get("caption")
            )
        if not summary:
            continue
        if len(summary) > 200:
            summary = summary[:197] + "..."
        lines.append(f"{len(lines) + 1}. {summary}")
    return lines


def dispatch_notification(
    awaitable: Awaitable[Any],
    *,
    logger: logging.Logger,
    description: str,
    timeout: float = DEFAULT_NOTIFICATION_TIMEOUT_SECONDS,
) -> None:
    async def runner() -> None:
        try:
            await asyncio.wait_for(awaitable, timeout=timeout)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception(description)

    task = asyncio.create_task(runner())

    def consume_result(done_task: asyncio.Task[None]) -> None:
        if done_task.cancelled():
            return
        try:
            done_task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("%s", description)

    task.add_done_callback(consume_result)


def build_regular_task_message(
    *,
    task_name: str,
    account_name: str,
    status: str,
    finished_at: Optional[datetime],
    summary: Optional[str],
    output: Optional[str] = None,
) -> str:
    success = str(status or "").lower() == "success"
    summary_text = _coerce_summary(
        summary,
        output,
        "Success" if success else "Task finished without summary",
    )
    lines = [
        "[任务完成通知]",
        "类型：普通任务",
        f"任务：{task_name}",
        f"账号：{account_name}",
        f"状态：{'成功' if success else '失败'}",
        f"完成时间：{_format_time(finished_at)}",
        f"摘要：{summary_text}",
    ]
    return _truncate_text("\n".join(lines))


def build_sign_task_message(
    *,
    task_name: str,
    account_name: str,
    success: bool,
    summary: Optional[str],
    finished_at: Optional[datetime],
    output: Optional[str] = None,
    message_events: Optional[list[dict[str, Any]]] = None,
) -> str:
    summary_text = _coerce_summary(
        summary,
        output,
        "Success" if success else "Task finished without summary",
    )
    lines = [
        "[任务完成通知]",
        "类型：签到任务",
        f"任务：{task_name}",
        f"账号：{account_name}",
        f"状态：{'成功' if success else '失败'}",
        f"完成时间：{_format_time(finished_at)}",
        f"摘要：{summary_text}",
    ]

    recent_messages = _recent_message_lines(message_events)
    if recent_messages:
        lines.append("")
        lines.append("最近消息：")
        lines.extend(recent_messages)

    return _truncate_text("\n".join(lines))


class NotificationService:
    async def resolve_target(self, account_name: str) -> NotificationTarget:
        profile = get_account_profile(account_name) or {}
        channel = _clean_optional(profile.get("notification_channel")) or "global"

        if channel == "disabled":
            return NotificationTarget(channel="disabled", bot_token=None, chat_id=None)

        if channel == "custom":
            return NotificationTarget(
                channel="custom",
                bot_token=_clean_optional(profile.get("notification_bot_token")),
                chat_id=_clean_optional(profile.get("notification_chat_id")),
            )

        config = get_config_service().get_telegram_notification_config() or {}
        return NotificationTarget(
            channel="global",
            bot_token=_clean_optional(config.get("bot_token")),
            chat_id=_clean_optional(config.get("chat_id")),
        )

    async def _send_message(self, *, bot_token: str, chat_id: str, text: str) -> bool:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            response.raise_for_status()
        return True

    async def send_regular_task_completion(
        self,
        *,
        task_obj,
        task_log,
        account_name: str,
    ) -> bool:
        target = await self.resolve_target(account_name)
        if not target.bot_token or not target.chat_id:
            return False

        text = build_regular_task_message(
            task_name=str(getattr(task_obj, "name", "") or ""),
            account_name=account_name,
            status=str(getattr(task_log, "status", "") or ""),
            finished_at=getattr(task_log, "finished_at", None),
            summary=None,
            output=getattr(task_log, "output", None),
        )
        return await self._send_message(
            bot_token=target.bot_token,
            chat_id=target.chat_id,
            text=text,
        )

    async def send_sign_task_completion(
        self,
        *,
        task_name: str,
        account_name: str,
        success: bool,
        summary: Optional[str],
        output: Optional[str] = None,
        message_events: Optional[list[dict[str, Any]]] = None,
        finished_at: Optional[datetime] = None,
    ) -> bool:
        target = await self.resolve_target(account_name)
        if not target.bot_token or not target.chat_id:
            return False

        text = build_sign_task_message(
            task_name=task_name,
            account_name=account_name,
            success=success,
            summary=summary,
            output=output,
            message_events=message_events,
            finished_at=finished_at,
        )
        return await self._send_message(
            bot_token=target.bot_token,
            chat_id=target.chat_id,
            text=text,
        )

    async def send_test_message(
        self,
        *,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> bool:
        config = get_config_service().get_telegram_notification_config() or {}
        final_bot_token = _clean_optional(bot_token) or _clean_optional(
            config.get("bot_token")
        )
        final_chat_id = _clean_optional(chat_id) or _clean_optional(config.get("chat_id"))
        if not final_bot_token or not final_chat_id:
            return False

        return await self._send_message(
            bot_token=final_bot_token,
            chat_id=final_chat_id,
            text=(
                "[任务完成通知]\n"
                "类型：测试消息\n"
                "摘要：Telegram Bot 通知配置测试成功"
            ),
        )


_notification_service: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    global _notification_service
    if _notification_service is None:
        _notification_service = NotificationService()
    return _notification_service
