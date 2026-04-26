"""
签到任务服务层
提供签到任务的 CRUD 操作和执行功能
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.core.config import get_settings
from backend.core.logging import (
    build_formatter,
    describe_exception,
    format_log_line,
)
from backend.core.runtime_config import (
    get_sign_task_runtime_config,
    get_telegram_api_runtime_config,
)
from backend.services.notifications import (
    dispatch_notification,
    get_notification_service,
)
from backend.utils.account_locks import get_account_lock
from backend.utils.proxy import resolve_proxy_dict
from backend.utils.tg_session import (
    get_account_proxy,
    get_account_session_string,
    get_global_semaphore,
    get_session_mode,
    load_session_string_file,
)
from tg_signer.core import UserSigner, get_client

settings = get_settings()
logger = logging.getLogger("backend.sign_tasks")


def _normalize_chat_action_interval(chat: dict, config_version) -> dict:
    """Migrate action_interval from seconds to milliseconds for configs older than v4."""
    normalized = dict(chat)
    if config_version is None or config_version < 4:
        normalized["action_interval"] = int(float(normalized.get("action_interval", 1)) * 1000)
    return normalized


def _normalize_legacy_chat_actions(chat: dict) -> dict:
    normalized = dict(chat)
    actions = normalized.get("actions")
    if isinstance(actions, list):
        return normalized

    normalized_actions: List[Dict[str, Any]] = []
    sign_text = normalized.get("sign_text")
    if sign_text:
        if normalized.get("as_dice"):
            normalized_actions.append({"action": 2, "dice": sign_text})
        else:
            normalized_actions.append({"action": 1, "text": sign_text})

    button_text = str(normalized.get("text_of_btn_to_click", "") or "").strip()
    if button_text:
        normalized_actions.append({"action": 3, "text": button_text})

    if bool(normalized.get("choose_option_by_image")):
        normalized_actions.append({"action": 4})

    if bool(normalized.get("has_calculation_problem")):
        normalized_actions.append({"action": 5})

    normalized["actions"] = normalized_actions
    return normalized


def _normalize_task_chats(
    chats: Any, config_version: Optional[int]
) -> List[Dict[str, Any]]:
    if not isinstance(chats, list):
        return []

    normalized_chats: List[Dict[str, Any]] = []
    for chat in chats:
        if not isinstance(chat, dict):
            continue
        normalized_chat = _normalize_chat_action_interval(chat, config_version)
        normalized_chat = _normalize_legacy_chat_actions(normalized_chat)
        normalized_chats.append(normalized_chat)
    return normalized_chats


class TaskLogHandler(logging.Handler):
    """
    自定义日志处理器，将日志实时写入到内存列表中
    """

    def __init__(self, log_list: List[str], on_log: Optional[Callable[[str], None]] = None):
        super().__init__()
        self.log_list = log_list
        self.on_log = on_log

    def emit(self, record):
        try:
            msg = self.format(record)
            self.log_list.append(msg)
            if self.on_log:
                self.on_log(msg)
            # 保持日志长度，避免内存占用过大
            if len(self.log_list) > 1000:
                self.log_list.pop(0)
        except Exception:
            self.handleError(record)


class BackendUserSigner(UserSigner):
    """
    后端专用的 UserSigner，适配后端目录结构并禁止交互式输入
    """

    @property
    def task_dir(self):
        # 适配后端的目录结构: signs_dir / account_name / task_name
        # self.tasks_dir -> workdir/signs
        return self.tasks_dir / self._account / self.task_name

    def ask_for_config(self):
        raise ValueError(
            f"任务配置文件不存在: {self.config_file}，且后端模式下禁止交互式输入。"
        )

    def reconfig(self):
        raise ValueError(
            f"任务配置文件不存在: {self.config_file}，且后端模式下禁止交互式输入。"
        )

    def ask_one(self):
        raise ValueError("后端模式下禁止交互式输入")


class SignTaskService:
    """签到任务服务类"""

    def __init__(self):
        from backend.core.config import get_settings

        settings = get_settings()
        runtime_config = get_sign_task_runtime_config()
        self.workdir = settings.resolve_workdir()
        self.signs_dir = self.workdir / "signs"
        self.run_history_dir = self.workdir / "history"
        self.signs_dir.mkdir(parents=True, exist_ok=True)
        self.run_history_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "初始化签到任务服务: signs_dir=%s, history_dir=%s",
            self.signs_dir,
            self.run_history_dir,
        )
        self._active_logs: Dict[tuple[str, str], List[str]] = {}  # (account, task) -> logs
        self._active_message_events: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
        self._active_message_event_sequences: Dict[tuple[str, str], int] = {}
        self._active_tasks: Dict[tuple[str, str], bool] = {}  # (account, task) -> running
        self._background_tasks: Dict[tuple[str, str], asyncio.Task] = {}
        self._background_owned_tasks: set[tuple[str, str]] = set()
        self._task_statuses: Dict[tuple[str, str], Dict[str, Any]] = {}
        self._cleanup_tasks: Dict[tuple[str, str], asyncio.Task] = {}
        self._tasks_cache = None  # 内存缓存
        self._account_locks: Dict[str, asyncio.Lock] = {}  # 账号锁
        self._account_last_run_end: Dict[str, float] = {}  # 账号最后一次结束时间
        self._account_cooldown_seconds = runtime_config.account_cooldown_seconds
        self._history_max_entries = runtime_config.history_max_entries
        self._history_max_flow_lines = runtime_config.history_max_flow_lines
        self._history_max_line_chars = runtime_config.history_max_line_chars
        self._history_max_message_events = getattr(
            runtime_config, "history_max_message_events", 100
        )
        self._active_message_event_buffer_limit = (
            self._history_max_message_events
            if self._history_max_message_events > 0
            else 100
        )
        self._cleanup_old_logs()

    @staticmethod
    def _validate_execution_window(
        *,
        task_name: str,
        sign_at: str,
        execution_mode: str,
        range_start: str,
        range_end: str,
    ) -> str:
        normalized_mode = str(execution_mode or "fixed").strip().lower() or "fixed"
        if normalized_mode not in {"fixed", "range"}:
            raise ValueError(
                f"任务 {task_name} 的执行模式无效，仅支持 fixed 或 range"
            )

        if normalized_mode == "range":
            start_text = str(range_start or "").strip()
            end_text = str(range_end or "").strip()
            if not start_text or not end_text:
                raise ValueError(
                    f"任务 {task_name} 使用随机时间段模式时必须同时填写开始时间和结束时间"
                )
            for label, value in (("开始时间", start_text), ("结束时间", end_text)):
                try:
                    datetime.strptime(value, "%H:%M")
                except ValueError as exc:
                    raise ValueError(
                        f"任务 {task_name} 的{label}格式无效，必须为 HH:MM"
                    ) from exc
            return normalized_mode

        if not str(sign_at or "").strip():
            raise ValueError(f"任务 {task_name} 的固定执行时间不能为空")
        return normalized_mode

    def _append_active_log(
        self,
        task_key: tuple[str, str],
        message: str,
        *,
        level: str = "INFO",
        logger_name: str = "backend.sign_tasks",
    ) -> None:
        logs = self._active_logs.setdefault(task_key, [])
        logs.append(format_log_line(message, level=level, logger_name=logger_name))
        if len(logs) > 1000:
            del logs[:-1000]

    @staticmethod
    def _task_requires_updates(task_config: Optional[Dict[str, Any]]) -> bool:
        """
        判断任务是否依赖 update handlers。
        """
        if not isinstance(task_config, dict):
            return True
        raw_chats = task_config.get("chats")
        if not isinstance(raw_chats, list):
            return True
        chats = _normalize_task_chats(raw_chats, task_config.get("_version"))
        if not chats:
            return False
        response_actions = {3, 4, 5, 6, 7}
        for chat in chats:
            actions = chat.get("actions")
            if not isinstance(actions, list):
                continue
            for action in actions:
                if not isinstance(action, dict):
                    continue
                try:
                    action_id = int(action.get("action"))
                except (TypeError, ValueError):
                    continue
                if action_id in response_actions:
                    return True
        return False

    def _cleanup_old_logs(self):
        """清理超过 3 天的日志"""
        from datetime import datetime, timedelta

        if not self.run_history_dir.exists():
            logger.info("签到任务历史目录不存在，跳过清理: %s", self.run_history_dir)
            return

        limit = datetime.now() - timedelta(days=3)
        for log_file in self.run_history_dir.glob("*.json"):
            if log_file.stat().st_mtime < limit.timestamp():
                try:
                    log_file.unlink()
                except Exception as exc:
                    logger.warning(
                        "清理过期签到历史失败: 路径=%s, 错误=%s",
                        log_file,
                        describe_exception(exc),
                    )
                    continue

    def _safe_history_key(self, name: str) -> str:
        return name.replace("/", "_").replace("\\", "_")

    def _history_file_path(self, task_name: str, account_name: str = "") -> Path:
        if account_name:
            safe_account = self._safe_history_key(account_name)
            safe_task = self._safe_history_key(task_name)
            return self.run_history_dir / f"{safe_account}__{safe_task}.json"
        return self.run_history_dir / f"{self._safe_history_key(task_name)}.json"

    def _normalize_flow_logs(
        self, flow_logs: Optional[List[str]]
    ) -> tuple[List[str], bool, int]:
        if not isinstance(flow_logs, list):
            return [], False, 0

        total = len(flow_logs)
        trimmed: List[str] = []
        for line in flow_logs[: self._history_max_flow_lines]:
            text = str(line).replace("\r", "").rstrip("\n")
            if len(text) > self._history_max_line_chars:
                text = text[: self._history_max_line_chars] + "..."
            trimmed.append(text)
        return trimmed, total > len(trimmed), total

    @staticmethod
    def _normalize_message_sender(sender: Any) -> Dict[str, Any]:
        if not isinstance(sender, dict):
            return {"id": None, "username": "", "display_name": "", "is_self": False}
        return {
            "id": sender.get("id"),
            "username": str(sender.get("username", "") or ""),
            "display_name": str(sender.get("display_name", "") or ""),
            "is_self": bool(sender.get("is_self", False)),
        }

    def _normalize_message_event(self, event: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(event, dict):
            return None
        return {
            "event_id": str(event.get("event_id", "") or ""),
            "event_type": str(event.get("event_type", "") or ""),
            "event_time": str(event.get("event_time", "") or ""),
            "message_id": event.get("message_id"),
            "chat_id": event.get("chat_id"),
            "chat_title": str(event.get("chat_title", "") or ""),
            "chat_username": str(event.get("chat_username", "") or ""),
            "sender": self._normalize_message_sender(event.get("sender")),
            "recipient": self._normalize_message_sender(event.get("recipient")),
            "is_outgoing": bool(event.get("is_outgoing", False)),
            "text": str(event.get("text", "") or ""),
            "caption": str(event.get("caption", "") or ""),
            "summary": str(event.get("summary", "") or ""),
        }

    def _normalize_message_events(
        self, message_events: Optional[List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        if not isinstance(message_events, list):
            return []
        if self._history_max_message_events <= 0:
            return []
        normalized = []
        for event in message_events[-self._history_max_message_events :]:
            normalized_event = self._normalize_message_event(event)
            if normalized_event is not None:
                normalized.append(normalized_event)
        return normalized

    @staticmethod
    def _public_message_event(event: Dict[str, Any]) -> Dict[str, Any]:
        public_event = dict(event)
        public_event.pop("_sequence", None)
        return public_event

    def _get_active_message_event_state(
        self, task_name: str, account_name: Optional[str] = None
    ) -> tuple[List[Dict[str, Any]], int]:
        if account_name:
            task_key = self._task_key(account_name, task_name)
            return (
                self._active_message_events.get(task_key, []),
                self._active_message_event_sequences.get(task_key, 0),
            )
        for key, events in self._active_message_events.items():
            if key[1] == task_name:
                return events, self._active_message_event_sequences.get(key, 0)
        return [], 0

    def _incoming_message_summaries(
        self, message_events: Optional[List[Dict[str, Any]]]
    ) -> List[str]:
        if not isinstance(message_events, list):
            return []

        def _event_key(event: Dict[str, Any]) -> str:
            message_id = event.get("message_id")
            chat_id = event.get("chat_id")
            if message_id is not None:
                return f"{chat_id}:{message_id}"
            event_id = str(event.get("event_id", "") or "")
            parts = event_id.split(":", 3)
            if len(parts) >= 3 and parts[1] and parts[2]:
                return f"{parts[1]}:{parts[2]}"
            return event_id

        summaries: List[str] = []
        summary_positions: Dict[str, int] = {}
        for event in message_events:
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("event_type", "") or "").strip().lower()
            if event_type and event_type not in {"message_received", "message_edited"}:
                continue
            sender = event.get("sender")
            sender_is_self = isinstance(sender, dict) and bool(
                sender.get("is_self", False)
            )
            if bool(event.get("is_outgoing", False)) or sender_is_self:
                continue
            summary = str(event.get("summary", "") or "").strip()
            if not summary:
                summary = (
                    str(event.get("text", "") or "").strip()
                    or str(event.get("caption", "") or "").strip()
                )
            if summary:
                summary = summary[:200] if len(summary) <= 200 else summary[:197] + "..."
                event_key = _event_key(event)
                if event_key and event_key in summary_positions:
                    summaries[summary_positions[event_key]] = summary
                elif event_key:
                    summary_positions[event_key] = len(summaries)
                    summaries.append(summary)
                else:
                    summaries.append(summary)
        return summaries

    def _latest_message_summary(
        self, message_events: Optional[List[Dict[str, Any]]]
    ) -> str:
        summaries = self._incoming_message_summaries(message_events)
        if not summaries:
            return ""

        summary = f"收到 {len(summaries)} 条消息"
        return summary[:200] if len(summary) <= 200 else summary[:197] + "..."

    def _load_history_entries(
        self, task_name: str, account_name: str = ""
    ) -> List[Dict[str, Any]]:
        history_file = self._history_file_path(task_name, account_name)
        legacy_file = self.run_history_dir / f"{self._safe_history_key(task_name)}.json"

        if not history_file.exists():
            if account_name and legacy_file.exists():
                history_file = legacy_file
            elif not account_name and legacy_file.exists():
                history_file = legacy_file
            else:
                return []

        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []

        if isinstance(data, dict):
            data_list = [data]
        elif isinstance(data, list):
            data_list = data
        else:
            return []

        entries: List[Dict[str, Any]] = []
        for item in data_list:
            if not isinstance(item, dict):
                continue
            if account_name:
                item_account = item.get("account_name")
                if item_account and item_account != account_name:
                    continue
            entries.append(item)

        entries.sort(key=lambda x: x.get("time", ""), reverse=True)
        return entries

    def get_task_history_logs(
        self, task_name: str, account_name: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        if limit < 1:
            limit = 1
        if limit > 200:
            limit = 200

        history = self._load_history_entries(task_name, account_name=account_name)
        result: List[Dict[str, Any]] = []
        for item in history[:limit]:
            flow_logs = item.get("flow_logs")
            if not isinstance(flow_logs, list):
                flow_logs = []
            message_events = self._normalize_message_events(item.get("message_events"))
            message = item.get("message", "") or ""
            if bool(item.get("success", False)):
                message = self._latest_message_summary(message_events) or message

            result.append(
                {
                    "time": item.get("time", ""),
                    "success": bool(item.get("success", False)),
                    "message": message,
                    "job_id": item.get("job_id", ""),
                    "task_name": item.get("task_name", task_name),
                    "account_name": item.get("account_name", account_name or ""),
                    "status": item.get(
                        "status",
                        "completed" if bool(item.get("success", False)) else "failed",
                    ),
                    "status_text": item.get(
                        "status_text",
                        "任务已完成" if bool(item.get("success", False)) else "执行失败",
                    ),
                    "started_at": item.get("started_at", ""),
                    "action_completed_at": item.get("action_completed_at", ""),
                    "finished_at": item.get("finished_at", ""),
                    "duration_seconds": item.get("duration_seconds"),
                    "blocking_info": item.get("blocking_info"),
                    "flow_logs": [str(line) for line in flow_logs],
                    "flow_truncated": bool(item.get("flow_truncated", False)),
                    "flow_line_count": int(item.get("flow_line_count", len(flow_logs))),
                    "message_events": message_events,
                }
            )
        return result

    def get_account_history_logs(self, account_name: str) -> List[Dict[str, Any]]:
        """获取某账号下所有任务的最近历史日志"""
        all_history = []
        if not self.run_history_dir.exists():
            return []

        # 优化：先获取该账号下的任务列表，只读取相关任务的日志
        # 避免扫描整个 history 目录并读取所有文件
        tasks = self.list_tasks(account_name=account_name)

        for task in tasks:
            task_name = task["name"]
            history_file = self._history_file_path(task_name, account_name)

            if not history_file.exists():
                legacy_file = self.run_history_dir / f"{task_name}.json"
                if legacy_file.exists():
                    history_file = legacy_file
                else:
                    continue

            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    data_list = json.load(f)
                    if not isinstance(data_list, list):
                        data_list = [data_list]

                    # 再次确认 account_name (虽然是从 task 列表来的，但以防万一)
                    for data in data_list:
                        if data.get("account_name") == account_name:
                            normalized = dict(data)
                            normalized["task_name"] = task_name
                            if bool(normalized.get("success", False)):
                                normalized["message"] = self._latest_message_summary(
                                    normalized.get("message_events")
                                ) or (normalized.get("message", "") or "")
                            else:
                                normalized["message"] = normalized.get("message", "") or ""
                            all_history.append(normalized)
            except Exception:
                continue

        # 按时间倒序
        all_history.sort(key=lambda x: x.get("time", ""), reverse=True)
        return all_history

    def clear_account_history_logs(self, account_name: str) -> Dict[str, int]:
        """娓呯悊鏌愯处鍙风殑鍘嗗彶鏃ュ織锛屼笉褰卞搷鍏朵粬璐﹀彿"""
        removed_files = 0
        removed_entries = 0

        if not self.run_history_dir.exists():
            return {"removed_files": 0, "removed_entries": 0}

        def _count_entries(data: Any) -> int:
            if isinstance(data, list):
                return len(data)
            if isinstance(data, dict):
                return 1
            return 0

        tasks = self.list_tasks(account_name=account_name)
        for task in tasks:
            task_name = task.get("name") or ""
            if not task_name:
                continue

            # --- CLEAR TASK LAST RUN METADATA ---
            task_dir = self.signs_dir / account_name / task_name
            if not task_dir.exists():
                task_dir = self.signs_dir / task_name
            config_file = task_dir / "config.json"
            if config_file.exists():
                try:
                    import json
                    with open(config_file, "r", encoding="utf-8") as f:
                        config = json.load(f)
                    if "last_run" in config:
                        del config["last_run"]
                        with open(config_file, "w", encoding="utf-8") as f:
                            json.dump(config, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass

            if self._tasks_cache is not None:
                for t in self._tasks_cache:
                    if t["name"] == task_name and t.get("account_name") == account_name:
                        t.pop("last_run", None)
                        break
            # ------------------------------------

            history_file = self._history_file_path(task_name, account_name)
            if history_file.exists():
                try:
                    with open(history_file, "r", encoding="utf-8") as f:
                        removed_entries += _count_entries(json.load(f))
                except Exception:
                    pass
                try:
                    history_file.unlink()
                    removed_files += 1
                except Exception:
                    pass
                continue

            legacy_file = self.run_history_dir / f"{self._safe_history_key(task_name)}.json"
            if not legacy_file.exists():
                continue

            try:
                with open(legacy_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    data_list = [data]
                elif isinstance(data, list):
                    data_list = data
                else:
                    data_list = []
            except Exception:
                continue

            if not data_list:
                try:
                    legacy_file.unlink()
                    removed_files += 1
                except Exception:
                    pass
                continue

            # legacy 鏂囦欢鍙兘娌℃湁 account_name 锛屾槸鏃х増鍗曡处鍙峰湺鏅?
            has_account_field = any(
                isinstance(item, dict) and "account_name" in item for item in data_list
            )
            if not has_account_field:
                removed_entries += len(data_list)
                try:
                    legacy_file.unlink()
                    removed_files += 1
                except Exception:
                    pass
                continue

            kept: List[Dict[str, Any]] = []
            for item in data_list:
                if not isinstance(item, dict):
                    continue
                if item.get("account_name") == account_name:
                    removed_entries += 1
                else:
                    kept.append(item)

            if not kept:
                try:
                    legacy_file.unlink()
                    removed_files += 1
                except Exception:
                    pass
            else:
                try:
                    with open(legacy_file, "w", encoding="utf-8") as f:
                        json.dump(kept, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass

        return {"removed_files": removed_files, "removed_entries": removed_entries}

    def _get_last_run_info(
        self, task_dir: Path, account_name: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        获取任务的最后执行信息
        """
        history_file = self._history_file_path(task_dir.name, account_name)
        legacy_file = self.run_history_dir / f"{task_dir.name}.json"

        if not history_file.exists():
            if account_name and legacy_file.exists():
                history_file = legacy_file
            else:
                return None

        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data[0]  # 最近的一条
                elif isinstance(data, dict):
                    return data
                return None
        except Exception:
            return None

    def _save_run_info(
        self,
        task_name: str,
        success: bool,
        message: str = "",
        account_name: str = "",
        flow_logs: Optional[List[str]] = None,
        message_events: Optional[List[Dict[str, Any]]] = None,
        run_metadata: Optional[Dict[str, Any]] = None,
    ):
        """保存任务执行历史 (保留列表)"""
        from datetime import datetime

        history_file = self._history_file_path(task_name, account_name)
        normalized_logs, flow_truncated, flow_line_count = self._normalize_flow_logs(
            flow_logs
        )
        normalized_message_events = self._normalize_message_events(message_events)
        run_metadata = run_metadata or {}

        new_entry = {
            "time": datetime.now().isoformat(),
            "success": success,
            "message": message,
            "account_name": account_name,
            "job_id": run_metadata.get("job_id", ""),
            "task_name": task_name,
            "status": run_metadata.get("status", "completed" if success else "failed"),
            "status_text": run_metadata.get(
                "status_text", "任务已完成" if success else "执行失败"
            ),
            "started_at": run_metadata.get("started_at", ""),
            "action_completed_at": run_metadata.get("action_completed_at", ""),
            "finished_at": run_metadata.get("finished_at", ""),
            "duration_seconds": run_metadata.get("duration_seconds"),
            "blocking_info": run_metadata.get("blocking_info"),
            "flow_logs": normalized_logs,
            "flow_truncated": flow_truncated,
            "flow_line_count": flow_line_count,
            "message_events": normalized_message_events,
        }

        history = []
        if history_file.exists():
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        history = data
                    else:
                        history = [data]
            except Exception:
                history = []

        history.insert(0, new_entry)
        # 只保留最近 N 条
        history = history[: self._history_max_entries]

        try:
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)

            # 同时更新任务配置中的 last_run
            # 1. 更新磁盘上的 config.json
            task = self.get_task(task_name, account_name)
            if task:
                # 注意 get_task 返回的是 dict，我们需要路径
                # 重新构建路径或复用逻辑
                # 这里为了简单，再次查找路径有点低效，但比全量扫描好
                # 我们可以利用 self.signs_dir / account_name / task_name
                # 但考虑到兼容性，还是得稍微判断下
                task_dir = self.signs_dir / account_name / task_name
                if not task_dir.exists():
                    task_dir = self.signs_dir / task_name

                config_file = task_dir / "config.json"
                if config_file.exists():
                    try:
                        with open(config_file, "r", encoding="utf-8") as f:
                            config = json.load(f)
                        config["last_run"] = new_entry
                        with open(config_file, "w", encoding="utf-8") as f:
                            json.dump(config, f, ensure_ascii=False, indent=2)
                    except Exception as e:
                        logger.warning(
                            "更新签到任务 last_run 失败: 账号=%s, 任务=%s, 配置文件=%s, 错误=%s",
                            account_name,
                            task_name,
                            config_file,
                            describe_exception(e),
                        )

            # 2. 更新内存缓存 (关键优化：避免置空 self._tasks_cache)
            if self._tasks_cache is not None:
                for t in self._tasks_cache:
                    if t["name"] == task_name and t.get("account_name") == account_name:
                        t["last_run"] = new_entry
                        break

        except Exception as e:
            logger.exception(
                "保存签到任务运行历史失败: 账号=%s, 任务=%s, 错误=%s",
                account_name,
                task_name,
                describe_exception(e),
            )

    def _append_scheduler_log(self, filename: str, message: str) -> None:
        try:
            logs_dir = settings.resolve_logs_dir()
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_path = logs_dir / filename
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{message}\n")
        except Exception as e:
            logging.getLogger("backend.sign_tasks").warning(
                "写入调度补充日志失败: 文件=%s, 错误=%s",
                filename,
                describe_exception(e),
            )

    def list_tasks(
        self, account_name: Optional[str] = None, force_refresh: bool = False
    ) -> List[Dict[str, Any]]:
        """
        获取所有签到任务列表 (支持内存缓存)
        """
        if self._tasks_cache is not None and not force_refresh:
            if account_name:
                return [
                    t
                    for t in self._tasks_cache
                    if t.get("account_name") == account_name
                ]
            return self._tasks_cache

        tasks = []
        base_dir = self.signs_dir

        if not base_dir.exists():
            logger.info("签到任务目录不存在，返回空列表: %s", base_dir)
            return []

        logger.info("开始扫描签到任务目录: %s", base_dir)
        try:
            # 扫描所有子目录 (账号名)
            for account_path in base_dir.iterdir():
                if not account_path.is_dir():
                    # 兼容旧路径：直接在 signs 目录下的任务
                    if (account_path / "config.json").exists():
                        task_info = self._load_task_config(account_path)
                        if task_info:
                            tasks.append(task_info)
                    continue

                # 扫描账号目录下的任务
                for task_dir in account_path.iterdir():
                    if not task_dir.is_dir():
                        continue

                    task_info = self._load_task_config(task_dir)
                    if task_info:
                        tasks.append(task_info)

            self._tasks_cache = sorted(
                tasks, key=lambda x: (x["account_name"], x["name"])
            )

            if account_name:
                return [
                    t
                    for t in self._tasks_cache
                    if t.get("account_name") == account_name
                ]
            return self._tasks_cache

        except Exception as e:
            logger.exception(
                "扫描签到任务目录失败: 目录=%s, 错误=%s",
                base_dir,
                describe_exception(e),
            )
            return []

    def _load_task_config(self, task_dir: Path) -> Optional[Dict[str, Any]]:
        """加载单个任务配置，优先使用 config.json 中的 last_run"""
        config_file = task_dir / "config.json"
        if not config_file.exists():
            return None

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)

            # 优先从 config 读取 last_run
            last_run = config.get("last_run")
            if not last_run:
                last_run = self._get_last_run_info(
                    task_dir, account_name=config.get("account_name", "")
                )

            chats = _normalize_task_chats(config.get("chats"), config.get("_version"))

            return {
                "name": task_dir.name,
                "account_name": config.get("account_name", ""),
                "sign_at": config.get("sign_at", ""),
                "random_seconds": config.get("random_seconds", 0),
                "sign_interval": config.get("sign_interval", 1),
                "chats": chats,
                "enabled": True,
                "last_run": last_run,
                "execution_mode": config.get("execution_mode", "fixed"),
                "range_start": config.get("range_start", ""),
                "range_end": config.get("range_end", ""),
            }
        except Exception as exc:
            logger.warning(
                "加载签到任务配置失败: 任务目录=%s, 错误=%s",
                task_dir,
                describe_exception(exc),
            )
            return None

    def get_task(
        self, task_name: str, account_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        获取单个任务的详细信息
        """
        if account_name:
            task_dir = self.signs_dir / account_name / task_name
        else:
            # 搜索模式 (兼容旧版或未传 account_name 的情况)
            task_dir = self.signs_dir / task_name
            if not (task_dir / "config.json").exists():
                # 在所有账号目录下搜
                for acc_dir in self.signs_dir.iterdir():
                    if (
                        acc_dir.is_dir()
                        and (acc_dir / task_name / "config.json").exists()
                    ):
                        task_dir = acc_dir / task_name
                        break

        config_file = task_dir / "config.json"

        if not config_file.exists():
            return None

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)

            chats = _normalize_task_chats(config.get("chats"), config.get("_version"))

            return {
                "name": task_name,
                "account_name": config.get("account_name", ""),
                "sign_at": config.get("sign_at", ""),
                "random_seconds": config.get("random_seconds", 0),
                "sign_interval": config.get("sign_interval", 1),
                "chats": chats,
                "enabled": True,
                "execution_mode": config.get("execution_mode", "fixed"),
                "range_start": config.get("range_start", ""),
                "range_end": config.get("range_end", ""),
            }
        except Exception:
            return None

    def create_task(
        self,
        task_name: str,
        sign_at: str,
        chats: List[Dict[str, Any]],
        random_seconds: int = 0,
        sign_interval: Optional[int] = None,
        account_name: str = "",
        execution_mode: str = "fixed",
        range_start: str = "",
        range_end: str = "",
    ) -> Dict[str, Any]:
        """
        创建新的签到任务
        """
        import random

        from backend.services.config import get_config_service

        if not account_name:
            raise ValueError("必须指定账号名称")

        normalized_mode = self._validate_execution_window(
            task_name=task_name,
            sign_at=sign_at,
            execution_mode=execution_mode,
            range_start=range_start or "",
            range_end=range_end or "",
        )

        account_dir = self.signs_dir / account_name
        account_dir.mkdir(parents=True, exist_ok=True)

        task_dir = account_dir / task_name
        if task_dir.exists():
            raise ValueError(f"任务 {task_name} 已存在，请勿重复创建")
        task_dir.mkdir(parents=True, exist_ok=False)

        # 获取 sign_interval
        if sign_interval is None:
            config_service = get_config_service()
            global_settings = config_service.get_global_settings()
            sign_interval = global_settings.get("sign_interval")

        if sign_interval is None:
            sign_interval = random.randint(1, 120)

        config = {
            "_version": 4,
            "account_name": account_name,
            "sign_at": sign_at,
            "random_seconds": random_seconds,
            "sign_interval": sign_interval,
            "chats": chats,
            "execution_mode": normalized_mode,
            "range_start": range_start,
            "range_end": range_end,
        }

        config_file = task_dir / "config.json"

        try:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.exception(
                "写入签到任务配置失败: 账号=%s, 任务=%s, 配置文件=%s, 错误=%s",
                account_name,
                task_name,
                config_file,
                describe_exception(e),
            )
            raise

        # Invalidate cache
        self._tasks_cache = None

        try:
            from backend.scheduler import add_or_update_sign_task_job

            add_or_update_sign_task_job(
                account_name,
                task_name,
                range_start if execution_mode == "range" else sign_at,
                enabled=True,
            )
        except Exception as e:
            logger.warning(
                "创建签到任务后更新调度失败: 账号=%s, 任务=%s, 错误=%s",
                account_name,
                task_name,
                describe_exception(e),
            )
        else:
            logger.info(
                "创建签到任务成功: 账号=%s, 任务=%s, 模式=%s",
                account_name,
                task_name,
                normalized_mode,
            )

        return {
            "name": task_name,
            "account_name": account_name,
            "sign_at": sign_at,
            "random_seconds": random_seconds,
            "sign_interval": sign_interval,
            "chats": chats,
            "enabled": True,
            "execution_mode": execution_mode,
            "range_start": range_start,
            "range_end": range_end,
        }

    def update_task(
        self,
        task_name: str,
        sign_at: Optional[str] = None,
        chats: Optional[List[Dict[str, Any]]] = None,
        random_seconds: Optional[int] = None,
        sign_interval: Optional[int] = None,
        account_name: Optional[str] = None,
        execution_mode: Optional[str] = None,
        range_start: Optional[str] = None,
        range_end: Optional[str] = None,
        new_task_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        更新签到任务
        """
        # 获取现有配置
        existing = self.get_task(task_name, account_name)
        if not existing:
            raise ValueError(f"任务 {task_name} 不存在")

        # Determine the account name for the update.
        # If a new account_name is provided, use it. Otherwise, use the existing one.
        acc_name = (
            account_name
            if account_name is not None
            else existing.get("account_name", "")
        )

        # 更新配置
        normalized_mode = self._validate_execution_window(
            task_name=new_task_name or task_name,
            sign_at=sign_at if sign_at is not None else existing["sign_at"],
            execution_mode=execution_mode
            if execution_mode is not None
            else existing.get("execution_mode", "fixed"),
            range_start=range_start
            if range_start is not None
            else existing.get("range_start", ""),
            range_end=range_end
            if range_end is not None
            else existing.get("range_end", ""),
        )

        config = {
            "_version": 4,
            "account_name": acc_name,
            "sign_at": sign_at if sign_at is not None else existing["sign_at"],
            "random_seconds": random_seconds
            if random_seconds is not None
            else existing["random_seconds"],
            "sign_interval": sign_interval
            if sign_interval is not None
            else existing["sign_interval"],
            "chats": chats if chats is not None else existing["chats"],
            "execution_mode": normalized_mode,
            "range_start": range_start
            if range_start is not None
            else existing.get("range_start", ""),
            "range_end": range_end
            if range_end is not None
            else existing.get("range_end", ""),
        }

        # 提前校验重命名，确保在写入配置前失败，避免脏数据
        effective_task_name = task_name
        target_dir = None
        if new_task_name and new_task_name != task_name:
            target_dir = self.signs_dir / acc_name / new_task_name
            if target_dir.exists():
                raise ValueError(f"任务 {new_task_name} 已存在")
            effective_task_name = new_task_name

        # 保存配置
        task_dir = self.signs_dir / acc_name / task_name
        if not task_dir.exists():
            # 兼容旧路径
            task_dir = self.signs_dir / task_name

        config_file = task_dir / "config.json"
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        # 执行目录重命名
        if target_dir is not None:
            task_dir.rename(target_dir)

        # Invalidate cache
        self._tasks_cache = None

        try:
            from backend.scheduler import add_or_update_sign_task_job

            add_or_update_sign_task_job(
                config["account_name"],
                effective_task_name,
                config.get("range_start")
                if config.get("execution_mode") == "range"
                else config["sign_at"],
                enabled=True,
            )
        except Exception as e:
            msg = (
                f"更新签到任务调度失败: 账号={config['account_name']}, "
                f"任务={effective_task_name}, 错误={describe_exception(e)}"
            )
            logger.warning(msg)
            self._append_scheduler_log(
                "scheduler_error.log", format_log_line(msg, logger_name="backend.sign_tasks")
            )
        else:
            logger.info(
                "更新签到任务成功: 账号=%s, 任务=%s, 模式=%s",
                config["account_name"],
                effective_task_name,
                normalized_mode,
            )
            self._append_scheduler_log(
                "scheduler_update.log",
                format_log_line(
                    (
                        f"已更新任务调度: 任务={effective_task_name}, CRON="
                        f"{config.get('range_start') if config.get('execution_mode') == 'range' else config['sign_at']}"
                    ),
                    logger_name="backend.sign_tasks",
                ),
            )

        return {
            "name": effective_task_name,
            "account_name": config["account_name"],
            "sign_at": config["sign_at"],
            "random_seconds": config["random_seconds"],
            "sign_interval": config["sign_interval"],
            "chats": config["chats"],
            "enabled": True,
            "execution_mode": config.get("execution_mode", "fixed"),
            "range_start": config.get("range_start", ""),
            "range_end": config.get("range_end", ""),
        }

    def delete_task(self, task_name: str, account_name: Optional[str] = None) -> bool:
        """
        删除签到任务
        """
        task_dir = None
        if account_name:
            task_dir = self.signs_dir / account_name / task_name
            # 如果指定了账号但任务不存在，直接返回失败，不进行搜索
            if not task_dir.exists():
                return False
        else:
            # 未指定账号，尝试搜索 (兼容旧逻辑，但不推荐)
            task_dir = self.signs_dir / task_name
            if not task_dir.exists():
                for acc_dir in self.signs_dir.iterdir():
                    if acc_dir.is_dir() and (acc_dir / task_name).exists():
                        task_dir = acc_dir / task_name
                        break

        if not task_dir or not task_dir.exists():
            return False

        # 确定真实的 account_name，以便移除调度
        real_account_name = account_name
        if not real_account_name:
            # 尝试从路径推断
            if task_dir.parent.parent == self.signs_dir:
                real_account_name = task_dir.parent.name
            else:
                # 回退尝试读取 config
                try:
                    with open(task_dir / "config.json", "r") as f:
                        real_account_name = json.load(f).get("account_name")
                except Exception:
                    pass

        try:
            import shutil

            shutil.rmtree(task_dir)
            # Invalidate cache
            self._tasks_cache = None

            if real_account_name:
                try:
                    from backend.scheduler import remove_sign_task_job

                    remove_sign_task_job(real_account_name, task_name)
                except Exception as e:
                    logger.warning(
                        "删除签到任务后移除调度失败: 账号=%s, 任务=%s, 错误=%s",
                        real_account_name,
                        task_name,
                        describe_exception(e),
                    )

            logger.info(
                "删除签到任务成功: 账号=%s, 任务=%s, 路径=%s",
                real_account_name,
                task_name,
                task_dir,
            )

            return True
        except Exception as exc:
            logger.exception(
                "删除签到任务失败: 账号=%s, 任务=%s, 路径=%s, 错误=%s",
                real_account_name,
                task_name,
                task_dir,
                describe_exception(exc),
            )
            return False

    async def get_account_chats(
        self, account_name: str, force_refresh: bool = False
    ) -> List[Dict[str, Any]]:
        """
        获取账号的 Chat 列表 (带缓存)
        """
        cache_file = self.signs_dir / account_name / "chats_cache.json"

        if not force_refresh and cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        # 如果没有缓存或强制刷新，执行刷新逻辑
        return await self.refresh_account_chats(account_name)

    def search_account_chats(
        self,
        account_name: str,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        通过缓存搜索账号的 Chat 列表（不触发全量 get_dialogs）
        """
        cache_file = self.signs_dir / account_name / "chats_cache.json"

        if limit < 1:
            limit = 1
        if limit > 200:
            limit = 200
        if offset < 0:
            offset = 0

        if not cache_file.exists():
            return {"items": [], "total": 0, "limit": limit, "offset": offset}

        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}

        if not isinstance(data, list):
            return {"items": [], "total": 0, "limit": limit, "offset": offset}

        q = (query or "").strip()
        if not q:
            total = len(data)
            return {
                "items": data[offset : offset + limit],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

        is_numeric = q.lstrip("-").isdigit()
        if is_numeric or q.startswith("-100"):
            def match(chat: Dict[str, Any]) -> bool:
                chat_id = chat.get("id")
                if chat_id is None:
                    return False
                return q in str(chat_id)
        else:
            q_lower = q.lower()

            def match(chat: Dict[str, Any]) -> bool:
                title = (chat.get("title") or "").lower()
                username = (chat.get("username") or "").lower()
                return q_lower in title or q_lower in username

        filtered = [c for c in data if match(c)]
        total = len(filtered)
        return {
            "items": filtered[offset : offset + limit],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @staticmethod
    def _is_invalid_session_error(err: Exception) -> bool:
        msg = str(err)
        if not msg:
            return False
        upper = msg.upper()
        return (
            "AUTH_KEY_UNREGISTERED" in upper
            or "AUTH_KEY_INVALID" in upper
            or "SESSION_REVOKED" in upper
            or "SESSION_EXPIRED" in upper
            or "USER_DEACTIVATED" in upper
        )

    async def _cleanup_invalid_session(self, account_name: str) -> None:
        try:
            from backend.services.telegram import get_telegram_service

            await get_telegram_service().delete_account(account_name)
        except Exception as e:
            logger.warning(
                "清理无效 Session 失败: 账号=%s, 错误=%s",
                account_name,
                describe_exception(e),
            )

        # 清理 chats 缓存，避免后续误用旧数据
        try:
            cache_file = self.signs_dir / account_name / "chats_cache.json"
            if cache_file.exists():
                cache_file.unlink()
        except Exception:
            pass

    async def refresh_account_chats(self, account_name: str) -> List[Dict[str, Any]]:
        """
        连接 Telegram 并刷新 Chat 列表
        """
        from pyrogram.enums import ChatType

        # 获取 session 文件路径
        from backend.core.config import get_settings

        settings = get_settings()
        session_dir = settings.resolve_session_dir()
        session_mode = get_session_mode()
        session_string = None
        fallback_session_string = None
        used_fallback_session = False
        session_file = session_dir / f"{account_name}.session"

        if session_mode == "string":
            session_string = (
                get_account_session_string(account_name)
                or load_session_string_file(session_dir, account_name)
            )
            if not session_string:
                raise ValueError(f"账号 {account_name} 登录已失效，请重新登录")
        else:
            fallback_session_string = (
                get_account_session_string(account_name)
                or load_session_string_file(session_dir, account_name)
            )
            if not session_file.exists():
                if fallback_session_string:
                    session_string = fallback_session_string
                    used_fallback_session = True
                else:
                    raise ValueError(f"账号 {account_name} 登录已失效，请重新登录")

        api_runtime = get_telegram_api_runtime_config()
        api_id = api_runtime.api_id
        api_hash = api_runtime.api_hash

        if not api_runtime.is_configured:
            raise ValueError("未配置 Telegram API ID 或 API Hash")

        # 使用 get_client 获取（可能共享的）客户端实例
        proxy_dict = resolve_proxy_dict(account_proxy=get_account_proxy(account_name))
        client_kwargs = {
            "name": account_name,
            "workdir": session_dir,
            "api_id": api_id,
            "api_hash": api_hash,
            "session_string": session_string,
            "in_memory": session_mode == "string",
            "proxy": proxy_dict,
            "no_updates": True,
        }
        client = get_client(**client_kwargs)

        chats: List[Dict[str, Any]] = []
        backend_logger = logging.getLogger("backend")
        try:
            logger.info("开始刷新账号对话列表: 账号=%s", account_name)
            # 初始化账号锁（跨服务共享）
            if account_name not in self._account_locks:
                self._account_locks[account_name] = get_account_lock(account_name)

            account_lock = self._account_locks[account_name]

            async def _fetch_chats(active_client) -> List[Dict[str, Any]]:
                local_chats: List[Dict[str, Any]] = []
                # 使用上下文管理器处理生命周期和锁
                async with account_lock:
                    async with get_global_semaphore():
                        async with active_client:
                            # 尝试获取用户信息，如果失败说明 session 无效
                            await active_client.get_me()

                            try:
                                async for dialog in active_client.get_dialogs():
                                    try:
                                        chat = getattr(dialog, "chat", None)
                                        if chat is None:
                                            backend_logger.warning(
                                                "刷新账号对话时收到空 chat，已跳过: 账号=%s",
                                                account_name,
                                            )
                                            continue
                                        chat_id = getattr(chat, "id", None)
                                        if chat_id is None:
                                            backend_logger.warning(
                                                "刷新账号对话时收到空 chat.id，已跳过: 账号=%s",
                                                account_name,
                                            )
                                            continue

                                        chat_info = {
                                            "id": chat_id,
                                            "title": chat.title
                                            or chat.first_name
                                            or chat.username
                                            or str(chat_id),
                                            "username": chat.username,
                                            "type": chat.type.name.lower(),
                                        }

                                        # 特殊处理机器人和私聊
                                        if chat.type == ChatType.BOT:
                                            chat_info["title"] = f"🤖 {chat_info['title']}"

                                        local_chats.append(chat_info)
                                    except Exception as e:
                                        backend_logger.warning(
                                            "处理对话条目失败，已跳过: 账号=%s, 错误=%s",
                                            account_name,
                                            describe_exception(e),
                                        )
                                        continue
                            except Exception as e:
                                # Pyrogram 边界异常：保留已获取结果
                                backend_logger.warning(
                                    "拉取对话列表被中断，返回已获取结果: 账号=%s, 错误=%s",
                                    account_name,
                                    describe_exception(e),
                                )
                return local_chats

            try:
                chats = await _fetch_chats(client)
            except Exception as e:
                if self._is_invalid_session_error(e):
                    if fallback_session_string and not used_fallback_session:
                        backend_logger.warning(
                            "账号 Session 失效，准备回退到 session_string 重试: 账号=%s, 错误=%s",
                            account_name,
                            describe_exception(e),
                        )
                        try:
                            from tg_signer.core import close_client_by_name

                            await close_client_by_name(account_name, workdir=session_dir)
                        except Exception:
                            pass
                        used_fallback_session = True
                        retry_kwargs = dict(client_kwargs)
                        retry_kwargs["session_string"] = fallback_session_string
                        retry_kwargs["in_memory"] = True
                        retry_kwargs["no_updates"] = True
                        client = get_client(**retry_kwargs)
                        chats = await _fetch_chats(client)
                    else:
                        backend_logger.warning(
                            "账号 Session 已失效，准备清理本地状态: 账号=%s, 错误=%s",
                            account_name,
                            describe_exception(e),
                        )
                        await self._cleanup_invalid_session(account_name)
                        raise ValueError(f"账号 {account_name} 登录已失效，请重新登录")
                else:
                    raise

            # 保存到缓存
            account_dir = self.signs_dir / account_name
            account_dir.mkdir(parents=True, exist_ok=True)
            cache_file = account_dir / "chats_cache.json"

            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(chats, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(
                    "保存账号对话缓存失败: 账号=%s, 缓存文件=%s, 错误=%s",
                    account_name,
                    cache_file,
                    describe_exception(e),
                )

            logger.info(
                "刷新账号对话列表完成: 账号=%s, 对话数量=%s, 是否使用回退会话=%s",
                account_name,
                len(chats),
                used_fallback_session,
            )
            return chats

        except Exception as e:
            # client 上下文管理器会自动处理 disconnect/stop，这里只需要处理业务异常
            logger.exception(
                "刷新账号对话列表失败: 账号=%s, 错误=%s",
                account_name,
                describe_exception(e),
            )
            raise

    async def run_task(self, account_name: str, task_name: str) -> Dict[str, Any]:
        """
        运行签到任务 (兼容接口，内部调用 run_task_with_logs)
        """
        return await self.run_task_with_logs(account_name, task_name)

    def _task_key(self, account_name: str, task_name: str) -> tuple[str, str]:
        return account_name, task_name

    def _find_task_keys(self, task_name: str) -> List[tuple[str, str]]:
        return [key for key in self._active_logs.keys() if key[1] == task_name]

    def get_active_logs(
        self, task_name: str, account_name: Optional[str] = None
    ) -> List[str]:
        """获取正在运行任务的日志"""
        if account_name:
            return self._active_logs.get(self._task_key(account_name, task_name), [])
        # 兼容旧接口：返回第一个同名任务的日志
        for key in self._find_task_keys(task_name):
            return self._active_logs.get(key, [])
        return []

    def append_active_message_event(
        self, account_name: str, task_name: str, event: Dict[str, Any]
    ) -> None:
        normalized_event = self._normalize_message_event(event)
        if normalized_event is None:
            return
        task_key = self._task_key(account_name, task_name)
        next_sequence = self._active_message_event_sequences.get(task_key, 0) + 1
        self._active_message_event_sequences[task_key] = next_sequence
        events = self._active_message_events.setdefault(task_key, [])
        active_event = dict(normalized_event)
        active_event["_sequence"] = next_sequence
        events.append(active_event)
        if (
            self._active_message_event_buffer_limit > 0
            and len(events) > self._active_message_event_buffer_limit
        ):
            del events[:-self._active_message_event_buffer_limit]

    def get_active_message_events(
        self, task_name: str, account_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        events, _latest_sequence = self._get_active_message_event_state(
            task_name, account_name=account_name
        )
        return [self._public_message_event(event) for event in events]

    def get_active_message_events_since(
        self,
        task_name: str,
        account_name: Optional[str] = None,
        after_sequence: int = 0,
    ) -> tuple[List[Dict[str, Any]], int]:
        events, latest_sequence = self._get_active_message_event_state(
            task_name, account_name=account_name
        )
        if after_sequence < 0:
            after_sequence = 0
        new_events = [
            self._public_message_event(event)
            for event in events
            if int(event.get("_sequence", 0) or 0) > after_sequence
        ]
        return new_events, latest_sequence

    def is_task_running(self, task_name: str, account_name: Optional[str] = None) -> bool:
        """检查任务是否正在运行"""
        if account_name:
            return self._active_tasks.get(self._task_key(account_name, task_name), False)
        return any(key[1] == task_name for key, running in self._active_tasks.items() if running)

    def submit_task(self, account_name: str, task_name: str) -> Dict[str, Any]:
        """兼容旧调用方：委托统一后台 Runner 提交。"""
        from backend.services.sign_task_runner import get_sign_task_runner

        return get_sign_task_runner().submit(account_name, task_name)

    async def _run_submitted_task(self, account_name: str, task_name: str) -> None:
        task_key = self._task_key(account_name, task_name)
        status_info = self._task_statuses.setdefault(task_key, {})
        status_info.update(
            {
                "status": "running",
                "message": "任务正在后台执行",
                "started_at": datetime.now().isoformat(),
            }
        )
        try:
            result = await self.run_task_with_logs(account_name, task_name)
            success = bool(result.get("success"))
            status_info.update(
                {
                    "status": "completed" if success else "failed",
                    "message": "任务已完成" if success else result.get("error", "任务执行失败"),
                    "success": success,
                    "error": result.get("error", ""),
                    "output": result.get("output", ""),
                    "finished_at": datetime.now().isoformat(),
                }
            )
        except Exception as exc:
            error_msg = describe_exception(exc)
            self._append_active_log(task_key, f"后台任务执行失败：{error_msg}", level="ERROR")
            status_info.update(
                {
                    "status": "failed",
                    "message": f"任务执行失败：{error_msg}",
                    "success": False,
                    "error": error_msg,
                    "output": "\n".join(self._active_logs.get(task_key, [])),
                    "finished_at": datetime.now().isoformat(),
                }
            )
        finally:
            self._active_tasks[task_key] = False
            self._background_tasks.pop(task_key, None)
            self._background_owned_tasks.discard(task_key)

    def get_task_status(self, account_name: str, task_name: str) -> Dict[str, Any]:
        """获取后台签到任务状态。"""
        task_key = self._task_key(account_name, task_name)
        status_info = dict(self._task_statuses.get(task_key, {}))
        status_value = status_info.get("status", "idle")
        is_running = self._active_tasks.get(task_key, False)
        return {
            "account_name": account_name,
            "task_name": task_name,
            "status": status_value,
            "is_running": is_running,
            "message": status_info.get("message", ""),
            "success": status_info.get("success"),
            "error": status_info.get("error", ""),
            "logs": list(self._active_logs.get(task_key, [])),
            "message_events": self.get_active_message_events(
                task_name,
                account_name=account_name,
            ),
            "submitted_at": status_info.get("submitted_at", ""),
            "started_at": status_info.get("started_at", ""),
            "finished_at": status_info.get("finished_at", ""),
        }

    async def wait_for_background_tasks(self) -> None:
        """等待当前后台签到任务结束，供测试和关闭流程使用。"""
        tasks = [task for task in self._background_tasks.values() if not task.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def run_task_with_logs(
        self,
        account_name: str,
        task_name: str,
        lock_wait_timeout_seconds: Optional[float] = None,
        progress_callback: Optional[Callable[[str, str, str], Awaitable[None]]] = None,
        run_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """运行任务并实时捕获日志 (In-Process)"""

        account_name = str(account_name or "").strip()
        task_name = str(task_name or "").strip()
        if not account_name:
            error_msg = "账号名称不能为空"
            return {
                "success": False,
                "error": error_msg,
                "output": format_log_line(
                    f"执行前校验失败：{error_msg}",
                    level="ERROR",
                    logger_name="backend.sign_tasks",
                ),
            }
        if not task_name:
            error_msg = "任务名称不能为空"
            return {
                "success": False,
                "error": error_msg,
                "output": format_log_line(
                    f"执行前校验失败：{error_msg}",
                    level="ERROR",
                    logger_name="backend.sign_tasks",
                ),
            }

        task_key = self._task_key(account_name, task_name)
        if self.is_task_running(task_name, account_name) and task_key not in self._background_owned_tasks:
            logger.warning(
                "拒绝重复执行签到任务: 账号=%s, 任务=%s",
                account_name,
                task_name,
            )
            return {
                "success": False,
                "error": "任务已经在运行中",
                "output": format_log_line(
                    "检测到同一任务仍在运行，本次执行请求已被拒绝",
                    level="WARNING",
                    logger_name="backend.sign_tasks",
                ),
            }

        # 初始化账号锁（跨服务共享）
        if account_name not in self._account_locks:
            self._account_locks[account_name] = get_account_lock(account_name)

        account_lock = self._account_locks[account_name]

        self._active_tasks[task_key] = True
        self._active_logs[task_key] = []
        self._active_message_events[task_key] = []
        self._active_message_event_sequences[task_key] = 0

        success = False
        error_msg = ""
        output_str = ""
        validation_passed = False
        run_metadata = dict(run_metadata or {})
        run_started_at = ""
        action_completed_at = ""
        run_started_monotonic = time.perf_counter()

        async def report(phase: str, phase_text: str, message: str) -> None:
            nonlocal run_started_at, action_completed_at
            now = datetime.now().isoformat()
            if phase == "preparing" and not run_started_at:
                run_started_at = now
            if phase == "action_completed" and not action_completed_at:
                action_completed_at = now
            self._append_active_log(task_key, message)
            if progress_callback:
                await progress_callback(phase, phase_text, message)

        async def report_from_tg_log(message: str) -> None:
            if not progress_callback:
                return
            if "等待机器人回复" in message:
                await progress_callback("waiting_reply", "等待机器人回复", message)
            elif "已收到机器人回复" in message:
                await progress_callback("running_action", "执行任务动作中", message)

        def schedule_progress_from_tg_log(message: str) -> None:
            if not progress_callback:
                return
            if "等待机器人回复" not in message and "已收到机器人回复" not in message:
                return
            asyncio.create_task(report_from_tg_log(message))

        @asynccontextmanager
        async def acquire_account_lock():
            acquired = False
            try:
                if lock_wait_timeout_seconds is None:
                    await account_lock.acquire()
                else:
                    await asyncio.wait_for(
                        account_lock.acquire(), timeout=lock_wait_timeout_seconds
                    )
                acquired = True
                yield
            except asyncio.TimeoutError as exc:
                timeout_text = f"{lock_wait_timeout_seconds:g}"
                message = (
                    "等待账号空闲超时，任务已取消。"
                    f"已等待 {timeout_text} 秒，请查看前序任务实时日志或稍后重试。"
                )
                self._append_active_log(task_key, message, level="ERROR")
                raise TimeoutError(message) from exc
            finally:
                if acquired:
                    account_lock.release()

        # 获取 logger 实例
        tg_logger = logging.getLogger("tg-signer")
        log_handler = TaskLogHandler(
            self._active_logs[task_key], on_log=schedule_progress_from_tg_log
        )
        log_handler.setLevel(logging.INFO)
        log_handler.setFormatter(build_formatter(include_source=False))
        tg_logger.addHandler(log_handler)

        try:
            self._append_active_log(
                task_key,
                f"开始执行签到任务: 账号={account_name}, 任务={task_name}",
            )
            logger.info("开始执行签到任务: 账号=%s, 任务=%s", account_name, task_name)

            task_cfg = self.get_task(task_name, account_name=account_name)
            if not task_cfg:
                raise ValueError("未找到签到任务配置")

            self._append_active_log(task_key, "任务配置校验通过")

            if account_lock.locked():
                self._append_active_log(
                    task_key,
                    "检测到账号执行锁已被占用，当前任务将排队等待前序任务完成",
                    level="WARNING",
                )

            async with acquire_account_lock():
                await report("preparing", "准备执行", "已获取账号执行锁，开始准备运行环境")
                last_end = self._account_last_run_end.get(account_name)
                if last_end:
                    gap = time.time() - last_end
                    wait_seconds = self._account_cooldown_seconds - gap
                    if wait_seconds > 0:
                        self._append_active_log(
                            task_key,
                            f"账号仍在冷却期，等待 {int(wait_seconds)} 秒后继续执行",
                        )
                        await asyncio.sleep(wait_seconds)

                api_runtime = get_telegram_api_runtime_config()
                api_id = api_runtime.api_id
                api_hash = api_runtime.api_hash

                if not api_runtime.is_configured:
                    raise ValueError(
                        "Telegram API 未配置，请先在系统设置中填写 API ID 和 API Hash"
                    )

                session_dir = settings.resolve_session_dir()
                session_mode = get_session_mode()
                session_string = None
                use_in_memory = False
                proxy_dict = resolve_proxy_dict(
                    account_proxy=get_account_proxy(account_name)
                )
                self._append_active_log(
                    task_key,
                    f"当前会话模式：{'session_string' if session_mode == 'string' else 'session 文件'}",
                )
                if proxy_dict:
                    self._append_active_log(task_key, "检测到账号代理配置，执行时将通过代理连接")
                else:
                    self._append_active_log(task_key, "未检测到账号代理配置，将使用直连模式")

                if session_mode == "string":
                    session_string = (
                        get_account_session_string(account_name)
                        or load_session_string_file(session_dir, account_name)
                    )
                    if not session_string:
                        raise ValueError(
                            f"账号 {account_name} 未找到有效的 session_string，请重新登录"
                        )
                    use_in_memory = True
                else:
                    session_string = None
                    use_in_memory = False

                    if get_sign_task_runtime_config().force_in_memory:
                        session_string = load_session_string_file(
                            session_dir, account_name
                        )
                        use_in_memory = bool(session_string)
                        if use_in_memory:
                            self._append_active_log(
                                task_key,
                                "已启用强制内存 Session 模式，并成功加载 session_string",
                            )
                        else:
                            self._append_active_log(
                                task_key,
                                "已启用强制内存 Session 模式，但未找到 session_string，将继续使用文件 Session",
                                level="WARNING",
                            )

                requires_updates = self._task_requires_updates(task_cfg)
                signer_no_updates = not requires_updates
                self._append_active_log(
                    task_key,
                    f"消息更新监听：{'开启' if requires_updates else '关闭'}",
                )
                validation_passed = True

                # 实例化 UserSigner (使用 BackendUserSigner)
                # 注意: UserSigner 内部会使用 get_client 复用 client
                async def handle_message_event(event: Dict[str, Any]) -> None:
                    self.append_active_message_event(account_name, task_name, event)

                    await report("preparing", "准备执行", "正在初始化签到执行器")
                signer = BackendUserSigner(
                    task_name=task_name,
                    session_dir=str(session_dir),
                    account=account_name,
                    workdir=self.workdir,
                    proxy=proxy_dict,
                    session_string=session_string,
                    in_memory=use_in_memory,
                    api_id=api_id,
                    api_hash=api_hash,
                    no_updates=signer_no_updates,
                    message_event_callback=handle_message_event,
                )

                # 执行任务（数据库锁冲突时重试）
                async with get_global_semaphore():
                    await report("running_action", "执行任务动作中", "正在执行 Telegram 签到动作")
                    self._append_active_log(task_key, "已获取全局执行信号量，准备开始任务动作")
                    max_retries = 3
                    for attempt in range(max_retries):
                        current_attempt = attempt + 1
                        self._append_active_log(
                            task_key, f"准备进行第 {current_attempt} 次执行尝试"
                        )
                        try:
                            await signer.run_once(num_of_dialogs=20)
                            self._append_active_log(
                                task_key, f"第 {current_attempt} 次执行尝试已完成"
                            )
                            break
                        except Exception as e:
                            if "database is locked" in str(e).lower():
                                if attempt < max_retries - 1:
                                    delay = (attempt + 1) * 3
                                    self._append_active_log(
                                        task_key,
                                        f"检测到 Session 数据库锁，将在 {delay} 秒后重试",
                                        level="WARNING",
                                    )
                                    logger.warning(
                                        "签到任务执行遇到数据库锁: 账号=%s, 任务=%s, 尝试次数=%s/%s, 错误=%s",
                                        account_name,
                                        task_name,
                                        current_attempt,
                                        max_retries,
                                        describe_exception(e),
                                    )
                                    await asyncio.sleep(delay)
                                    continue
                            self._append_active_log(
                                task_key,
                                f"第 {current_attempt} 次执行尝试失败：{describe_exception(e)}",
                                level="ERROR",
                            )
                            raise

                success = True
                await report(
                    "action_completed",
                    "任务动作已完成",
                    "任务动作已完成，正在执行收尾动作",
                )

                # 增加缓冲时间，防止同账号连续执行任务时，Session文件锁尚未完全释放导致 "database is locked"
                self._append_active_log(task_key, "签到任务执行完成")

        except Exception as e:
            error_detail = describe_exception(e)
            phase = "任务执行异常" if validation_passed else "执行前校验失败"
            error_msg = f"{phase}：{error_detail}"
            self._append_active_log(task_key, error_msg, level="ERROR")
            logger.exception(
                "签到任务执行失败: 账号=%s, 任务=%s, 阶段=%s, 错误=%s",
                account_name,
                task_name,
                phase,
                error_detail,
            )
        finally:
            self._account_last_run_end[account_name] = time.time()
            self._active_tasks[task_key] = False
            if log_handler in tg_logger.handlers:
                tg_logger.removeHandler(log_handler)

            if progress_callback:
                try:
                    await progress_callback(
                        "cleanup",
                        "收尾处理中",
                        "正在保存历史并发送完成通知",
                    )
                except Exception:
                    logger.exception("签到任务进度回调失败: 阶段=cleanup")

            # 保存执行记录
            final_logs = list(self._active_logs.get(task_key, []))
            final_message_events = list(self._active_message_events.get(task_key, []))
            output_str = "\n".join(final_logs)

            last_reply = ""
            if success:
                last_reply = self._latest_message_summary(final_message_events)

            msg = error_msg if not success else (last_reply or "任务执行完成")
            finished_at = datetime.now()
            duration_seconds = round(time.perf_counter() - run_started_monotonic, 3)
            history_metadata = {
                **run_metadata,
                "status": "completed" if success else "failed",
                "status_text": "任务已完成" if success else "执行失败",
                "started_at": run_metadata.get("started_at") or run_started_at,
                "action_completed_at": run_metadata.get("action_completed_at")
                or action_completed_at,
                "finished_at": finished_at.isoformat(),
                "duration_seconds": duration_seconds,
            }
            self._save_run_info(
                task_name,
                success,
                msg,
                account_name,
                flow_logs=final_logs,
                message_events=final_message_events,
                run_metadata=history_metadata,
            )
            dispatch_notification(
                get_notification_service().send_sign_task_completion(
                    task_name=task_name,
                    account_name=account_name,
                    success=success,
                    summary=msg,
                    output=output_str,
                    message_events=final_message_events,
                    finished_at=finished_at,
                ),
                logger=logger,
                description=f"发送签到任务完成通知失败: 账号={account_name}, 任务={task_name}",
            )

            if progress_callback:
                try:
                    final_phase = "completed" if success else "failed"
                    final_text = "任务已完成" if success else "执行失败"
                    await progress_callback(final_phase, final_text, msg)
                except Exception:
                    logger.exception("签到任务进度回调失败: 阶段=completed")

            # 延迟清理日志（同一 task_key 仅保留一个 cleanup 协程）
            old_cleanup_task = self._cleanup_tasks.get(task_key)
            if old_cleanup_task and not old_cleanup_task.done():
                old_cleanup_task.cancel()

            async def cleanup():
                try:
                    await asyncio.sleep(60)
                    if not self._active_tasks.get(task_key):
                        self._active_logs.pop(task_key, None)
                        self._active_message_events.pop(task_key, None)
                        self._active_message_event_sequences.pop(task_key, None)
                finally:
                    self._cleanup_tasks.pop(task_key, None)

            self._cleanup_tasks[task_key] = asyncio.create_task(cleanup())

        return {
            "success": success,
            "output": output_str,
            "error": error_msg,
        }


# 创建全局实例
_sign_task_service: Optional[SignTaskService] = None


def get_sign_task_service() -> SignTaskService:
    global _sign_task_service
    if _sign_task_service is None:
        _sign_task_service = SignTaskService()
    return _sign_task_service
