from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from backend.core.database import get_session_local
from backend.core.logging import describe_exception
from backend.models.task import Task
from backend.services.tasks import run_task_once

scheduler: AsyncIOScheduler | None = None
logger = logging.getLogger("backend.scheduler")


def create_cron_trigger(cron_str: str) -> CronTrigger:
    """自动解析格式并创建 CronTrigger，支持 5位和6位 cron 表达式以及 HH:MM 或 HH:MM:SS"""
    cron_str = str(cron_str or "").strip()
    if not cron_str:
        raise ValueError("CRON 表达式不能为空")

    if ":" in cron_str:
        parts = cron_str.split(":")
        try:
            if len(parts) == 2:
                hour, minute = parts
                cron_str = f"0 {int(minute)} {int(hour)} * * *"
            elif len(parts) == 3:
                hour, minute, second = parts
                cron_str = f"{int(second)} {int(minute)} {int(hour)} * * *"
        except ValueError:
            pass

    parts = cron_str.split()
    if len(parts) == 6:
        return CronTrigger(
            second=parts[0],
            minute=parts[1],
            hour=parts[2],
            day=parts[3],
            month=parts[4],
            day_of_week=parts[5],
        )
    return CronTrigger.from_crontab(cron_str)


async def _job_run_task(task_id: int) -> None:
    db: Session = get_session_local()()
    try:
        # 这里的查询是同步的，对于 SQLite 且任务量不大可以接受
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task or not task.enabled:
            logger.info("跳过普通任务调度执行: 任务 ID=%s, 原因=%s", task_id, "任务不存在或未启用")
            return
        # run_task_once 将被改为 async
        logger.info("开始执行普通任务调度: 任务 ID=%s, 任务名=%s", task_id, task.name)
        await run_task_once(db, task)
        logger.info("普通任务调度执行结束: 任务 ID=%s, 任务名=%s", task_id, task.name)
    finally:
        db.close()


async def _job_run_sign_task(account_name: str, task_name: str) -> None:
    """运行签到任务的 Job 包装器"""
    import asyncio
    import random
    from datetime import datetime, timedelta

    from backend.services.sign_tasks import get_sign_task_service

    try:
        logger.info("开始执行签到任务调度: 账号=%s, 任务=%s", account_name, task_name)

        # 获取任务配置，检查是否为随机时间段模式
        sign_task_service = get_sign_task_service()
        task_config = sign_task_service.get_task(task_name, account_name)
        if not task_config:
            logger.warning(
                "签到任务调度执行前未找到任务配置，跳过本次执行: 账号=%s, 任务=%s",
                account_name,
                task_name,
            )
            return
        if task_config and task_config.get("execution_mode") == "range":
            range_start_str = task_config.get("range_start")
            range_end_str = task_config.get("range_end")

            if range_start_str and range_end_str:
                try:
                    # 解析时间
                    fmt = "%H:%M"
                    start_time = datetime.strptime(range_start_str, fmt).time()
                    end_time = datetime.strptime(range_end_str, fmt).time()

                    # 转换为当前日期的 datetime
                    now = datetime.now()
                    start_dt = now.replace(
                        hour=start_time.hour,
                        minute=start_time.minute,
                        second=0,
                        microsecond=0,
                    )
                    end_dt = now.replace(
                        hour=end_time.hour,
                        minute=end_time.minute,
                        second=0,
                        microsecond=0,
                    )

                    # 如果结束时间小于开始时间，假设是第二天（虽然CRON触发通常在开始时间，这里做个防御）
                    if end_dt < start_dt:
                        end_dt += timedelta(days=1)

                    # 计算总秒数
                    total_seconds = (end_dt - start_dt).total_seconds()

                    if total_seconds > 0:
                        # 生成随机延迟
                        delay_seconds = random.uniform(0, total_seconds)
                        logger.info(
                            "签到任务启用随机时间段执行: 账号=%s, 任务=%s, 时间段=%s-%s",
                            account_name,
                            task_name,
                            range_start_str,
                            range_end_str,
                        )
                        logger.info(
                            "签到任务将在随机延迟后执行: 账号=%s, 任务=%s, 延迟秒数=%s, 延迟分钟=%.2f",
                            account_name,
                            task_name,
                            int(delay_seconds),
                            delay_seconds / 60,
                        )

                        await asyncio.sleep(delay_seconds)
                    else:
                        logger.warning(
                            "签到任务随机时间段计算结果无效，将立即执行: 账号=%s, 任务=%s, 时间段=%s-%s",
                            account_name,
                            task_name,
                            range_start_str,
                            range_end_str,
                        )

                except Exception as e:
                    logger.exception(
                        "计算签到任务随机时间段延迟失败，将立即执行: 账号=%s, 任务=%s, 错误=%s",
                        account_name,
                        task_name,
                        describe_exception(e),
                    )

        # run_task_with_logs 是 async 的，我们使用它
        sign_task_service = get_sign_task_service()
        result = await sign_task_service.run_task_with_logs(account_name, task_name)
        if result.get("success"):
            logger.info("签到任务调度执行成功: 账号=%s, 任务=%s", account_name, task_name)
        else:
            logger.error(
                "签到任务调度执行失败: 账号=%s, 任务=%s, 错误=%s",
                account_name,
                task_name,
                result.get("error"),
            )
    except Exception as e:
        logger.exception(
            "签到任务调度执行异常: 账号=%s, 任务=%s, 错误=%s",
            account_name,
            task_name,
            describe_exception(e),
        )


