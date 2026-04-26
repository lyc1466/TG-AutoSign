from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional
from uuid import uuid4

ACTIVE_STATUSES = {
    "queued",
    "waiting_account_lock",
    "preparing",
    "running_action",
    "waiting_reply",
    "action_completed",
    "cleanup",
}

RunTaskCallable = Callable[..., Awaitable[Dict[str, Any]]]
LogProvider = Callable[[str, str], List[str]]
MessageEventProvider = Callable[[str, str], List[Dict[str, Any]]]


@dataclass
class SignTaskJob:
    job_id: str
    account_name: str
    task_name: str
    status: str = "queued"
    status_text: str = "排队中"
    phase: str = "queued"
    phase_text: str = "排队中"
    message: str = "任务已提交后台执行"
    accepted: bool = True
    success: Optional[bool] = None
    error: str = ""
    output: str = ""
    logs: List[str] = field(default_factory=list)
    message_events: List[Dict[str, Any]] = field(default_factory=list)
    blocking_job_id: Optional[str] = None
    blocking_task_name: Optional[str] = None
    blocking_phase: Optional[str] = None
    blocking_phase_text: Optional[str] = None
    blocking_last_log: str = ""
    submitted_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    action_completed_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    def snapshot(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "account_name": self.account_name,
            "task_name": self.task_name,
            "accepted": self.accepted,
            "status": self.status,
            "status_text": self.status_text,
            "phase": self.phase,
            "phase_text": self.phase_text,
            "message": self.message,
            "success": self.success,
            "error": self.error,
            "output": self.output,
            "logs": list(self.logs),
            "message_events": list(self.message_events),
            "last_log": self.logs[-1] if self.logs else "",
            "blocking_job_id": self.blocking_job_id,
            "blocking_task_name": self.blocking_task_name,
            "blocking_phase": self.blocking_phase,
            "blocking_phase_text": self.blocking_phase_text,
            "blocking_last_log": self.blocking_last_log,
            "submitted_at": self.submitted_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else "",
            "action_completed_at": self.action_completed_at.isoformat()
            if self.action_completed_at
            else "",
            "finished_at": self.finished_at.isoformat() if self.finished_at else "",
            "is_running": self.is_active,
        }


