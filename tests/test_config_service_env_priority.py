import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.services.config as config_module  # noqa: E402


def _make_service(monkeypatch, tmp_path):
    monkeypatch.setattr(
        config_module,
        "settings",
        SimpleNamespace(resolve_workdir=lambda: tmp_path),
    )
    return config_module.ConfigService()


def test_get_ai_config_ignores_environment_without_ui_file(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")

    service = _make_service(monkeypatch, tmp_path)

    assert service.get_ai_config() is None


def test_get_ai_config_prefers_ui_file_over_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("OPENAI_MODEL", "env-model")

    service = _make_service(monkeypatch, tmp_path)
    config_path = service._get_ai_config_file()
    config_path.write_text(
        '{"api_key": "sk-file-key", "base_url": "https://file.example/v1", "model": "file-model"}',
        encoding="utf-8",
    )

    assert service.get_ai_config() == {
        "api_key": "sk-file-key",
        "base_url": "https://file.example/v1",
        "model": "file-model",
    }


def test_get_telegram_config_uses_environment_without_ui_file(monkeypatch, tmp_path):
    monkeypatch.setenv("TG_API_ID", "123456")
    monkeypatch.setenv("TG_API_HASH", "env-hash")

    service = _make_service(monkeypatch, tmp_path)

    assert service.get_telegram_config() == {
        "api_id": "123456",
        "api_hash": "env-hash",
        "is_custom": True,
    }


def test_get_telegram_config_prefers_ui_file_over_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("TG_API_ID", "123456")
    monkeypatch.setenv("TG_API_HASH", "env-hash")

    service = _make_service(monkeypatch, tmp_path)
    config_path = service._get_telegram_config_file()
    config_path.write_text(
        '{"api_id": "999999", "api_hash": "file-hash"}',
        encoding="utf-8",
    )

    assert service.get_telegram_config() == {
        "api_id": "999999",
        "api_hash": "file-hash",
        "is_custom": True,
    }
