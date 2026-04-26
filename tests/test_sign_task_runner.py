import asyncio

import pytest

from backend.services.sign_task_runner import SignTaskRunner


@pytest.mark.asyncio
async def test_runner_submit_returns_immediately_and_completes():
    started = asyncio.Event()
    release = asyncio.Event()

    async def run_task(account_name, task_name, progress_callback=None):
        started.set()
        await progress_callback("running_action", "执行任务动作中", "正在执行 Telegram 签到动作")
        await release.wait()
        return {"success": True, "output": "ok", "error": ""}

    runner = SignTaskRunner(run_task=run_task, worker_count=1)
    await runner.start()
    try:
        submission = runner.submit("alice", "daily")
        assert submission["accepted"] is True
        assert submission["status"] == "queued"
        assert submission["message"] == "任务已提交后台执行"

        await asyncio.wait_for(started.wait(), timeout=1)
        status = runner.get_status(submission["job_id"])
        assert status["phase"] == "running_action"
        assert status["phase_text"] == "执行任务动作中"

        release.set()
        await asyncio.wait_for(runner.wait_for_idle(), timeout=1)
        status = runner.get_status(submission["job_id"])
        assert status["status"] == "completed"
        assert status["status_text"] == "任务已完成"
    finally:
        await runner.stop()


@pytest.mark.asyncio
async def test_runner_rejects_duplicate_task_while_active():
    release = asyncio.Event()

    async def run_task(account_name, task_name, progress_callback=None):
        await release.wait()
        return {"success": True, "output": "ok", "error": ""}

    runner = SignTaskRunner(run_task=run_task, worker_count=1)
    await runner.start()
    try:
        first = runner.submit("alice", "daily")
        duplicate = runner.submit("alice", "daily")
        assert first["accepted"] is True
        assert duplicate["accepted"] is False
        assert duplicate["status"] == "running"
        assert duplicate["message"] == "该任务正在执行中，请勿重复触发"
    finally:
        release.set()
        await runner.stop()


@pytest.mark.asyncio
async def test_runner_reports_waiting_account_lock_with_blocking_job():
    release = asyncio.Event()

    async def run_task(account_name, task_name, progress_callback=None):
        await progress_callback("running_action", "执行任务动作中", f"正在执行 {task_name}")
        await release.wait()
        return {"success": True, "output": "ok", "error": ""}

    runner = SignTaskRunner(run_task=run_task, worker_count=2)
    await runner.start()
    try:
        first = runner.submit("alice", "first")
        await asyncio.sleep(0)
        second = runner.submit("alice", "second")
        assert second["accepted"] is True

        await asyncio.sleep(0.05)
        status = runner.get_status(second["job_id"])
        assert status["status"] == "waiting_account_lock"
        assert status["blocking_task_name"] == "first"
        assert status["blocking_phase_text"] == "执行任务动作中"
        assert "等待账号空闲" in status["message"]
        assert runner.get_active_job_for_account("alice").job_id == first["job_id"]
    finally:
        release.set()
        await runner.stop()


@pytest.mark.asyncio
async def test_runner_fails_waiting_job_after_lock_timeout():
    release = asyncio.Event()

    async def run_task(account_name, task_name, progress_callback=None):
        await release.wait()
        return {"success": True, "output": "ok", "error": ""}

    runner = SignTaskRunner(
        run_task=run_task,
        worker_count=2,
        lock_wait_timeout_seconds=0.01,
    )
    await runner.start()
    try:
        runner.submit("alice", "first")
        await asyncio.sleep(0)
        second = runner.submit("alice", "second")
        await asyncio.sleep(0.05)
        status = runner.get_status(second["job_id"])
        assert status["status"] == "failed"
        assert "等待账号空闲超时" in status["message"]
    finally:
        release.set()
        await runner.stop()
