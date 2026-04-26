from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from pathlib import Path
from typing import List, Optional

from sqlalchemy.orm import Session

from backend.cli.tasks import async_run_task_cli
from backend.core.config import get_settings
from backend.core.logging import format_log_line, utc_now_naive
from backend.models.account import Account
from backend.models.task import Task
from backend.models.task_log import TaskLog
from backend.services.notifications import (
    dispatch_notification,
    get_notification_service,
)

settings = get_settings()
logger = logging.getLogger("backend.tasks")

# 用于实时日志推送的状态跟踪
_active_tasks: dict[int, bool] = {}
_active_logs: dict[int, list[str]] = {}


def get_active_logs(task_id: int) -> list[str]:
    return _active_logs.get(task_id, [])


def is_task_running(task_id: int) -> bool:
    return _active_tasks.get(task_id, False)


def list_tasks(db: Session) -> List[Task]:
    return db.query(Task).order_by(Task.id.desc()).all()


def cleanup_old_logs(db: Session, days: int = 3) -> int:
    """清理超过指定天数的任务日志和文件"""
    cutoff = utc_now_naive() - timedelta(days=days)

    # 获取旧日志
    old_logs = db.query(TaskLog).filter(TaskLog.started_at < cutoff).all()

    count = 0
    for log in old_logs:
        # 删除文件
        if log.log_path:
            try:
                p = Path(log.log_path)
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        # 从数据库删除
        db.delete(log)
        count += 1

    if count > 0:
        db.commit()
    return count


def get_task(db: Session, task_id: int) -> Optional[Task]:
    return db.query(Task).filter(Task.id == task_id).first()


def create_task(
    db: Session,
    name: str,
    cron: str,
    enabled: bool,
    account_id: int,
) -> Task:
    task = Task(name=name, cron=cron, enabled=enabled, account_id=account_id)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def update_task(
    db: Session,
    task: Task,
    *,
    name: Optional[str] = None,
    cron: Optional[str] = None,
    enabled: Optional[bool] = None,
    account_id: Optional[int] = None,
) -> Task:
    if name is not None:
        task.name = name
    if cron is not None:
        task.cron = cron
    if enabled is not None:
        task.enabled = enabled
    if account_id is not None:
        task.account_id = account_id
    db.commit()
    db.refresh(task)
    return task


def delete_task(db: Session, task: Task) -> None:
    db.delete(task)
    db.commit()


def _create_log_file(task: Task) -> Path:
    logs_dir = settings.resolve_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = utc_now_naive().strftime("%Y%m%d_%H%M%S")
    return logs_dir / f"task_{task.id}_{ts}.log"


def _dispatch_task_completion_notification(
    *,
    task: Task,
    task_log: TaskLog,
    account_name: str,
) -> None:
    dispatch_notification(
        get_notification_service().send_regular_task_completion(
            task_obj=task,
            task_log=task_log,
            account_name=account_name,
        ),
        logger=logger,
        description=f"发送普通任务完成通知失败: 账号={account_name}, 任务={task.name}",
    )


async def run_task_once(db: Session, task: Task) -> TaskLog:
    if is_task_running(task.id):
        # 如果已经在运行，返回最新的运行记录（或者抛出异常）
        logger.warning("普通任务已在运行，返回最近一次记录: 任务 ID=%s", task.id)
        last_log = (
            db.query(TaskLog)
            .filter(TaskLog.task_id == task.id)
            .order_by(TaskLog.id.desc())
            .first()
        )
        return last_log

    account: Account = task.account  # type: ignore[assignment]
    log_file = _create_log_file(task)

    _active_tasks[task.id] = True
    _active_logs[task.id] = []
    logger.info(
        "开始执行普通任务: 任务ID=%s, 任务名=%s, 账号=%s",
        task.id,
        task.name,
        account.account_name,
    )

    task_log = TaskLog(
        task_id=task.id,
        status="running",
        log_path=str(log_file),
        started_at=utc_now_naive(),
    )
    db.add(task_log)
    db.commit()
    db.refresh(task_log)

    def log_callback(line: str):
        _active_logs[task.id].append(line)
        if len(_active_logs[task.id]) > 500:
            _active_logs[task.id].pop(0)

    try:
        # 使用异步执行调用，并注入回调
        returncode, stdout, stderr = await async_run_task_cli(
            account_name=account.account_name,
            task_name=task.name,
            callback=log_callback,
        )

        full_output = (stdout or "") + "\n" + (stderr or "")

        # 写入日志文件（完整内容）
        with open(log_file, "w", encoding="utf-8") as fp:
            fp.write(full_output)

        # 更新数据库记录
        task_log.finished_at = utc_now_naive()
        task_log.status = "success" if returncode == 0 else "failed"
        if returncode != 0:
            task_log.output = (
                stderr[-1000:] if stderr else f"任务执行失败，退出码: {returncode}"
            )
        else:
            task_log.output = "执行成功"

        db.commit()
        db.refresh(task_log)

        task.last_run_at = task_log.finished_at
        db.commit()
        logger.info(
            "普通任务执行结束: 任务ID=%s, 任务名=%s, 状态=%s",
            task.id,
            task.name,
            task_log.status,
        )
        _dispatch_task_completion_notification(
            task=task,
            task_log=task_log,
            account_name=account.account_name,
        )
    except Exception as e:
        msg = f"任务执行失败: {type(e).__name__}: {e}"
        _active_logs[task.id].append(msg)
        task_log.status = "failed"
        task_log.output = msg[-1000:]
        task_log.finished_at = utc_now_naive()
        logger.exception(
            "普通任务执行异常: 任务ID=%s, 任务名=%s, 账号=%s, 错误=%s",
            task.id,
            task.name,
            account.account_name,
            e,
        )
        db.commit()
        _dispatch_task_completion_notification(
            task=task,
            task_log=task_log,
            account_name=account.account_name,
        )
    finally:
        _active_tasks[task.id] = False
        if task_log.status == "failed" and (
            not _active_logs[task.id] or _active_logs[task.id][-1] != task_log.output
        ):
            _active_logs[task.id].append(
                format_log_line(task_log.output, level="ERROR", logger_name="backend.tasks")
            )

        # 延迟清理日志
        async def cleanup():
            await asyncio.sleep(60)
            if not is_task_running(task.id):
                _active_logs.pop(task.id, None)

        asyncio.create_task(cleanup())

    return task_log


def list_task_logs(db: Session, task_id: int, limit: int = 50) -> List[TaskLog]:
    return (
        db.query(TaskLog)
        .filter(TaskLog.task_id == task_id)
        .order_by(TaskLog.id.desc())
        .limit(limit)
        .all()
    )
