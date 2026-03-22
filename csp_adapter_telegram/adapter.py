import asyncio
import threading
from logging import getLogger
from queue import Queue
from typing import Dict, List, Optional, Set, TypeVar

import csp
from csp.impl.adaptermanager import AdapterManagerImpl
from csp.impl.outputadapter import OutputAdapter
from csp.impl.pushadapter import PushInputAdapter
from csp.impl.types.tstype import ts
from csp.impl.wiring import py_output_adapter_def, py_push_adapter_def
from telegram import Bot, ReactionTypeEmoji, Update
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

from .adapter_config import TelegramAdapterConfig
from .chat_mapper import TelegramChatMapper
from .message import TelegramMessage

T = TypeVar("T")
log = getLogger(__file__)


__all__ = ("TelegramAdapterManager", "TelegramInputAdapterImpl", "TelegramOutputAdapterImpl", "send_telegram_message")


async def send_telegram_message(
    msg: str,
    chat_id: str,
    bot_token: str,
    parse_mode: Optional[str] = None,
    reply_to_message_id: Optional[int] = None,
) -> dict:
    """Send a message to a Telegram chat using the Bot API directly.

    Standalone convenience function symmetric with Symphony's ``send_symphony_message``.
    Returns the sent message as a dict.
    """
    bot = Bot(token=bot_token)
    result = await bot.send_message(
        chat_id=int(chat_id),
        text=msg,
        parse_mode=parse_mode or None,
        reply_to_message_id=reply_to_message_id,
    )
    return result.to_dict()


