import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import backend.services.config as config_module


def _load_config_routes_module():
    module_path = Path(__file__).resolve().parents[1] / "backend" / "api" / "routes" / "config.py"
    spec = importlib.util.spec_from_file_location("config_routes_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _make_service(monkeypatch, tmp_path):
    monkeypatch.setattr(
        config_module,
        "settings",
        SimpleNamespace(resolve_workdir=lambda: tmp_path),
    )
    return config_module.ConfigService()


def test_get_telegram_notification_config_returns_none_without_file(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)

    assert service.get_telegram_notification_config() is None


def test_save_and_get_telegram_notification_config(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)

    saved = service.save_telegram_notification_config(
        bot_token="123456:test-token",
        chat_id="-1001234567890",
    )

    assert saved == {
        "bot_token": "123456:test-token",
        "chat_id": "-1001234567890",
    }
    assert service.get_telegram_notification_config() == saved


def test_save_telegram_notification_config_keeps_existing_token(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)
    service.save_telegram_notification_config(
        bot_token="123456:test-token",
        chat_id="-1001234567890",
    )

    saved = service.save_telegram_notification_config(
        bot_token=None,
        chat_id="-100999888777",
        keep_existing_token=True,
    )

    assert saved == {
        "bot_token": "123456:test-token",
        "chat_id": "-100999888777",
    }


def test_save_telegram_notification_config_requires_token_for_new_config(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="bot token"):
        service.save_telegram_notification_config(
            bot_token=None,
            chat_id="-1001234567890",
            keep_existing_token=True,
        )


def test_delete_telegram_notification_config_removes_file(monkeypatch, tmp_path):
    service = _make_service(monkeypatch, tmp_path)
    service.save_telegram_notification_config(
        bot_token="123456:test-token",
        chat_id="-1001234567890",
    )

    assert service.delete_telegram_notification_config() is True
    assert service.get_telegram_notification_config() is None


def test_test_telegram_notification_config_masks_internal_errors(monkeypatch):
    config_routes = _load_config_routes_module()
    monkeypatch.setattr(
        config_routes,
        "get_config_service",
        lambda: SimpleNamespace(
            get_telegram_notification_config=lambda: {
                "bot_token": "123456:test-token",
                "chat_id": "-1001234567890",
            }
        ),
    )

    async def raise_runtime_error():
        raise RuntimeError("sensitive upstream detail")

    monkeypatch.setattr(
        config_routes,
        "get_notification_service",
        lambda: SimpleNamespace(send_test_message=raise_runtime_error),
    )

    response = asyncio.run(
        config_routes.test_telegram_notification_config(
            current_user=SimpleNamespace(username="tester")
        )
    )

    assert response.success is False
    assert response.message == "Telegram notification test failed"
    assert "sensitive" not in response.message

