"""Configuration API routes."""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from backend.core.auth import get_current_user
from backend.models.user import User
from backend.services.config import get_config_service
from backend.services.notifications import get_notification_service
from backend.utils.masking import mask_secret
from backend.utils.storage import is_writable_dir

router = APIRouter()
logger = logging.getLogger("backend.config_routes")


def _clear_sign_task_cache() -> None:
    try:
        from backend.services.sign_tasks import get_sign_task_service

        get_sign_task_service()._tasks_cache = None
    except Exception:
        # Best-effort cache invalidation; import should still succeed.
        pass


def _validate_name(value: str, field: str) -> None:
    """Reject values that could cause path traversal."""
    if not value or ".." in value or "/" in value or "\\" in value or "\x00" in value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field} 参数不合法",
        )


class ExportTaskResponse(BaseModel):
    task_name: str
    task_type: str
    config_json: str


class ImportTaskRequest(BaseModel):
    config_json: str
    task_name: Optional[str] = None
    account_name: Optional[str] = None


class ImportTaskResponse(BaseModel):
    success: bool
    task_name: str
    message: str


class ImportAllRequest(BaseModel):
    config_json: str
    overwrite: bool = False


class ImportAllResponse(BaseModel):
    signs_imported: int
    signs_skipped: int
    monitors_imported: int
    monitors_skipped: int
    errors: list[str]
    message: str


class TaskListResponse(BaseModel):
    sign_tasks: list[str]
    monitor_tasks: list[str]
    total: int


class ImportSignTasksRequest(BaseModel):
    config_json: str
    account_name: str
    overwrite: bool = False


class ImportSignTasksResponse(BaseModel):
    imported: int
    skipped: int
    errors: list[str]
    message: str


@router.get("/tasks", response_model=TaskListResponse)
def list_all_tasks(current_user: User = Depends(get_current_user)):
    try:
        sign_tasks = get_config_service().list_sign_tasks()
        monitor_tasks = get_config_service().list_monitor_tasks()
        return TaskListResponse(
            sign_tasks=sign_tasks,
            monitor_tasks=monitor_tasks,
            total=len(sign_tasks) + len(monitor_tasks),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取任务列表失败: {str(e)}",
        )


@router.get("/export/sign/{task_name}")
def export_sign_task(
    task_name: str,
    account_name: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    try:
        config_json = get_config_service().export_sign_task(
            task_name, account_name=account_name
        )
        if config_json is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"任务 {task_name} 不存在",
            )

        return Response(
            content=config_json.encode("utf-8"),
            media_type="application/json; charset=utf-8",
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导出任务失败: {str(e)}",
        )


@router.post("/import/sign", response_model=ImportTaskResponse)
async def import_sign_task(
    request: ImportTaskRequest, current_user: User = Depends(get_current_user)
):
    try:
        service = get_config_service()
        if not is_writable_dir(service.signs_dir):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"数据目录不可写: {service.signs_dir}",
            )

        success = service.import_sign_task(
            request.config_json, request.task_name, request.account_name
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="任务配置无效",
            )

        data = json.loads(request.config_json)
        final_task_name = request.task_name or data.get("task_name", "导入任务")

        from backend.scheduler import sync_jobs

        _clear_sign_task_cache()
        await sync_jobs()

        return ImportTaskResponse(
            success=True,
            task_name=final_task_name,
            message=f"任务 {final_task_name} 导入成功",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导入任务失败: {str(e)}",
        )


@router.get("/export/all")
def export_all_configs(current_user: User = Depends(get_current_user)):
    try:
        config_json = get_config_service().export_all_configs()
        return Response(
            content=config_json.encode("utf-8"),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="tg_signer_all_configs.json"'
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导出全部配置失败: {str(e)}",
        )


@router.post("/import/all", response_model=ImportAllResponse)
async def import_all_configs(
    request: ImportAllRequest, current_user: User = Depends(get_current_user)
):
    try:
        result = get_config_service().import_all_configs(
            request.config_json, request.overwrite
        )

        message_parts = []
        if result.get("signs_imported", 0) > 0:
            message_parts.append(f"已导入签到任务 {result['signs_imported']} 个")
        if result.get("signs_skipped", 0) > 0:
            message_parts.append(f"已跳过签到任务 {result['signs_skipped']} 个")
        if result.get("monitors_imported", 0) > 0:
            message_parts.append(f"已导入监控任务 {result['monitors_imported']} 个")
        if result.get("monitors_skipped", 0) > 0:
            message_parts.append(f"已跳过监控任务 {result['monitors_skipped']} 个")
        if result.get("settings_imported", 0) > 0:
            message_parts.append(f"已导入设置 {result['settings_imported']} 项")

        message = "；".join(message_parts) if message_parts else "未导入任何配置"

        from backend.scheduler import sync_jobs

        _clear_sign_task_cache()
        await sync_jobs()

        return ImportAllResponse(
            signs_imported=int(result.get("signs_imported", 0)),
            signs_skipped=int(result.get("signs_skipped", 0)),
            monitors_imported=int(result.get("monitors_imported", 0)),
            monitors_skipped=int(result.get("monitors_skipped", 0)),
            errors=[str(item) for item in result.get("errors", [])],
            message=message,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导入全部配置失败: {str(e)}",
        )