async def _job_maintenance() -> None:
    """每日维护任务：清理旧日志等"""
    db: Session = get_session_local()()
    try:
        from backend.services.sign_tasks import get_sign_task_service
        from backend.services.tasks import cleanup_old_logs

        # 清理数据库任务日志
        count = cleanup_old_logs(db, days=3)
        logger.info("维护任务已清理普通任务日志: 数量=%s", count)

        # 清理签到任务日志
        get_sign_task_service()._cleanup_old_logs()
        logger.info("维护任务已完成签到历史清理")
    finally:
        db.close()


async def sync_jobs() -> None:
    """
    Sync APScheduler jobs from DB tasks table and file-based sign tasks.
    """
    if scheduler is None:
        logger.warning("调度器尚未初始化，跳过同步任务")
        return

    from backend.services.sign_tasks import get_sign_task_service

    db: Session = get_session_local()()
    try:
        # 1. 同步数据库任务
        tasks = db.query(Task).filter(Task.enabled).all()
        existing_ids = {
            job.id
            for job in scheduler.get_jobs()
            if job.id.startswith("db-") or job.id.startswith("sign-")
        }
        desired_ids = set()

        for task in tasks:
            job_id = f"db-{task.id}"
            desired_ids.add(job_id)

            try:
                trigger = create_cron_trigger(task.cron)
                if job_id in existing_ids:
                    scheduler.reschedule_job(job_id, trigger=trigger)
                    logger.info("已更新普通任务调度: 作业 ID=%s, CRON=%s", job_id, task.cron)
                else:
                    scheduler.add_job(
                        _job_run_task,
                        trigger=trigger,
                        id=job_id,
                        args=[task.id],
                        replace_existing=True,
                    )
                    logger.info("已新增普通任务调度: 作业 ID=%s, CRON=%s", job_id, task.cron)
            except Exception as e:
                logger.exception(
                    "同步普通任务调度失败: 任务 ID=%s, CRON=%s, 错误=%s",
                    task.id,
                    task.cron,
                    describe_exception(e),
                )

        # 2. 同步签到任务 (SignTask)
        # 使用缓存的任务列表，减少 I/O
        sign_task_service = get_sign_task_service()
        sign_tasks = sign_task_service.list_tasks(force_refresh=False)
        for st in sign_tasks:
            job_id = f"sign-{st['account_name']}-{st['name']}"
            desired_ids.add(job_id)

            # SignTask 目前默认都是启用的，或者根据 st['enabled']
            if not st.get("enabled", True):
                if job_id in existing_ids:
                    scheduler.remove_job(job_id)
                    logger.info("已移除禁用的签到任务调度: 作业 ID=%s", job_id)
                continue

            try:
                trigger = create_cron_trigger(st["sign_at"])
                if st.get("execution_mode") == "range" and st.get("range_start"):
                    trigger = create_cron_trigger(st["range_start"])

                if job_id in existing_ids:
                    scheduler.reschedule_job(job_id, trigger=trigger)
                    logger.info(
                        "已更新签到任务调度: 作业 ID=%s, 账号=%s, 任务=%s",
                        job_id,
                        st["account_name"],
                        st["name"],
                    )
                else:
                    # 使用新的 job wrapper
                    scheduler.add_job(
                        _job_run_sign_task,
                        trigger=trigger,
                        id=job_id,
                        args=[st["account_name"], st["name"]],
                        replace_existing=True,
                    )
                    logger.info(
                        "已新增签到任务调度: 作业 ID=%s, 账号=%s, 任务=%s",
                        job_id,
                        st["account_name"],
                        st["name"],
                    )
            except Exception as e:
                logger.exception(
                    "同步签到任务调度失败: 账号=%s, 任务=%s, 错误=%s",
                    st.get("account_name"),
                    st.get("name"),
                    describe_exception(e),
                )

        # remove obsolete jobs
        for job_id in existing_ids - desired_ids:
            scheduler.remove_job(job_id)
            logger.info("已移除过期调度任务: 作业 ID=%s", job_id)
    finally:
        db.close()


