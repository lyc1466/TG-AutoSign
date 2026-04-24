import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

import backend.services.notifications as notifications_module


def test_send_message_posts_to_telegram_api(monkeypatch):
    service = notifications_module.NotificationService()
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json, timeout):
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            return FakeResponse()

    monkeypatch.setattr(notifications_module.httpx, "AsyncClient", FakeClient)

    ok = asyncio.run(
        service._send_message(bot_token="123:abc", chat_id="-1001", text="done")
    )

    assert ok is True
    assert captured["url"] == "https://api.telegram.org/bot123:abc/sendMessage"
    assert captured["json"] == {
        "chat_id": "-1001",
        "text": "done",
        "disable_web_page_preview": True,
    }
    assert captured["timeout"] == 10


def test_resolve_target_prefers_account_custom_config(monkeypatch):
    service = notifications_module.NotificationService()
    monkeypatch.setattr(
        notifications_module,
        "get_config_service",
        lambda: type(
            "ConfigServiceStub",
            (),
            {
                "get_telegram_notification_config": lambda self: {
                    "bot_token": "123:global",
                    "chat_id": "-100-global",
                }
            },
        )(),
    )
    monkeypatch.setattr(
        notifications_module,
        "get_account_profile",
        lambda _account_name: {
            "notification_channel": "custom",
            "notification_bot_token": "123:custom",
            "notification_chat_id": "-100-custom",
        },
    )

    target = asyncio.run(service.resolve_target("alice"))

    assert target == notifications_module.NotificationTarget(
        channel="custom",
        bot_token="123:custom",
        chat_id="-100-custom",
    )


def test_resolve_target_respects_disabled_channel(monkeypatch):
    service = notifications_module.NotificationService()
    monkeypatch.setattr(
        notifications_module,
        "get_config_service",
        lambda: type(
            "ConfigServiceStub",
            (),
            {
                "get_telegram_notification_config": lambda self: {
                    "bot_token": "123:global",
                    "chat_id": "-100-global",
                }
            },
        )(),
    )
    monkeypatch.setattr(
        notifications_module,
        "get_account_profile",
        lambda _account_name: {
            "notification_channel": "disabled",
        },
    )

    target = asyncio.run(service.resolve_target("alice"))

    assert target == notifications_module.NotificationTarget(
        channel="disabled",
        bot_token=None,
        chat_id=None,
    )


def test_build_sign_task_message_includes_recent_messages_and_truncates():
    message = notifications_module.build_sign_task_message(
        task_name="linuxdo_sign",
        account_name="alice",
        success=False,
        summary="Timeout while waiting for reply",
        finished_at=datetime(2026, 4, 24, 18, 35, 12),
        output="x" * 5000,
        message_events=[
            {"summary": "Bot: 签到成功，积分 +1"},
            {"text": "Bot: 今日已签到"},
        ],
    )

    assert "[任务完成通知]" in message
    assert "类型：签到任务" in message
    assert "任务：linuxdo_sign" in message
    assert "账号：alice" in message
    assert "状态：失败" in message
    assert "完成时间：2026-04-24 18:35:12" in message
    assert "最近消息：" in message
    assert "1. Bot: 签到成功，积分 +1" in message
    assert "2. Bot: 今日已签到" in message
    assert len(message) <= 3500


def test_recent_message_lines_keep_contiguous_numbering():
    lines = notifications_module._recent_message_lines(
        [
            {"summary": "Bot: 第一条"},
            {},
            {"text": "Bot: 第二条"},
        ]
    )

    assert lines == ["1. Bot: 第一条", "2. Bot: 第二条"]


def test_dispatch_notification_uses_timeout_and_logs_failures(monkeypatch):
    captured = {}
    logged = []

    class DummyTask:
        def add_done_callback(self, callback):
            callback(self)

        def result(self):
            return None

        def cancelled(self):
            return False

    async def fake_wait_for(awaitable, timeout):
        captured["timeout"] = timeout
        await awaitable

    async def failing_awaitable():
        raise RuntimeError("boom")

    def fake_create_task(coro):
        asyncio.run(coro)
        return DummyTask()

    monkeypatch.setattr(notifications_module.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(notifications_module.asyncio, "create_task", fake_create_task)

    logger = SimpleNamespace(
        exception=lambda message, *args, **kwargs: logged.append(message)
    )

    notifications_module.dispatch_notification(
        failing_awaitable(),
        logger=logger,
        description="notification dispatch failed",
    )

    assert captured["timeout"] == 5
    assert logged == ["notification dispatch failed"]


def test_dispatch_notification_ignores_cancelled_tasks(monkeypatch):
    logged = []

    class DummyTask:
        def add_done_callback(self, callback):
            callback(self)

        def result(self):
            raise AssertionError("result() should not be called for cancelled tasks")

        def cancelled(self):
            return True

    class NoopAwaitable:
        def __await__(self):
            if False:
                yield None
            return None

    def fake_create_task(coro):
        coro.close()
        return DummyTask()

    monkeypatch.setattr(notifications_module.asyncio, "create_task", fake_create_task)

    logger = SimpleNamespace(
        exception=lambda message, *args, **kwargs: logged.append(message)
    )

    notifications_module.dispatch_notification(
        NoopAwaitable(),
        logger=logger,
        description="notification dispatch cancelled",
    )

    assert logged == []


def test_dispatch_notification_ignores_cancelled_runner(monkeypatch):
    logged = []

    class FakeCancelledError(Exception):
        pass

    class DummyTask:
        def add_done_callback(self, callback):
            callback(self)

        def result(self):
            return None

        def cancelled(self):
            return False

    class NoopAwaitable:
        def __await__(self):
            if False:
                yield None
            return None

    async def fake_wait_for(awaitable, timeout):
        raise FakeCancelledError("cancelled")

    def fake_create_task(coro):
        asyncio.run(coro)
        return DummyTask()

    monkeypatch.setattr(notifications_module.asyncio, "CancelledError", FakeCancelledError)
    monkeypatch.setattr(notifications_module.asyncio, "wait_for", fake_wait_for)
    monkeypatch.setattr(notifications_module.asyncio, "create_task", fake_create_task)

    logger = SimpleNamespace(
        exception=lambda message, *args, **kwargs: logged.append(message)
    )

    notifications_module.dispatch_notification(
        NoopAwaitable(),
        logger=logger,
        description="notification dispatch cancelled in runner",
    )

    assert logged == []


def test_send_message_propagates_errors_for_contextual_logging(monkeypatch):
    service = notifications_module.NotificationService()

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json, timeout):
            raise RuntimeError("boom")

    monkeypatch.setattr(notifications_module.httpx, "AsyncClient", FakeClient)

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(
            service._send_message(bot_token="123:abc", chat_id="-1001", text="done")
        )