@router.delete("/sign/{task_name}")
async def delete_sign_task(
    task_name: str,
    account_name: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    try:
        success = get_config_service().delete_sign_config(
            task_name, account_name=account_name
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"任务 {task_name} 不存在",
            )

        from backend.scheduler import sync_jobs

        _clear_sign_task_cache()
        await sync_jobs()

        return {"success": True, "message": f"任务 {task_name} 已删除"}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除任务失败: {str(e)}",
        )


@router.get("/export/signs")
def export_sign_tasks(
    account_name: str,
    task_name: Optional[list[str]] = None,
    current_user: User = Depends(get_current_user),
):
    _validate_name(account_name, "account_name")
    try:
        config_json = get_config_service().export_sign_tasks(
            account_name=account_name, task_names=task_name
        )
        return Response(
            content=config_json.encode("utf-8"),
            media_type="application/json; charset=utf-8",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导出签到任务失败: {str(e)}",
        )


@router.post("/import/signs", response_model=ImportSignTasksResponse)
async def import_sign_tasks(
    request: ImportSignTasksRequest, current_user: User = Depends(get_current_user)
):
    _validate_name(request.account_name, "account_name")
    try:
        service = get_config_service()
        if not is_writable_dir(service.signs_dir):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"数据目录不可写: {service.signs_dir}",
            )

        result = service.import_sign_tasks(
            request.config_json,
            target_account_name=request.account_name,
            overwrite=request.overwrite,
        )

        _clear_sign_task_cache()

        from backend.scheduler import sync_jobs
        await sync_jobs()

        imported = int(result.get("imported", 0))
        skipped = int(result.get("skipped", 0))
        errors = [str(e) for e in result.get("errors", [])]
        parts = []
        if imported:
            parts.append(f"已导入 {imported} 个")
        if skipped:
            parts.append(f"已跳过 {skipped} 个")
        if errors:
            parts.append(f"出现 {len(errors)} 个错误")
        message = "；".join(parts) if parts else "没有可导入的任务"

        return ImportSignTasksResponse(
            imported=imported,
            skipped=skipped,
            errors=errors,
            message=message,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导入签到任务失败: {str(e)}",
        )


class AIConfigRequest(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


class AIConfigResponse(BaseModel):
    has_config: bool
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key_masked: Optional[str] = None


class AIConfigSaveResponse(BaseModel):
    success: bool
    message: str


class AITestResponse(BaseModel):
    success: bool
    message: str
    model_used: Optional[str] = None


@router.get("/ai", response_model=AIConfigResponse)
def get_ai_config(current_user: User = Depends(get_current_user)):
    try:
        config = get_config_service().get_ai_config()
        if not config:
            return AIConfigResponse(has_config=False)

        api_key = config.get("api_key", "")
        if api_key:
            masked = (
                api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:]
                if len(api_key) > 8
                else "****"
            )
        else:
            masked = None

        return AIConfigResponse(
            has_config=True,
            base_url=config.get("base_url"),
            model=config.get("model"),
            api_key_masked=masked,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"读取 AI 配置失败: {str(e)}",
        )


@router.post("/ai", response_model=AIConfigSaveResponse)
def save_ai_config(
    request: AIConfigRequest, current_user: User = Depends(get_current_user)
):
    try:
        get_config_service().save_ai_config(
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
        )
        return AIConfigSaveResponse(success=True, message="AI 配置已保存")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"保存 AI 配置失败: {str(e)}",
        )


@router.post("/ai/test", response_model=AITestResponse)
async def test_ai_connection(current_user: User = Depends(get_current_user)):
    try:
        result = await get_config_service().test_ai_connection()
        return AITestResponse(**result)
    except Exception as e:
        return AITestResponse(success=False, message=f"AI 测试失败: {str(e)}")


@router.delete("/ai", response_model=AIConfigSaveResponse)
def delete_ai_config(current_user: User = Depends(get_current_user)):
    try:
        get_config_service().delete_ai_config()
        return AIConfigSaveResponse(success=True, message="AI 配置已删除")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除 AI 配置失败: {str(e)}",
        )


class GlobalSettingsRequest(BaseModel):
    sign_interval: Optional[int] = None
    log_retention_days: int = 7
    data_dir: Optional[str] = None


class GlobalSettingsResponse(BaseModel):
    sign_interval: Optional[int] = None
    log_retention_days: int = 7
    data_dir: Optional[str] = None


@router.get("/settings", response_model=GlobalSettingsResponse)
def get_global_settings(current_user: User = Depends(get_current_user)):
    try:
        settings = get_config_service().get_global_settings()
        return GlobalSettingsResponse(**settings)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"读取全局设置失败: {str(e)}",
        )


