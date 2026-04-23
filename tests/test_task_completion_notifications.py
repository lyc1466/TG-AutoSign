import asyncio
from types import SimpleNamespace

import backend.services.tasks as tasks_module


class _FakeDB:
    def __init__(self):
        self.added = []
        self.commits = 0
        self.refreshed = []

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        self.refreshed.append(obj)


def _close_background_task(coro):
    coro.close()
    return None


def _make_task(task_id: int = 1, name: str = "daily_cleanup", account_name: str = "alice"):
    return SimpleNamespace(
        id=task_id,
        name=name,
        account=SimpleNamespace(account_name=account_name),
        last_run_at=None,
    )


class _CapturedAwaitable:
    def __await__(self):
        if False:
            yield None
        return True


def test_run_task_once_sends_notification_after_success(monkeypatch, tmp_path):
    monkeypatch.setattr(
        tasks_module,
        "settings",
        SimpleNamespace(resolve_logs_dir=lambda: tmp_path),
    )
    monkeypatch.setattr(tasks_module.asyncio, "create_task", _close_background_task)

    async def fake_cli_success(*, account_name, task_name, callback):
        callback("done")
        return 0, "success output", ""

    sent = {}
    scheduled = []

    def fake_send(*, task_obj, task_log, account_name):
        sent["task_obj"] = task_obj
        sent["task_log"] = task_log
        sent["account_name"] = account_name
        return _CapturedAwaitable()

    def fake_dispatch(awaitable, *, logger, description, timeout=5):
        scheduled.append({"description": description, "timeout": timeout, "logger": logger})

    monkeypatch.setattr(tasks_module, "async_run_task_cli", fake_cli_success)
    monkeypatch.setattr(
        tasks_module,
        "get_notification_service",
        lambda: SimpleNamespace(send_regular_task_completion=fake_send),
    )
    monkeypatch.setattr(tasks_module, "dispatch_notification", fake_dispatch)

    db = _FakeDB()
    task = _make_task()

    task_log = asyncio.run(tasks_module.run_task_once(db, task))

    assert task_log.status == "success"
    assert sent["task_obj"] is task
    assert sent["task_log"] is task_log
    assert sent["account_name"] == "alice"
    assert len(scheduled) == 1
    assert scheduled[0]["timeout"] == 5


def test_run_task_once_sends_notification_after_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        tasks_module,
        "settings",
        SimpleNamespace(resolve_logs_dir=lambda: tmp_path),
    )
    monkeypatch.setattr(tasks_module.asyncio, "create_task", _close_background_task)

    async def fake_cli_failure(*, account_name, task_name, callback):
        callback("failed")
        return 1, "", "stderr failure"

    sent = {}
    scheduled = []

    def fake_send(*, task_obj, task_log, account_name):
        sent["status"] = task_log.status
        sent["account_name"] = account_name
        return _CapturedAwaitable()

    def fake_dispatch(awaitable, *, logger, description, timeout=5):
        scheduled.append({"description": description, "timeout": timeout, "logger": logger})

    monkeypatch.setattr(tasks_module, "async_run_task_cli", fake_cli_failure)
    monkeypatch.setattr(
        tasks_module,
        "get_notification_service",
        lambda: SimpleNamespace(send_regular_task_completion=fake_send),
    )
    monkeypatch.setattr(tasks_module, "dispatch_notification", fake_dispatch)

    db = _FakeDB()
    task = _make_task(task_id=2, name="nightly_job", account_name="bob")

    task_log = asyncio.run(tasks_module.run_task_once(db, task))

    assert task_log.status == "failed"
    assert task_log.output == "stderr failure"
    assert sent == {
        "status": "failed",
        "account_name": "bob",
    }
    assert len(scheduled) == 1
    assert scheduled[0]["timeout"] == 5
