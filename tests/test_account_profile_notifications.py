import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import backend.services.telegram as telegram_module
import backend.utils.tg_session as tg_session_module


def _load_accounts_routes_module():
    module_path = Path(__file__).resolve().parents[1] / "backend" / "api" / "routes" / "accounts.py"
    spec = importlib.util.spec_from_file_location("accounts_routes_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.AccountUpdateRequest.update_forward_refs()
    return module


def _patch_session_dir(monkeypatch, tmp_path):
    settings = SimpleNamespace(resolve_session_dir=lambda: tmp_path)
    monkeypatch.setattr(tg_session_module, "get_settings", lambda: settings)
    monkeypatch.setattr(telegram_module, "settings", settings)


def test_set_account_profile_persists_notification_fields(monkeypatch, tmp_path):
    _patch_session_dir(monkeypatch, tmp_path)

    tg_session_module.set_account_profile(
        "alice",
        notification_channel="custom",
        notification_bot_token="123456:test-token",
        notification_chat_id="-100100200300",
    )

    profile = tg_session_module.get_account_profile("alice")

    assert profile["notification_channel"] == "custom"
    assert profile["notification_bot_token"] == "123456:test-token"
    assert profile["notification_chat_id"] == "-100100200300"


def test_set_account_profile_rejects_invalid_notification_channel(monkeypatch, tmp_path):
    _patch_session_dir(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="notification_channel"):
        tg_session_module.set_account_profile(
            "alice",
            notification_channel="invalid",
        )


def test_list_accounts_exposes_masked_notification_metadata(monkeypatch, tmp_path):
    _patch_session_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(telegram_module, "is_string_session_mode", lambda: True)
    monkeypatch.setattr(telegram_module, "_login_sessions", {})
    monkeypatch.setattr(telegram_module, "_qr_login_sessions", {})

    (tmp_path / "alice.session_string").write_text("session-string", encoding="utf-8")
    tg_session_module.set_account_profile(
        "alice",
        remark="主账号",
        proxy="socks5://127.0.0.1:1080",
        notification_channel="custom",
        notification_bot_token="123456:test-token",
        notification_chat_id="-100100200300",
    )

    service = telegram_module.TelegramService()
    account = next(
        item for item in service.list_accounts(force_refresh=True) if item["name"] == "alice"
    )

    assert account["remark"] == "主账号"
    assert account["proxy"] == "socks5://127.0.0.1:1080"
    assert account["notification_channel"] == "custom"
    assert account["notification_has_custom_token"] is True
    assert account["notification_bot_token_masked"] == "1234*********oken"
    assert account["notification_chat_id"] == "-100100200300"
    assert "notification_bot_token" not in account


def test_update_account_returns_400_for_invalid_notification_channel(monkeypatch):
    account_routes = _load_accounts_routes_module()
    monkeypatch.setattr(
        account_routes,
        "get_telegram_service",
        lambda: SimpleNamespace(
            account_exists=lambda _account_name: True,
            list_accounts=lambda force_refresh=False: [],
        ),
    )

    def raise_value_error(*args, **kwargs):
        raise ValueError("notification_channel must be one of: global, custom, disabled")

    monkeypatch.setattr(tg_session_module, "set_account_profile", raise_value_error)

    with pytest.raises(HTTPException) as exc_info:
        account_routes.update_account(
            "alice",
            account_routes.AccountUpdateRequest(notification_channel="invalid"),
            current_user=SimpleNamespace(username="tester"),
        )

    assert exc_info.value.status_code == 400
    assert "notification_channel" in str(exc_info.value.detail)
