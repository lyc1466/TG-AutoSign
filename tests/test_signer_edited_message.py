import asyncio
import sys
import types
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ai_tools_module = types.ModuleType("tg_signer.ai_tools")


class _FakeAITools:
    pass


class _FakeOpenAIConfigManager:
    def __init__(self, workdir):
        self.workdir = workdir


ai_tools_module.AITools = _FakeAITools
ai_tools_module.OpenAIConfigManager = _FakeOpenAIConfigManager
sys.modules.setdefault("tg_signer.ai_tools", ai_tools_module)

import tg_signer.core as core_module


def _make_signer():
    signer = core_module.UserSigner.__new__(core_module.UserSigner)
    signer._account = "acc1"
    signer.task_name = "task1"
    signer.context = core_module.UserSignerWorkerContext(
        waiter=core_module.Waiter(),
        sign_chats=defaultdict(list),
        chat_messages=defaultdict(dict),
        waiting_message=None,
    )
    signer.log = lambda *args, **kwargs: None
    return signer


def _make_message(message_id: int, chat_id: int = 100):
    return SimpleNamespace(
        id=message_id,
        chat=SimpleNamespace(id=chat_id),
        from_user=SimpleNamespace(username="tester", id=1),
        text="test",
        photo=None,
        caption=None,
        reply_markup=None,
    )


def test_wait_for_processes_same_message_edit_before_timeout():
    signer = _make_signer()
    action = core_module.ClickKeyboardByTextAction(text="go")
    chat = core_module.SignChatV3(
        chat_id=100,
        actions=[action],
        action_interval=1000,
    )
    original = _make_message(10)
    edited = _make_message(10)
    edited.reply_markup = object()
    signer.context.chat_messages[chat.chat_id][original.id] = original
    processing_started = asyncio.Event()
    release_processing = asyncio.Event()

    async def fake_on_message(client, message):
        signer.context.chat_messages[message.chat.id][message.id] = message

    signer._on_message = fake_on_message
    signer.log = lambda *args, **kwargs: None

    async def fake_click(action_, message):
        if message.reply_markup:
            return True
        processing_started.set()
        await release_processing.wait()
        return False

    async def fake_history(chat_id, limit=5):
        if False:
            yield chat_id, limit

    signer._click_keyboard_by_text = fake_click
    signer.app = SimpleNamespace(get_chat_history=fake_history)

    async def invoke():
        async def publish_edit():
            await processing_started.wait()
            edit_task = asyncio.create_task(signer.on_edited_message(None, edited))
            await asyncio.sleep(0.05)
            release_processing.set()
            await edit_task

        await asyncio.gather(
            signer.wait_for(chat, action, timeout=0.8),
            publish_edit(),
        )

    asyncio.run(invoke())

    assert signer.context.chat_messages[edited.chat.id][edited.id] is None