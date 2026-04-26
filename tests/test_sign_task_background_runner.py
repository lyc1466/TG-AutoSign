import importlib
import sys
import types
from types import SimpleNamespace

import backend.core.config as config_module


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
            history_max_entries=5,
            history_max_flow_lines=100,
            history_max_line_chars=500,
            history_max_message_events=10,
            force_in_memory=False,
        ),
    )
    return sign_tasks_module.SignTaskService()


def test_save_run_info_keeps_latest_five_entries(monkeypatch, tmp_path):
    service = _build_service(monkeypatch, tmp_path)
    service._history_max_entries = 5

    for index in range(7):
        service._save_run_info(
            "daily",
            True,
            f"? {index} ?",
            "alice",
            flow_logs=[f"?? {index}"],
            message_events=[],
        )

    history = service.get_task_history_logs(
        task_name="daily",
        account_name="alice",
        limit=10,
    )

    assert len(history) == 5
    assert history[0]["message"] == "? 6 ?"
    assert history[-1]["message"] == "? 2 ?"