@router.post("/settings", response_model=AIConfigSaveResponse)
def save_global_settings(
    request: GlobalSettingsRequest, current_user: User = Depends(get_current_user)
):
    try:
        settings = {
            "sign_interval": request.sign_interval,
            "log_retention_days": request.log_retention_days,
        }
        fields_set = getattr(request, "model_fields_set", getattr(request, "__fields_set__", set()))
        if "data_dir" in fields_set:
            settings["data_dir"] = request.data_dir

        get_config_service().save_global_settings(settings)
        return AIConfigSaveResponse(success=True, message="全局设置已保存")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"保存全局设置失败: {str(e)}",
        )


class TelegramConfigRequest(BaseModel):
    api_id: str
    api_hash: str


class TelegramConfigResponse(BaseModel):
    api_id: str
    api_hash: str
    is_custom: bool
    default_api_id: str
    default_api_hash: str


class TelegramConfigSaveResponse(BaseModel):
    success: bool
    message: str


class TelegramNotificationConfigRequest(BaseModel):
    bot_token: Optional[str] = None
    chat_id: str
    keep_existing_token: bool = False


class TelegramNotificationConfigResponse(BaseModel):
    has_config: bool
    bot_token_masked: Optional[str] = None
    chat_id: Optional[str] = None


class TelegramNotificationConfigSaveResponse(BaseModel):
    success: bool
    message: str


@router.get("/telegram", response_model=TelegramConfigResponse)
def get_telegram_config(current_user: User = Depends(get_current_user)):
    try:
        config = get_config_service().get_telegram_config()
        service = get_config_service()
        return TelegramConfigResponse(
            api_id=config.get("api_id", ""),
            api_hash=config.get("api_hash", ""),
            is_custom=bool(config.get("is_custom", False)),
            default_api_id=service.DEFAULT_TG_API_ID,
            default_api_hash=service.DEFAULT_TG_API_HASH,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"读取 Telegram 配置失败: {str(e)}",
        )


@router.post("/telegram", response_model=TelegramConfigSaveResponse)
def save_telegram_config(
    request: TelegramConfigRequest, current_user: User = Depends(get_current_user)
):
    try:
        if not request.api_id or not request.api_hash:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="必须填写 api_id 和 api_hash",
            )

        success = get_config_service().save_telegram_config(
            api_id=request.api_id,
            api_hash=request.api_hash,
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="保存 Telegram 配置失败",
            )
        return TelegramConfigSaveResponse(success=True, message="Telegram 配置已保存")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"保存 Telegram 配置失败: {str(e)}",
        )


@router.delete("/telegram", response_model=TelegramConfigSaveResponse)
def reset_telegram_config(current_user: User = Depends(get_current_user)):
    try:
        get_config_service().reset_telegram_config()
        return TelegramConfigSaveResponse(success=True, message="Telegram 配置已重置")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"重置 Telegram 配置失败: {str(e)}",
        )


@router.get(
    "/telegram-notification", response_model=TelegramNotificationConfigResponse
)
def get_telegram_notification_config(current_user: User = Depends(get_current_user)):
    try:
        config = get_config_service().get_telegram_notification_config()
        if not config:
            return TelegramNotificationConfigResponse(has_config=False)

        return TelegramNotificationConfigResponse(
            has_config=True,
            bot_token_masked=mask_secret(config.get("bot_token")),
            chat_id=config.get("chat_id"),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"读取 Telegram 通知配置失败: {str(e)}",
        )


@router.post(
    "/telegram-notification", response_model=TelegramNotificationConfigSaveResponse
)
def save_telegram_notification_config(
    request: TelegramNotificationConfigRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        get_config_service().save_telegram_notification_config(
            bot_token=request.bot_token,
            chat_id=request.chat_id,
            keep_existing_token=request.keep_existing_token,
        )
        return TelegramNotificationConfigSaveResponse(
            success=True,
            message="Telegram 通知配置已保存",
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"保存 Telegram 通知配置失败: {str(e)}",
        )


@router.delete(
    "/telegram-notification", response_model=TelegramNotificationConfigSaveResponse
)
def delete_telegram_notification_config(
    current_user: User = Depends(get_current_user),
):
    try:
        success = get_config_service().delete_telegram_notification_config()
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="删除 Telegram 通知配置失败",
            )
        return TelegramNotificationConfigSaveResponse(
            success=True,
            message="Telegram 通知配置已删除",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除 Telegram 通知配置失败: {str(e)}",
        )


@router.post(
    "/telegram-notification/test",
    response_model=TelegramNotificationConfigSaveResponse,
)
async def test_telegram_notification_config(
    current_user: User = Depends(get_current_user),
):
    try:
        config = get_config_service().get_telegram_notification_config()
        if not config:
            return TelegramNotificationConfigSaveResponse(
                success=False,
                message="尚未配置 Telegram 通知",
            )

        success = await get_notification_service().send_test_message()
        if success:
            return TelegramNotificationConfigSaveResponse(
                success=True,
                message="Telegram 通知测试消息发送成功",
            )

        return TelegramNotificationConfigSaveResponse(
            success=False,
            message="Telegram 通知测试失败",
        )
    except Exception:
        logger.exception("发送 Telegram 通知测试消息失败")
        return TelegramNotificationConfigSaveResponse(
            success=False,
            message="Telegram 通知测试失败",
        )
