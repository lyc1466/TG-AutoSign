from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_SESSION_MODE_FILE = "file"
_SESSION_MODE_STRING = "string"
_DEFAULT_ADMIN_PASSWORD = "admin123"
_DEFAULT_SECRET_KEY = "tg-signer-default-secret-key-please-change-in-production-2024"
_DEFAULT_DATA_DIR_OVERRIDE_FILE = Path.cwd() / ".tg_signpulse_data_dir"


def _read_str_env(name: str) -> Optional[str]:
    value = os.getenv(name)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _read_bool_env(*names: str, default: bool = False) -> bool:
    for name in names:
        value = _read_str_env(name)
        if value is None:
            continue
        return value.lower() in {"1", "true", "yes", "on"}
    return default


def _read_positive_int_env(name: str, default: int, minimum: int = 1) -> int:
    value = _read_str_env(name)
    if value is None:
        return default
    try:
        return max(int(value), minimum)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class SessionRuntimeConfig:
    mode: str
    no_updates: bool
    global_concurrency: int


@dataclass(frozen=True)
class SignTaskRuntimeConfig:
    account_cooldown_seconds: int
    force_in_memory: bool
    history_max_entries: int
    history_max_flow_lines: int
    history_max_line_chars: int


@dataclass(frozen=True)
class TelegramApiRuntimeConfig:
    api_id: Optional[int]
    api_hash: Optional[str]
    is_configured: bool


@dataclass(frozen=True)
class AuthRuntimeConfig:
    totp_valid_window: int
    initial_admin_password: str


@dataclass(frozen=True)
class AppRuntimeConfig:
    app_name: str
    host: str
    secret_key: str
    access_token_expire_hours: int
    timezone: str


@dataclass(frozen=True)
class StorageRuntimeConfig:
    data_dir_override_file: Path


@dataclass(frozen=True)
class ProxyRuntimeConfig:
    global_proxy: Optional[str]


@dataclass(frozen=True)
class TGClientDeviceRuntimeConfig:
    device_model: str
    system_version: str
    app_version: str
    lang_code: str


@dataclass(frozen=True)
class LegacySignerRuntimeConfig:
    workdir: Path
    gui_auth_code: Optional[str]
    server_chan_send_key: Optional[str]
    pyrogram_log_enabled: bool


def get_session_runtime_config() -> SessionRuntimeConfig:
    mode = (_read_str_env("TG_SESSION_MODE") or _SESSION_MODE_FILE).lower()
    if mode != _SESSION_MODE_STRING:
        mode = _SESSION_MODE_FILE
    return SessionRuntimeConfig(
        mode=mode,
        no_updates=_read_bool_env("TG_SESSION_NO_UPDATES", "TG_NO_UPDATES"),
        global_concurrency=_read_positive_int_env("TG_GLOBAL_CONCURRENCY", 1, 1),
    )


def get_sign_task_runtime_config() -> SignTaskRuntimeConfig:
    return SignTaskRuntimeConfig(
        account_cooldown_seconds=_read_positive_int_env(
            "SIGN_TASK_ACCOUNT_COOLDOWN", 5, 1
        ),
        force_in_memory=_read_bool_env("SIGN_TASK_FORCE_IN_MEMORY"),
        history_max_entries=_read_positive_int_env(
            "SIGN_TASK_HISTORY_MAX_ENTRIES", 100, 10
        ),
        history_max_flow_lines=_read_positive_int_env(
            "SIGN_TASK_HISTORY_MAX_FLOW_LINES", 200, 20
        ),
        history_max_line_chars=_read_positive_int_env(
            "SIGN_TASK_HISTORY_MAX_LINE_CHARS", 500, 80
        ),
    )


def get_telegram_api_runtime_config() -> TelegramApiRuntimeConfig:
    config = get_config_service().get_telegram_config()
    api_id_raw = config.get("api_id")
    api_hash_raw = config.get("api_hash")

    try:
        api_id = int(api_id_raw) if api_id_raw is not None else None
    except (TypeError, ValueError):
        api_id = None

    api_hash = api_hash_raw.strip() if isinstance(api_hash_raw, str) else None
    if api_hash == "":
        api_hash = None

    return TelegramApiRuntimeConfig(
        api_id=api_id,
        api_hash=api_hash,
        is_configured=bool(api_id and api_hash),
    )


def get_auth_runtime_config() -> AuthRuntimeConfig:
    valid_window = _read_positive_int_env("APP_TOTP_VALID_WINDOW", 1, 0)
    admin_password = _read_str_env("ADMIN_PASSWORD") or _DEFAULT_ADMIN_PASSWORD
    return AuthRuntimeConfig(
        totp_valid_window=valid_window,
        initial_admin_password=admin_password,
    )


def get_app_runtime_config() -> AppRuntimeConfig:
    return AppRuntimeConfig(
        app_name=_read_str_env("APP_APP_NAME") or "tg-signer-panel",
        host=_read_str_env("APP_HOST") or "127.0.0.1",
        secret_key=_read_str_env("APP_SECRET_KEY") or _DEFAULT_SECRET_KEY,
        access_token_expire_hours=_read_positive_int_env(
            "APP_ACCESS_TOKEN_EXPIRE_HOURS", 12, 1
        ),
        timezone=_read_str_env("TZ") or "Asia/Hong_Kong",
    )


def get_storage_runtime_config() -> StorageRuntimeConfig:
    override_file = _read_str_env("APP_DATA_DIR_OVERRIDE_FILE")
    return StorageRuntimeConfig(
        data_dir_override_file=(
            Path(override_file).expanduser()
            if override_file
            else _DEFAULT_DATA_DIR_OVERRIDE_FILE
        ),
    )


def get_proxy_runtime_config() -> ProxyRuntimeConfig:
    return ProxyRuntimeConfig(global_proxy=_read_str_env("TG_PROXY"))


def get_config_service():
    from backend.services.config import get_config_service as _get_config_service

    return _get_config_service()


def get_tg_client_device_runtime_config() -> TGClientDeviceRuntimeConfig:
    return TGClientDeviceRuntimeConfig(
        device_model=_read_str_env("TG_DEVICE_MODEL") or "Samsung Galaxy S24",
        system_version=_read_str_env("TG_SYSTEM_VERSION") or "SDK 35",
        app_version=_read_str_env("TG_APP_VERSION") or "11.4.2",
        lang_code=_read_str_env("TG_LANG_CODE") or "zh",
    )


def get_legacy_signer_runtime_config() -> LegacySignerRuntimeConfig:
    return LegacySignerRuntimeConfig(
        workdir=Path(_read_str_env("TG_SIGNER_WORKDIR") or ".signer").expanduser(),
        gui_auth_code=_read_str_env("TG_SIGNER_GUI_AUTHCODE"),
        server_chan_send_key=_read_str_env("SERVER_CHAN_SEND_KEY"),
        pyrogram_log_enabled=_read_bool_env("PYROGRAM_LOG_ON"),
    )