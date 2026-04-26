import asyncio
import importlib.util
import sys
import types
import uuid
from pathlib import Path
from types import SimpleNamespace


def _load_sign_tasks_routes_module():
    fake_sign_task_service = types.ModuleType("backend.services.sign_tasks")
    fake_sign_task_service.get_sign_task_service = lambda: None
    sys.modules["backend.services.sign_tasks"] = fake_sign_task_service

    fake_runner_module = types.ModuleType("backend.services.sign_task_runner")
    fake_runner_module.get_sign_task_runner = lambda: None
    sys.modules["backend.services.sign_task_runner"] = fake_runner_module

    module_path = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "api"
        / "routes"
        / "sign_tasks.py"
    )
    spec = importlib.util.spec_from_file_location(
        f"sign_tasks_routes_background_under_test_{uuid.uuid4().hex}", module_path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_run_sign_task_submits_background_runner(monkeypatch):
    sign_tasks_routes = _load_sign_tasks_routes_module()
    calls = []

    class _ServiceStub:
        def get_task(self, task_name, account_name=None):
            return {"name": task_name, "account_name": account_name}

    class _RunnerStub:
        def submit(self, account_name, task_name):
            calls.append((account_name, task_name))
            return {
                "accepted": True,
                "success": True,
                "job_id": "job-1",
                "status": "queued",
                "status_text": "排队中",
                "phase": "queued",
                "phase_text": "排队中",
                "message": "任务已提交后台执行",
                "output": "任务已提交后台执行",
                "error": "",
            }

    monkeypatch.setattr(sign_tasks_routes, "get_sign_task_service", lambda: _ServiceStub())
    monkeypatch.setattr(sign_tasks_routes, "get_sign_task_runner", lambda: _RunnerStub())

    result = asyncio.run(
        sign_tasks_routes.run_sign_task(
            "daily",
            account_name="alice",
            current_user=SimpleNamespace(username="tester"),
        )
    )

    assert result.status_code == 202
    assert calls == [("alice", "daily")]
    assert b'"status":"queued"' in result.body
    assert "任务已提交后台执行".encode() in result.body


def test_run_sign_task_returns_conflict_for_duplicate(monkeypatch):
    sign_tasks_routes = _load_sign_tasks_routes_module()

    class _ServiceStub:
        def get_task(self, task_name, account_name=None):
            return {"name": task_name, "account_name": account_name}

    class _RunnerStub:
        def submit(self, account_name, task_name):
            return {
                "accepted": False,
                "success": False,
                "job_id": "job-1",
                "status": "running",
                "status_text": "任务正在执行中",
                "phase": "running_action",
                "phase_text": "执行任务动作中",
                "message": "该任务正在执行中，请勿重复触发",
                "output": "",
                "error": "该任务正在执行中，请勿重复触发",
            }

    monkeypatch.setattr(sign_tasks_routes, "get_sign_task_service", lambda: _ServiceStub())
    monkeypatch.setattr(sign_tasks_routes, "get_sign_task_runner", lambda: _RunnerStub())

    result = asyncio.run(
        sign_tasks_routes.run_sign_task(
            "daily",
            account_name="alice",
            current_user=SimpleNamespace(username="tester"),
        )
    )

    assert result.status_code == 409
    assert "该任务正在执行中，请勿重复触发".encode() in result.body


def test_run_status_reads_latest_runner_status(monkeypatch):
    sign_tasks_routes = _load_sign_tasks_routes_module()

    class _ServiceStub:
        def get_task(self, task_name, account_name=None):
            return {"name": task_name, "account_name": account_name}

    class _RunnerStub:
        def get_latest_status(self, account_name, task_name):
            return {
                "job_id": "job-2",
                "account_name": account_name,
                "task_name": task_name,
                "accepted": True,
                "status": "waiting_account_lock",
                "status_text": "等待账号空闲",
                "phase": "waiting_account_lock",
                "phase_text": "等待账号空闲",
                "is_running": True,
                "message": "正在等待账号空闲，前序任务：first",
                "success": None,
                "error": "",
                "logs": [],
                "message_events": [],
                "last_log": "正在等待账号空闲，前序任务：first",
                "blocking_task_name": "first",
            }

    monkeypatch.setattr(sign_tasks_routes, "get_sign_task_service", lambda: _ServiceStub())
    monkeypatch.setattr(sign_tasks_routes, "get_sign_task_runner", lambda: _RunnerStub())

    result = sign_tasks_routes.get_sign_task_run_status(
        "second",
        account_name="alice",
        current_user=SimpleNamespace(username="tester"),
    )

    assert result["status"] == "waiting_account_lock"
    assert result["blocking_task_name"] == "first"
