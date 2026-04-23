import asyncio
import importlib
import sys
import types
from types import SimpleNamespace

import backend.core.config as config_module


def _close_background_task(coro):
    coro.close()
    return None


async def _no_sleep(_seconds):
    return None


class _CapturedAwaitable:
    def __await__(self):
        if False:
            yield None
        return True


def _build_service(monkeypatch, tmp_path):
    fake_tg_core = types.ModuleType("tg_signer.core")
    fake_tg_core.UserSigner = object
    fake_tg_core.get_client = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "tg_signer.core", fake_tg_core)

    sign_tasks_module = importlib.import_module("backend.services.sign_tasks")
    sign_tasks_module = importlib.reload(sign_tasks_module)

    settings = SimpleNamespace(
        resolve_workdir=lambda: tmp_path,
        resolve_session_dir=lambda: tmp_path,
    )
    monkeypatch.setattr(sign_tasks_module, "settings", settings)
    monkeypatch.setattr(config_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        sign_tasks_module,
        "get_sign_task_runtime_config",
        lambda: SimpleNamespace(
            account_cooldown_seconds=0,
            history_max_entries=10,
            history_max_flow_lines=100,
            history_max_line_chars=500,
            history_max_message_events=10,
            force_in_memory=False,
        ),
    )
    monkeypatch.setattr(sign_tasks_module.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(sign_tasks_module.asyncio, "create_task", _close_background_task)
    monkeypatch.setattr(sign_tasks_module, "get_account_lock", lambda _account: asyncio.Lock())
    monkeypatch.setattr(sign_tasks_module, "get_global_semaphore", lambda: asyncio.Semaphore(1))
    monkeypatch.setattr(
        sign_tasks_module,
        "get_telegram_api_runtime_config",
        lambda: SimpleNamespace(api_id=123456, api_hash="hash", is_configured=True),
    )
    monkeypatch.setattr(sign_tasks_module, "get_session_mode", lambda: "string")
    monkeypatch.setattr(sign_tasks_module, "get_account_session_string", lambda _account: "session")
    monkeypatch.setattr(sign_tasks_module, "load_session_string_file", lambda *_args: None)
    monkeypatch.setattr(sign_tasks_module, "get_account_proxy", lambda _account: None)
    monkeypatch.setattr(sign_tasks_module, "resolve_proxy_dict", lambda **_kwargs: None)

    service = sign_tasks_module.SignTaskService()
    monkeypatch.setattr(service, "get_task", lambda *_args, **_kwargs: {"chats": []})
    monkeypatch.setattr(service, "_task_requires_updates", lambda _cfg: False)
    return sign_tasks_module, service


def test_run_task_with_logs_sends_sign_notification_on_success(monkeypatch, tmp_path):
    sign_tasks_module, service = _build_service(monkeypatch, tmp_path)
    saved = {"called": False}
    captured = {}
    scheduled = []

    class FakeSigner:
        def __init__(self, *args, **kwargs):
            self._callback = kwargs["message_event_callback"]

        async def run_once(self, num_of_dialogs=20):
            await self._callback({"summary": "Bot: 签到成功，积分 +1"})

    def fake_save_run_info(*args, **kwargs):
        saved["called"] = True

    def fake_send(**kwargs):
        captured.update(kwargs)
        captured["save_called"] = saved["called"]
        return _CapturedAwaitable()

    def fake_dispatch(awaitable, *, logger, description, timeout=5):
        scheduled.append({"description": description, "timeout": timeout, "logger": logger})

    monkeypatch.setattr(sign_tasks_module, "BackendUserSigner", FakeSigner)
    monkeypatch.setattr(service, "_save_run_info", fake_save_run_info)
    monkeypatch.setattr(
        sign_tasks_module,
        "get_notification_service",
        lambda: SimpleNamespace(send_sign_task_completion=fake_send),
    )
    monkeypatch.setattr(sign_tasks_module, "dispatch_notification", fake_dispatch)

    result = asyncio.run(service.run_task_with_logs(account_name="alice", task_name="linuxdo"))

    assert result["success"] is True
    assert captured["task_name"] == "linuxdo"
    assert captured["account_name"] == "alice"
    assert captured["success"] is True
    assert captured["message_events"][0]["summary"] == "Bot: 签到成功，积分 +1"
    assert captured["save_called"] is True
    assert len(scheduled) == 1
    assert scheduled[0]["timeout"] == 5


def test_run_task_with_logs_sends_sign_notification_on_failure(monkeypatch, tmp_path):
    sign_tasks_module, service = _build_service(monkeypatch, tmp_path)
    captured = {}
    scheduled = []

    class FakeSigner:
        def __init__(self, *args, **kwargs):
            self._callback = kwargs["message_event_callback"]

        async def run_once(self, num_of_dialogs=20):
            await self._callback({"summary": "Bot: 正在处理"})
            raise RuntimeError("sign failed")

    def fake_send(**kwargs):
        captured.update(kwargs)
        return _CapturedAwaitable()

    def fake_dispatch(awaitable, *, logger, description, timeout=5):
        scheduled.append({"description": description, "timeout": timeout, "logger": logger})

    monkeypatch.setattr(sign_tasks_module, "BackendUserSigner", FakeSigner)
    monkeypatch.setattr(service, "_save_run_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sign_tasks_module,
        "get_notification_service",
        lambda: SimpleNamespace(send_sign_task_completion=fake_send),
    )
    monkeypatch.setattr(sign_tasks_module, "dispatch_notification", fake_dispatch)

    result = asyncio.run(service.run_task_with_logs(account_name="bob", task_name="linuxdo"))

    assert result["success"] is False
    assert captured["task_name"] == "linuxdo"
    assert captured["account_name"] == "bob"
    assert captured["success"] is False
    assert "sign failed" in captured["summary"]
    assert len(scheduled) == 1
    assert scheduled[0]["timeout"] == 5
