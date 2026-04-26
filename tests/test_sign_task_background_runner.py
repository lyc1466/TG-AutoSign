import asyncio
import importlib
import sys
import types
from types import SimpleNamespace

import pytest

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
            run_metadata={
                "job_id": f"job-{index}",
                "status": "completed",
                "status_text": "任务已完成",
                "started_at": f"2026-04-26T00:00:0{index}",
                "action_completed_at": f"2026-04-26T00:00:1{index}",
                "finished_at": f"2026-04-26T00:00:2{index}",
                "duration_seconds": index,
                "blocking_info": None,
            },
        )

    history = service.get_task_history_logs(
        task_name="daily",
        account_name="alice",
        limit=10,
    )

    assert len(history) == 5
    assert history[0]["message"] == "? 6 ?"
    assert history[0]["job_id"] == "job-6"
    assert history[0]["status_text"] == "任务已完成"
    assert history[0]["action_completed_at"] == "2026-04-26T00:00:16"
    assert history[0]["duration_seconds"] == 6
    assert history[-1]["message"] == "? 2 ?"


@pytest.mark.asyncio
async def test_run_task_with_logs_fails_when_account_lock_wait_times_out(
    monkeypatch, tmp_path
):
    service = _build_service(monkeypatch, tmp_path)
    monkeypatch.setattr(
        service,
        "get_task",
        lambda task_name, account_name=None: {"name": task_name, "chats": []},
    )
    lock = asyncio.Lock()
    await lock.acquire()
    service._account_locks["alice"] = lock

    result = await service.run_task_with_logs(
        "alice",
        "daily",
        lock_wait_timeout_seconds=0.01,
    )

    assert result["success"] is False
    assert "等待账号空闲超时" in result["error"]
    history = service.get_task_history_logs("daily", account_name="alice")
    assert history[0]["status"] == "failed"
    assert "等待账号空闲超时" in history[0]["message"]
    lock.release()
