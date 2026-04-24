from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from backend.core.config import get_settings
from backend.core.runtime_config import get_session_runtime_config

_GLOBAL_SEMAPHORE: Optional[asyncio.Semaphore] = None
_VALID_NOTIFICATION_CHANNELS = {"global", "custom", "disabled"}


def get_session_mode() -> str:
    return get_session_runtime_config().mode


def is_string_session_mode() -> bool:
    return get_session_mode() == "string"


def get_no_updates_flag() -> bool:
    return get_session_runtime_config().no_updates


def get_global_semaphore() -> asyncio.Semaphore:
    global _GLOBAL_SEMAPHORE
    if _GLOBAL_SEMAPHORE is None:
        limit = get_session_runtime_config().global_concurrency
        _GLOBAL_SEMAPHORE = asyncio.Semaphore(limit)
    return _GLOBAL_SEMAPHORE


def _account_store_path() -> Path:
    settings = get_settings()
    session_dir = settings.resolve_session_dir()
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir / "accounts.json"


def _load_account_store() -> dict:
    path = _account_store_path()
    if not path.exists():
        return {"accounts": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"accounts": {}}
    if not isinstance(data, dict):
        return {"accounts": {}}
    accounts = data.get("accounts")
    if not isinstance(accounts, dict):
        data["accounts"] = {}
    return data


def _save_account_store(data: dict) -> None:
    path = _account_store_path()
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tmp_path.replace(path)


def list_account_names() -> list[str]:
    data = _load_account_store()
    accounts = data.get("accounts", {})
    if not isinstance(accounts, dict):
        return []
    return sorted(accounts.keys())


def get_account_session_string(account_name: str) -> Optional[str]:
    data = _load_account_store()
    entry = data.get("accounts", {}).get(account_name)
    if not isinstance(entry, dict):
        return None
    session_string = entry.get("session_string")
    if isinstance(session_string, str) and session_string.strip():
        return session_string.strip()
    return None


def set_account_session_string(account_name: str, session_string: str) -> None:
    data = _load_account_store()
    accounts = data.get("accounts")
    if not isinstance(accounts, dict):
        accounts = {}
        data["accounts"] = accounts
    entry = accounts.get(account_name)
    if not isinstance(entry, dict):
        entry = {}
    entry["session_string"] = session_string.strip()
    entry["updated_at"] = datetime.utcnow().isoformat()
    accounts[account_name] = entry
    _save_account_store(data)


def delete_account_session_string(account_name: str) -> None:
    data = _load_account_store()
    accounts = data.get("accounts")
    if isinstance(accounts, dict) and account_name in accounts:
        accounts.pop(account_name, None)
        _save_account_store(data)


def get_account_profile(account_name: str) -> dict[str, Any]:
    data = _load_account_store()
    entry = data.get("accounts", {}).get(account_name)
    if not isinstance(entry, dict):
        return {}
    notification_channel = entry.get("notification_channel")
    if notification_channel not in _VALID_NOTIFICATION_CHANNELS:
        notification_channel = "global"
    return {
        "remark": entry.get("remark"),
        "proxy": entry.get("proxy"),
        "notification_channel": notification_channel,
        "notification_bot_token": entry.get("notification_bot_token"),
        "notification_chat_id": entry.get("notification_chat_id"),
    }


def get_account_proxy(account_name: str) -> Optional[str]:
    profile = get_account_profile(account_name)
    proxy = profile.get("proxy")
    if isinstance(proxy, str) and proxy.strip():
        return proxy.strip()
    return None


def get_account_remark(account_name: str) -> Optional[str]:
    profile = get_account_profile(account_name)
    remark = profile.get("remark")
    if isinstance(remark, str) and remark.strip():
        return remark.strip()
    return None


def set_account_profile(
    account_name: str,
    *,
    remark: Optional[str] = None,
    proxy: Optional[str] = None,
    notification_channel: Optional[str] = None,
    notification_bot_token: Optional[str] = None,
    notification_chat_id: Optional[str] = None,
) -> None:
    data = _load_account_store()
    accounts = data.get("accounts")
    if not isinstance(accounts, dict):
        accounts = {}
        data["accounts"] = accounts
    entry = accounts.get(account_name)
    if not isinstance(entry, dict):
        entry = {}
    if remark is not None:
        entry["remark"] = remark.strip() if isinstance(remark, str) else remark
    if proxy is not None:
        entry["proxy"] = proxy.strip() if isinstance(proxy, str) else proxy
    if notification_channel is not None:
        normalized_channel = (
            notification_channel.strip()
            if isinstance(notification_channel, str)
            else notification_channel
        )
        if normalized_channel not in _VALID_NOTIFICATION_CHANNELS:
            raise ValueError(
                "notification_channel must be one of: global, custom, disabled"
            )
        entry["notification_channel"] = normalized_channel
    if notification_bot_token is not None:
        entry["notification_bot_token"] = (
            notification_bot_token.strip()
            if isinstance(notification_bot_token, str)
            else notification_bot_token
        )
    if notification_chat_id is not None:
        entry["notification_chat_id"] = (
            notification_chat_id.strip()
            if isinstance(notification_chat_id, str)
            else notification_chat_id
        )
    entry["updated_at"] = datetime.utcnow().isoformat()
    accounts[account_name] = entry
    _save_account_store(data)


def session_string_file_path(session_dir: Path, account_name: str) -> Path:
    return session_dir / f"{account_name}.session_string"


def load_session_string_file(session_dir: Path, account_name: str) -> Optional[str]:
    path = session_string_file_path(session_dir, account_name)
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    return content or None


def save_session_string_file(
    session_dir: Path, account_name: str, session_string: str
) -> None:
    path = session_string_file_path(session_dir, account_name)
    path.write_text(session_string.strip(), encoding="utf-8")


def delete_session_string_file(session_dir: Path, account_name: str) -> None:
    path = session_string_file_path(session_dir, account_name)
    if path.exists():
        try:
            path.unlink()
        except Exception:
            pass