class SignTaskRunner:
    def __init__(
        self,
        run_task: RunTaskCallable,
        worker_count: int = 2,
        lock_wait_timeout_seconds: float = 120,
        log_provider: Optional[LogProvider] = None,
        message_event_provider: Optional[MessageEventProvider] = None,
    ):
        self._run_task = run_task
        self._worker_count = worker_count
        self._lock_wait_timeout_seconds = lock_wait_timeout_seconds
        self._log_provider = log_provider
        self._message_event_provider = message_event_provider
        self._queue: asyncio.Queue[SignTaskJob | None] = asyncio.Queue()
        self._jobs: Dict[str, SignTaskJob] = {}
        self._latest_by_task: Dict[tuple[str, str], str] = {}
        self._active_by_task: Dict[tuple[str, str], str] = {}
        self._active_by_account: Dict[str, str] = {}
        self._account_locks: Dict[str, asyncio.Lock] = {}
        self._workers: List[asyncio.Task] = []
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        for index in range(self._worker_count):
            self._workers.append(
                asyncio.create_task(self._worker_loop(), name=f"sign-task-runner:{index}")
            )

    async def stop(self) -> None:
        if not self._started:
            return
        for _ in self._workers:
            await self._queue.put(None)
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._started = False

    def submit(self, account_name: str, task_name: str) -> Dict[str, Any]:
        account_name = str(account_name or "").strip()
        task_name = str(task_name or "").strip()
        if not account_name:
            return self._rejected("账号名称不能为空", status="failed")
        if not task_name:
            return self._rejected("任务名称不能为空", status="failed")

        task_key = (account_name, task_name)
        active_job_id = self._active_by_task.get(task_key)
        active_job = self._jobs.get(active_job_id or "")
        if active_job and active_job.is_active:
            return {
                **active_job.snapshot(),
                "accepted": False,
                "success": False,
                "status": "running",
                "status_text": "任务正在执行中",
                "message": "该任务正在执行中，请勿重复触发",
                "error": "该任务正在执行中，请勿重复触发",
            }

        job = SignTaskJob(
            job_id=uuid4().hex,
            account_name=account_name,
            task_name=task_name,
            logs=["任务已提交后台执行"],
        )
        self._jobs[job.job_id] = job
        self._latest_by_task[task_key] = job.job_id
        self._active_by_task[task_key] = job.job_id
        self._queue.put_nowait(job)
        return job.snapshot()

    def get_status(self, job_id: str) -> Dict[str, Any]:
        job = self._jobs.get(job_id)
        if not job:
            return self._rejected("任务状态不存在", status="not_found")
        if self._log_provider:
            provider_logs = self._log_provider(job.account_name, job.task_name)
            if provider_logs:
                job.logs = provider_logs
        if self._message_event_provider:
            job.message_events = self._message_event_provider(job.account_name, job.task_name)
        return job.snapshot()

    def get_latest_status(self, account_name: str, task_name: str) -> Dict[str, Any]:
        job_id = self._latest_by_task.get((account_name, task_name))
        if not job_id:
            return {
                "job_id": "",
                "account_name": account_name,
                "task_name": task_name,
                "accepted": False,
                "status": "idle",
                "status_text": "空闲",
                "phase": "idle",
                "phase_text": "空闲",
                "message": "当前没有后台执行任务",
                "success": None,
                "error": "",
                "output": "",
                "logs": [],
                "message_events": [],
                "last_log": "",
                "blocking_job_id": None,
                "blocking_task_name": None,
                "blocking_phase": None,
                "blocking_phase_text": None,
                "blocking_last_log": "",
                "submitted_at": "",
                "started_at": "",
                "action_completed_at": "",
                "finished_at": "",
                "is_running": False,
            }
        return self.get_status(job_id)

    def get_active_job_for_task(
        self, account_name: str, task_name: str
    ) -> Optional[SignTaskJob]:
        job = self._jobs.get(self._active_by_task.get((account_name, task_name), ""))
        return job if job and job.is_active else None

    def get_active_job_for_account(self, account_name: str) -> Optional[SignTaskJob]:
        job = self._jobs.get(self._active_by_account.get(account_name, ""))
        return job if job and job.is_active else None

    async def wait_for_idle(self) -> None:
        await self._queue.join()
        while any(job.is_active for job in self._jobs.values()):
            await asyncio.sleep(0)

    async def _worker_loop(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                if job is None:
                    return
                await self._run_one(job)
            finally:
                self._queue.task_done()

    async def _run_one(self, job: SignTaskJob) -> None:
        lock = self._account_locks.setdefault(job.account_name, asyncio.Lock())
        if lock.locked():
            self._set_blocking_job(job)
        try:
            await asyncio.wait_for(lock.acquire(), timeout=self._lock_wait_timeout_seconds)
        except asyncio.TimeoutError:
            self._fail_waiting_job(job)
            return

        self._active_by_account[job.account_name] = job.job_id
        try:
            await self._report(job, "preparing", "准备执行", "已获取账号执行锁，开始准备运行环境")
            result = await self._run_task(
                job.account_name,
                job.task_name,
                progress_callback=lambda phase, phase_text, message: self._report(
                    job, phase, phase_text, message
                ),
            )
            success = bool(result.get("success"))
            job.success = success
            job.error = result.get("error", "") or ""
            job.output = result.get("output", "") or ""
            if success:
                await self._report(job, "completed", "任务已完成", "任务已完成")
                job.status = "completed"
                job.status_text = "任务已完成"
            else:
                job.status = "failed"
                job.status_text = "执行失败"
                job.phase = "failed"
                job.phase_text = "执行失败"
                job.message = job.error or "任务执行失败"
                job.logs.append(job.message)
        except Exception as exc:
            job.success = False
            job.error = f"{type(exc).__name__}: {exc}"
            job.status = "failed"
            job.status_text = "执行失败"
            job.phase = "failed"
            job.phase_text = "执行失败"
            job.message = f"执行失败：{job.error}"
            job.logs.append(job.message)
        finally:
            job.finished_at = datetime.now()
            if self._active_by_account.get(job.account_name) == job.job_id:
                self._active_by_account.pop(job.account_name, None)
            if self._active_by_task.get((job.account_name, job.task_name)) == job.job_id:
                self._active_by_task.pop((job.account_name, job.task_name), None)
            lock.release()

    async def _report(
        self, job: SignTaskJob, phase: str, phase_text: str, message: str
    ) -> None:
        now = datetime.now()
        job.phase = phase
        job.phase_text = phase_text
        job.status = phase if phase in ACTIVE_STATUSES else job.status
        job.status_text = phase_text
        job.message = message
        if phase == "preparing" and job.started_at is None:
            job.started_at = now
        if phase == "action_completed" and job.action_completed_at is None:
            job.action_completed_at = now
        job.logs.append(message)

    def _set_blocking_job(self, job: SignTaskJob) -> None:
        blocking = self.get_active_job_for_account(job.account_name)
        job.status = "waiting_account_lock"
        job.status_text = "等待账号空闲"
        job.phase = "waiting_account_lock"
        job.phase_text = "等待账号空闲"
        if blocking:
            job.blocking_job_id = blocking.job_id
            job.blocking_task_name = blocking.task_name
            job.blocking_phase = blocking.phase
            job.blocking_phase_text = blocking.phase_text
            job.blocking_last_log = blocking.logs[-1] if blocking.logs else ""
            job.message = f"正在等待账号空闲，前序任务：{blocking.task_name}"
        else:
            job.message = "正在等待账号空闲"
        job.logs.append(job.message)

    def _fail_waiting_job(self, job: SignTaskJob) -> None:
        job.status = "failed"
        job.status_text = "执行失败"
        job.phase = "failed"
        job.phase_text = "执行失败"
        job.success = False
        job.error = "等待账号空闲超时"
        job.message = "等待账号空闲超时，当前任务已取消，不会中断前序任务"
        job.finished_at = datetime.now()
        job.logs.append(job.message)
        if self._active_by_task.get((job.account_name, job.task_name)) == job.job_id:
            self._active_by_task.pop((job.account_name, job.task_name), None)

    def _rejected(self, message: str, status: str) -> Dict[str, Any]:
        return {
            "job_id": "",
            "accepted": False,
            "success": False,
            "status": status,
            "status_text": "执行失败" if status == "failed" else message,
            "phase": status,
            "phase_text": "执行失败" if status == "failed" else message,
            "message": message,
            "error": message,
            "output": "",
            "logs": [],
            "message_events": [],
            "last_log": "",
        }


_sign_task_runner: SignTaskRunner | None = None


def get_sign_task_runner() -> SignTaskRunner:
    global _sign_task_runner
    if _sign_task_runner is None:
        from backend.services.sign_tasks import get_sign_task_service

        service = get_sign_task_service()
        _sign_task_runner = SignTaskRunner(
            run_task=service.run_task_with_logs,
            log_provider=lambda account, task: service.get_active_logs(
                task, account_name=account
            ),
            message_event_provider=lambda account, task: service.get_active_message_events(
                task, account_name=account
            ),
        )
    return _sign_task_runner
