import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from types import SimpleNamespace


def test_session_runtime_config_reads_mode_no_updates_and_concurrency(monkeypatch):
    from backend.core.runtime_config import get_session_runtime_config

    monkeypatch.setenv("TG_SESSION_MODE", "string")
    monkeypatch.setenv("TG_SESSION_NO_UPDATES", "true")
    monkeypatch.setenv("TG_GLOBAL_CONCURRENCY", "3")

    runtime = get_session_runtime_config()

    assert runtime.mode == "string"
    assert runtime.no_updates is True
    assert runtime.global_concurrency == 3


def test_sign_task_runtime_config_reads_limits_and_force_in_memory(monkeypatch):
    from backend.core.runtime_config import get_sign_task_runtime_config

    monkeypatch.setenv("SIGN_TASK_ACCOUNT_COOLDOWN", "9")
    monkeypatch.setenv("SIGN_TASK_FORCE_IN_MEMORY", "1")
    monkeypatch.setenv("SIGN_TASK_HISTORY_MAX_ENTRIES", "150")
    monkeypatch.setenv("SIGN_TASK_HISTORY_MAX_FLOW_LINES", "320")
    monkeypatch.setenv("SIGN_TASK_HISTORY_MAX_LINE_CHARS", "640")

    runtime = get_sign_task_runtime_config()

    assert runtime.account_cooldown_seconds == 9
    assert runtime.force_in_memory is True
    assert runtime.history_max_entries == 150
    assert runtime.history_max_flow_lines == 320
    assert runtime.history_max_line_chars == 640


def test_telegram_api_runtime_config_uses_config_service(monkeypatch):
    from backend.core import runtime_config as runtime_module

    monkeypatch.setattr(
        runtime_module,
        "get_config_service",
        lambda: SimpleNamespace(
            get_telegram_config=lambda: {
                "api_id": "123456",
                "api_hash": "hash-from-config-service",
            }
        ),
    )

    runtime = runtime_module.get_telegram_api_runtime_config()

    assert runtime.api_id == 123456
    assert runtime.api_hash == "hash-from-config-service"
    assert runtime.is_configured is True


def test_auth_runtime_config_reads_totp_window_and_admin_password(monkeypatch):
    from backend.core.runtime_config import get_auth_runtime_config

    monkeypatch.setenv("APP_TOTP_VALID_WINDOW", "2")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-from-env")

    runtime = get_auth_runtime_config()

    assert runtime.totp_valid_window == 2
    assert runtime.initial_admin_password == "admin-from-env"


def test_app_runtime_config_reads_app_fields(monkeypatch):
    from backend.core.runtime_config import get_app_runtime_config

    monkeypatch.setenv("APP_APP_NAME", "TG-AutoSign")
    monkeypatch.setenv("APP_HOST", "0.0.0.0")
    monkeypatch.setenv("APP_SECRET_KEY", "secret-from-env")
    monkeypatch.setenv("APP_ACCESS_TOKEN_EXPIRE_HOURS", "24")
    monkeypatch.setenv("TZ", "Asia/Shanghai")

    runtime = get_app_runtime_config()

    assert runtime.app_name == "TG-AutoSign"
    assert runtime.host == "0.0.0.0"
    assert runtime.secret_key == "secret-from-env"
    assert runtime.access_token_expire_hours == 24
    assert runtime.timezone == "Asia/Shanghai"


def test_storage_runtime_config_reads_data_dir_and_override_file(monkeypatch):
    from backend.core.runtime_config import get_storage_runtime_config

    monkeypatch.setenv("APP_DATA_DIR_OVERRIDE_FILE", "/srv/data/.override")

    runtime = get_storage_runtime_config()

    assert runtime.data_dir_override_file.as_posix() == "/srv/data/.override"


def test_proxy_runtime_config_reads_global_proxy(monkeypatch):
    from backend.core.runtime_config import get_proxy_runtime_config

    monkeypatch.setenv("TG_PROXY", "127.0.0.1:1080")

    runtime = get_proxy_runtime_config()

    assert runtime.global_proxy == "127.0.0.1:1080"


def test_tg_client_device_runtime_config_reads_device_fields(monkeypatch):
    from backend.core.runtime_config import get_tg_client_device_runtime_config

    monkeypatch.setenv("TG_DEVICE_MODEL", "Vivo X100s")
    monkeypatch.setenv("TG_SYSTEM_VERSION", "SDK 35")
    monkeypatch.setenv("TG_APP_VERSION", "11.4.2")
    monkeypatch.setenv("TG_LANG_CODE", "zh")

    runtime = get_tg_client_device_runtime_config()

    assert runtime.device_model == "Vivo X100s"
    assert runtime.system_version == "SDK 35"
    assert runtime.app_version == "11.4.2"
    assert runtime.lang_code == "zh"


def test_legacy_signer_runtime_config_reads_workdir_gui_and_logging(monkeypatch):
    from backend.core.runtime_config import get_legacy_signer_runtime_config

    monkeypatch.setenv("TG_SIGNER_WORKDIR", ".signer")
    monkeypatch.setenv("TG_SIGNER_GUI_AUTHCODE", "auth-code")
    monkeypatch.setenv("SERVER_CHAN_SEND_KEY", "send-key")
    monkeypatch.setenv("PYROGRAM_LOG_ON", "1")

    runtime = get_legacy_signer_runtime_config()

    assert runtime.workdir.as_posix().endswith('.signer')
    assert runtime.gui_auth_code == "auth-code"
    assert runtime.server_chan_send_key == "send-key"
    assert runtime.pyrogram_log_enabled is True