async def init_scheduler(sync_on_startup: bool = True) -> AsyncIOScheduler:
    global scheduler
    if scheduler is None:
        from backend.core.config import get_settings

        settings = get_settings()
        scheduler = AsyncIOScheduler(
            timezone=settings.timezone,
            job_defaults={
                "misfire_grace_time": 3600,  # 允许任务延迟 1 小时执行
                "coalesce": True,  # 合并积压的执行
                "max_instances": 10,  # 增加并发实例数，避免多账号任务相互阻塞
            },
        )
        scheduler.start()
        logger.info("调度器初始化完成: 时区=%s", settings.timezone)

        # 添加每日凌晨 3 点执行的维护任务
        scheduler.add_job(
            _job_maintenance,
            trigger=CronTrigger.from_crontab("0 3 * * *"),
            id="system-maintenance",
            replace_existing=True,
        )
        logger.info("已注册系统维护任务: 作业 ID=system-maintenance, CRON=0 3 * * *")

        if sync_on_startup:
            await sync_jobs()
    return scheduler


def shutdown_scheduler() -> None:
    global scheduler
    if scheduler:
        scheduler.shutdown(wait=False)
        logger.info("调度器已关闭")
        scheduler = None


def add_or_update_sign_task_job(
    account_name: str, task_name: str, cron_expression: str, enabled: bool = True
) -> None:
    """动态添加或更新签到任务 Job"""
    global scheduler
    if not scheduler:
        logger.warning(
            "调度器未初始化，无法动态更新签到任务调度: 账号=%s, 任务=%s",
            account_name,
            task_name,
        )
        return

    job_id = f"sign-{account_name}-{task_name}"

    if not enabled:
        remove_sign_task_job(account_name, task_name)
        return

    try:
        cron = cron_expression
        trigger = create_cron_trigger(cron)

        # 总是使用 replace_existing=True 来覆盖旧的
        scheduler.add_job(
            _job_run_sign_task,
            trigger=trigger,
            id=job_id,
            args=[account_name, task_name],
            replace_existing=True,
        )
        logger.info("已动态添加或更新签到任务调度: 作业 ID=%s, CRON=%s", job_id, cron)
    except Exception as e:
        logger.exception(
            "动态添加签到任务调度失败: 作业 ID=%s, CRON=%s, 错误=%s",
            job_id,
            cron_expression,
            describe_exception(e),
        )


def remove_sign_task_job(account_name: str, task_name: str) -> None:
    """动态移除签到任务 Job"""
    global scheduler
    if not scheduler:
        logger.warning(
            "调度器未初始化，无法动态移除签到任务调度: 账号=%s, 任务=%s",
            account_name,
            task_name,
        )
        return

    job_id = f"sign-{account_name}-{task_name}"
    try:
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
            logger.info("已动态移除签到任务调度: 作业 ID=%s", job_id)
    except Exception as e:
        logger.exception(
            "动态移除签到任务调度失败: 作业 ID=%s, 错误=%s",
            job_id,
            describe_exception(e),
        )