class TelegramAdapterManager(AdapterManagerImpl):
    def __init__(self, config: TelegramAdapterConfig):
        self._config = config
        self._bot_token = config.bot_token

        # down stream edges
        self._subscribers = []
        self._publishers = []

        # message queues
        self._inqueue: Queue[TelegramMessage] = Queue()
        self._outqueue: Queue[TelegramMessage] = Queue()

        # handler thread
        self._running: bool = False
        self._thread: threading.Thread = None
        self._loop: asyncio.AbstractEventLoop = None
        self._application: Application = None

        # lookups for user/chat resolution
        self._user_id_to_user_name: Dict[str, str] = {}
        self._user_id_to_username: Dict[str, str] = {}
        self._chat_mapper = TelegramChatMapper()

        # deduplication
        self._seen_msg_ids: Set[str] = set()

        # optional chat filtering
        self._chat_ids: Set[str] = set()
        self._exit_msg: str = ""

        # bot info
        self._bot_id: str = ""
        self._bot_username: str = ""

    def subscribe(self, chat_ids: Optional[Set[str]] = None, exit_msg: str = ""):
        """Subscribe to incoming messages.

        Args:
            chat_ids: If provided, only messages from these chat IDs will be delivered.
            exit_msg: If set, this message is sent to all subscribed chats on shutdown.
        """
        if chat_ids:
            self._chat_ids = set(chat_ids)
        if exit_msg:
            self._exit_msg = exit_msg
        return _telegram_input_adapter(self, push_mode=csp.PushMode.NON_COLLAPSING)

    def publish(self, msg: ts[TelegramMessage]):
        return _telegram_output_adapter(self, msg)

    def _create(self, engine, memo):
        super().__init__(engine)
        return self

    def start(self, starttime, endtime):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        if self._running:
            self._running = False
            if self._loop and self._application:
                # Schedule stop in the event loop
                asyncio.run_coroutine_threadsafe(self._stop_application(), self._loop)
            if self._thread:
                self._thread.join(timeout=10)

    async def _stop_application(self):
        """Stop the telegram application from within the event loop."""
        try:
            # Send exit messages
            if self._exit_msg and self._application:
                bot = self._application.bot
                chat_ids = self._chat_ids or set(self._chat_mapper._id_to_title.keys())
                for cid in chat_ids:
                    try:
                        await bot.send_message(chat_id=int(cid), text=self._exit_msg)
                    except Exception:
                        log.exception(f"Error sending exit message to chat {cid}")

            updater = self._application.updater
            if updater and updater.running:
                await updater.stop()
            if self._application.running:
                await self._application.stop()
            await self._application.shutdown()
        except Exception:
            log.exception("Error stopping Telegram application")

    def register_subscriber(self, adapter):
        if adapter not in self._subscribers:
            self._subscribers.append(adapter)

    def register_publisher(self, adapter):
        if adapter not in self._publishers:
            self._publishers.append(adapter)

    def _get_user_display_name(self, user) -> str:
        """Extract display name from a telegram User object."""
        if user is None:
            return ""
        parts = []
        if user.first_name:
            parts.append(user.first_name)
        if user.last_name:
            parts.append(user.last_name)
        return " ".join(parts) if parts else str(user.id)

    def _get_chat_title(self, chat) -> str:
        """Extract title from a telegram Chat object."""
        if chat is None:
            return ""
        if chat.title:
            return chat.title
        # For private chats, use the user's name
        parts = []
        if chat.first_name:
            parts.append(chat.first_name)
        if chat.last_name:
            parts.append(chat.last_name)
        return " ".join(parts) if parts else str(chat.id)

    def _get_tags_from_message(self, message) -> List[str]:
        """Extract @mentions from message entities."""
        tags = []
        if not message.entities:
            return tags
        for entity in message.entities:
            if entity.type == "mention" and message.text:
                # @username mention - extract the username (without @)
                mention_text = message.text[entity.offset : entity.offset + entity.length]
                if mention_text.startswith("@"):
                    mention_text = mention_text[1:]
                tags.append(mention_text)
            elif entity.type == "text_mention" and entity.user:
                # text_mention: mention by user id (no username)
                tags.append(self._get_user_display_name(entity.user))
        return tags

    async def _handle_message(self, update: Update, context):
        """Handle incoming Telegram messages."""
        if update.message is None:
            return

        message = update.message
        user = message.from_user
        chat = message.chat

        # Deduplication
        msg_key = f"{chat.id}:{message.message_id}" if chat else str(message.message_id)
        if msg_key in self._seen_msg_ids:
            return
        self._seen_msg_ids.add(msg_key)

        # Chat filtering
        chat_id = str(chat.id) if chat else ""
        if self._chat_ids and chat_id not in self._chat_ids:
            return

        # Cache user info
        user_id = str(user.id) if user else ""
        if user and user_id:
            self._user_id_to_user_name[user_id] = self._get_user_display_name(user)
            if user.username:
                self._user_id_to_username[user_id] = user.username

        # Cache chat info via mapper
        if chat and chat_id:
            title = self._get_chat_title(chat)
            self._chat_mapper.set(title, chat_id)
            if chat.type == "private" and user:
                self._chat_mapper.set_dm(self._get_user_display_name(user), chat_id)

        tags = self._get_tags_from_message(message)

        telegram_msg = TelegramMessage(
            user=self._get_user_display_name(user) if user else "",
            user_id=user_id,
            username=user.username or "" if user else "",
            tags=tags,
            chat=self._get_chat_title(chat) if chat else "",
            chat_id=chat_id,
            chat_type=chat.type if chat else "",
            msg=message.text or message.caption or "",
            reaction="",
            thread=str(message.message_id),
            payload=message.to_dict(),
        )
        self._inqueue.put(telegram_msg)

    async def _handle_callback_query(self, update: Update, context):
        """Handle inline keyboard callback queries (like Symphony's SYMPHONYELEMENTSACTION)."""
        if update.callback_query is None:
            return

        query = update.callback_query
        user = query.from_user
        chat = query.message.chat if query.message else None

        user_id = str(user.id) if user else ""
        chat_id = str(chat.id) if chat else ""

        if self._chat_ids and chat_id not in self._chat_ids:
            return

        telegram_msg = TelegramMessage(
            user=self._get_user_display_name(user) if user else "",
            user_id=user_id,
            username=user.username or "" if user else "",
            tags=[],
            chat=self._get_chat_title(chat) if chat else "",
            chat_id=chat_id,
            chat_type=chat.type if chat else "",
            msg="",
            reaction="",
            thread=str(query.message.message_id) if query.message else "",
            callback_data=query.data or "",
            payload=query.to_dict() if hasattr(query, "to_dict") else {},
        )
        self._inqueue.put(telegram_msg)

        # Acknowledge the callback query
        try:
            await query.answer()
        except Exception:
            log.exception("Failed to answer callback query")

    def _run(self):
        """Main run loop in a separate thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._async_run())

    async def _async_run(self):
        """Async main loop: start polling and process queues."""
        # Build the application
        self._application = Application.builder().token(self._bot_token).build()

        # Register message handler for all text messages
        self._application.add_handler(MessageHandler(filters.TEXT | filters.CAPTION, self._handle_message))
        # Register callback query handler
        self._application.add_handler(CallbackQueryHandler(self._handle_callback_query))

        # Initialize and start
        await self._application.initialize()

        # Get bot info
        bot_info = await self._application.bot.get_me()
        self._bot_id = str(bot_info.id)
        self._bot_username = bot_info.username or ""

        await self._application.start()
        await self._application.updater.start_polling(drop_pending_updates=True)

        try:
            while self._running:
                # Drain outbound queue
                while not self._outqueue.empty():
                    telegram_msg = self._outqueue.get()
                    await self._send_message(telegram_msg)

                # Push inbound messages to subscribers
                if not self._inqueue.empty():
                    telegram_msgs = []
                    while not self._inqueue.empty():
                        telegram_msgs.append(self._inqueue.get())

                    for adapter in self._subscribers:
                        adapter.push_tick(telegram_msgs)

                await asyncio.sleep(0.1)
        finally:
            # Shutdown
            try:
                updater = self._application.updater
                if updater and updater.running:
                    await updater.stop()
                if self._application.running:
                    await self._application.stop()
                await self._application.shutdown()
            except Exception:
                log.exception("Error during Telegram application shutdown")

    async def _send_message(self, telegram_msg: TelegramMessage):
        """Send a message, reaction, or edit via the Telegram Bot API."""
        bot: Bot = self._application.bot

        # Determine chat_id — try field, then resolve via mapper
        chat_id = getattr(telegram_msg, "chat_id", None) or ""
        if not chat_id:
            chat_name = getattr(telegram_msg, "chat", None) or ""
            if chat_name:
                chat_id = self._chat_mapper.get_chat_id(chat_name) or ""
        if not chat_id:
            log.error(f"Received TelegramMessage without chat_id: {telegram_msg}")
            if self._config.error_chat_id:
                try:
                    await bot.send_message(chat_id=int(self._config.error_chat_id), text=f"ERROR: Message missing chat_id: {telegram_msg.msg[:100]}")
                except Exception:
                    log.exception("Failed to send error notification")
            return

        parse_mode = getattr(telegram_msg, "parse_mode", None) or None

        # Reaction
        if hasattr(telegram_msg, "reaction") and telegram_msg.reaction and hasattr(telegram_msg, "thread") and telegram_msg.thread:
            try:
                await bot.set_message_reaction(
                    chat_id=int(chat_id),
                    message_id=int(telegram_msg.thread),
                    reaction=[ReactionTypeEmoji(emoji=telegram_msg.reaction)],
                )
            except Exception:
                log.exception("Failed to set reaction on Telegram message")
                self._send_error_notification(bot, chat_id, "Failed to set reaction")
            return

        # Edit existing message
        edit_id = getattr(telegram_msg, "edit_message_id", None) or ""
        if edit_id and hasattr(telegram_msg, "msg") and telegram_msg.msg:
            try:
                await bot.edit_message_text(
                    chat_id=int(chat_id),
                    message_id=int(edit_id),
                    text=telegram_msg.msg,
                    parse_mode=parse_mode,
                )
            except Exception:
                log.exception("Failed to edit Telegram message")
                self._send_error_notification(bot, chat_id, "Failed to edit message")
            return

        # Text message
        if hasattr(telegram_msg, "msg") and telegram_msg.msg:
            try:
                reply_to = None
                if hasattr(telegram_msg, "thread") and telegram_msg.thread:
                    try:
                        reply_to = int(telegram_msg.thread)
                    except (ValueError, TypeError):
                        pass

                await bot.send_message(
                    chat_id=int(chat_id),
                    text=telegram_msg.msg,
                    parse_mode=parse_mode,
                    reply_to_message_id=reply_to,
                )
            except Exception:
                log.exception("Failed to send message to Telegram")
                self._send_error_notification(bot, chat_id, "Failed to send message")
            return

        log.error(f"Received malformed TelegramMessage instance: {telegram_msg}")

    def _send_error_notification(self, bot: Bot, failed_chat_id: str, error_desc: str):
        """Attempt to send error notifications to the error chat or the original chat."""

        async def _notify():
            if self._config.error_chat_id:
                try:
                    await bot.send_message(chat_id=int(self._config.error_chat_id), text=f"ERROR: {error_desc} in chat {failed_chat_id}")
                except Exception:
                    log.exception("Failed to send error notification to error_chat_id")
            if self._config.inform_client:
                try:
                    await bot.send_message(chat_id=int(failed_chat_id), text=f"ERROR: {error_desc}")
                except Exception:
                    log.exception("Failed to inform client of error")

        if self._loop and self._loop.is_running():
            asyncio.ensure_future(_notify(), loop=self._loop)

    def _on_tick(self, value):
        self._outqueue.put(value)


class TelegramInputAdapterImpl(PushInputAdapter):
    def __init__(self, manager):
        manager.register_subscriber(self)
        super().__init__()


class TelegramOutputAdapterImpl(OutputAdapter):
    def __init__(self, manager):
        manager.register_publisher(self)
        self._manager = manager
        super().__init__()

    def on_tick(self, time, value):
        self._manager._on_tick(value)


_telegram_input_adapter = py_push_adapter_def(
    name="TelegramInputAdapter",
    adapterimpl=TelegramInputAdapterImpl,
    out_type=ts[[TelegramMessage]],
    manager_type=TelegramAdapterManager,
)
_telegram_output_adapter = py_output_adapter_def(
    name="TelegramOutputAdapter",
    adapterimpl=TelegramOutputAdapterImpl,
    manager_type=TelegramAdapterManager,
    input=ts[TelegramMessage],
)
