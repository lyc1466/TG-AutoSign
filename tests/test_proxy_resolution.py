import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backend.services.telegram as telegram_module
from backend.utils import proxy as proxy_utils


def test_resolve_proxy_dict_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("TG_PROXY", "127.0.0.1:1080")

    proxy = proxy_utils.resolve_proxy_dict()

    assert proxy == {
        "scheme": "socks5",
        "hostname": "127.0.0.1",
        "port": 1080,
    }


def test_resolve_proxy_dict_prefers_explicit_over_account_and_env(monkeypatch):
    monkeypatch.setenv("TG_PROXY", "127.0.0.1:1080")

    proxy = proxy_utils.resolve_proxy_dict(
        explicit_proxy="socks5://10.0.0.8:9000",
        account_proxy="socks5://192.168.1.2:7890",
    )

    assert proxy == {
        "scheme": "socks5",
        "hostname": "10.0.0.8",
        "port": 9000,
    }


class _FakeClient:
    def __init__(self):
        self.is_connected = False

    async def connect(self):
        self.is_connected = True

    async def get_me(self):
        return SimpleNamespace(id=123456)


def test_check_account_status_uses_global_proxy_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("TG_PROXY", "socks5://127.0.0.1:1080")
    monkeypatch.setattr(
        telegram_module,
        "settings",
        SimpleNamespace(resolve_session_dir=lambda: tmp_path),
    )
    monkeypatch.setattr(telegram_module, "get_account_profile", lambda _: {})
    monkeypatch.setattr(telegram_module, "get_session_mode", lambda: "file")

    captured = {}
    fake_core = types.ModuleType("tg_signer.core")

    def fake_get_client(
        name,
        proxy=None,
        workdir=None,
        session_string=None,
        in_memory=False,
    ):
        captured["proxy"] = proxy
        return _FakeClient()

    fake_core.get_client = fake_get_client
    monkeypatch.setitem(sys.modules, "tg_signer.core", fake_core)

    service = telegram_module.TelegramService()
    monkeypatch.setattr(service, "account_exists", lambda _: True)

    result = asyncio.run(service.check_account_status("demo-account"))

    assert result["ok"] is True
    assert captured["proxy"] == {
        "scheme": "socks5",
        "hostname": "127.0.0.1",
        "port": 1080,
    }