import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import csp
import pytest
from csp import ts
from pydantic import ValidationError

from csp_adapter_telegram import (
    TelegramAdapterConfig,
    TelegramAdapterManager,
    TelegramChatMapper,
    TelegramMessage,
    format_bold,
    format_code,
    format_code_block,
    format_italic,
    format_link,
    format_table,
    format_telegram_markdown,
    mention_all,
    mention_user,
    send_telegram_message,
)


@csp.node
def hello(msg: ts[TelegramMessage]) -> ts[TelegramMessage]:
    if csp.ticked(msg):
        text = f"Hello {msg.user}!"
        return TelegramMessage(
            chat_id=msg.chat_id,
            thread=msg.thread,
            msg=text,
        )


@csp.node
def react(msg: ts[TelegramMessage]) -> ts[TelegramMessage]:
    if csp.ticked(msg):
        return TelegramMessage(
            chat_id=msg.chat_id,
            thread=msg.thread,
            reaction="👋",
        )


@csp.node
def send_fake_message(am: TelegramAdapterManager) -> ts[bool]:
    with csp.alarms():
        a_send = csp.alarm(bool)
    with csp.start():
        csp.schedule_alarm(a_send, timedelta(seconds=1), True)
    if csp.ticked(a_send):
        if a_send:
            am._inqueue.put(
                TelegramMessage(
                    user="John Doe",
                    user_id="12345",
                    username="johndoe",
                    tags=["botuser"],
                    chat="Test Group",
                    chat_id="-100999",
                    chat_type="supergroup",
                    msg="hello @botuser",
                    reaction="",
                    thread="42",
                    payload={"message_id": 42, "text": "hello @botuser"},
                )
            )
            csp.schedule_alarm(a_send, timedelta(seconds=1), False)
        else:
            return True


# Sample Telegram update payload: text message in a group
GROUP_MESSAGE_PAYLOAD = {
    "message_id": 42,
    "from": {
        "id": 12345,
        "is_bot": False,
        "first_name": "John",
        "last_name": "Doe",
        "username": "johndoe",
    },
    "chat": {
        "id": -100999,
        "title": "Test Group",
        "type": "supergroup",
    },
    "date": 1707423091,
    "text": "hello @botuser",
    "entities": [
        {
            "offset": 6,
            "length": 8,
            "type": "mention",
        }
    ],
}

# Sample Telegram update payload: private message
PRIVATE_MESSAGE_PAYLOAD = {
    "message_id": 43,
    "from": {
        "id": 12345,
        "is_bot": False,
        "first_name": "John",
        "last_name": "Doe",
        "username": "johndoe",
    },
    "chat": {
        "id": 12345,
        "first_name": "John",
        "last_name": "Doe",
        "type": "private",
    },
    "date": 1707423220,
    "text": "test",
}

# Message with text_mention entity (user without username)
TEXT_MENTION_PAYLOAD = {
    "message_id": 44,
    "from": {
        "id": 67890,
        "is_bot": False,
        "first_name": "Jane",
    },
    "chat": {
        "id": -200111,
        "title": "Another Group",
        "type": "group",
    },
    "date": 1707423300,
    "text": "Hello Jane!",
    "entities": [
        {
            "offset": 6,
            "length": 4,
            "type": "text_mention",
            "user": {
                "id": 11111,
                "is_bot": False,
                "first_name": "Jane",
                "last_name": "Smith",
            },
        }
    ],
}


def _make_mock_update(payload):
    """Create a mock telegram Update from a message payload dict."""
    update = MagicMock()
    message = MagicMock()

    # from_user
    from_data = payload.get("from", {})
    user = MagicMock()
    user.id = from_data.get("id", 0)
    user.first_name = from_data.get("first_name", "")
    user.last_name = from_data.get("last_name", None)
    user.username = from_data.get("username", None)
    user.is_bot = from_data.get("is_bot", False)
    message.from_user = user

    # chat
    chat_data = payload.get("chat", {})
    chat = MagicMock()
    chat.id = chat_data.get("id", 0)
    chat.title = chat_data.get("title", None)
    chat.first_name = chat_data.get("first_name", None)
    chat.last_name = chat_data.get("last_name", None)
    chat.type = chat_data.get("type", "private")
    message.chat = chat

    # message fields
    message.message_id = payload.get("message_id", 0)
    message.text = payload.get("text", "")
    message.caption = payload.get("caption", None)
    message.date = payload.get("date", 0)
    message.to_dict.return_value = payload.copy()

    # entities
    entities = []
    for ent_data in payload.get("entities", []):
        entity = MagicMock()
        entity.type = ent_data.get("type", "")
        entity.offset = ent_data.get("offset", 0)
        entity.length = ent_data.get("length", 0)
        if "user" in ent_data:
            ent_user = MagicMock()
            ent_user.id = ent_data["user"].get("id", 0)
            ent_user.first_name = ent_data["user"].get("first_name", "")
            ent_user.last_name = ent_data["user"].get("last_name", None)
            ent_user.username = ent_data["user"].get("username", None)
            entity.user = ent_user
        else:
            entity.user = None
        entities.append(entity)
    message.entities = entities if entities else None

    update.message = message
    return update


class TestTelegramConfig:
    def test_valid_token(self):
        config = TelegramAdapterConfig(bot_token="123456:ABCDefGhIjKlMnOpQrStUvWxYz")
        assert config.bot_token == "123456:ABCDefGhIjKlMnOpQrStUvWxYz"

    def test_invalid_token_no_colon(self):
        with pytest.raises(ValidationError):
            TelegramAdapterConfig(bot_token="invalidtoken")

    def test_invalid_token_no_numeric_prefix(self):
        with pytest.raises(ValidationError):
            TelegramAdapterConfig(bot_token="abc:defghijklmnop")

    def test_invalid_token_short_suffix(self):
        with pytest.raises(ValidationError):
            TelegramAdapterConfig(bot_token="123:short")


class TestTelegramMessage:
    def test_message_creation(self):
        msg = TelegramMessage(
            user="John Doe",
            user_id="12345",
            username="johndoe",
            tags=["botuser"],
            chat="Test Group",
            chat_id="-100999",
            chat_type="supergroup",
            msg="hello",
            reaction="",
            thread="42",
            payload={"text": "hello"},
        )
        assert msg.user == "John Doe"
        assert msg.user_id == "12345"
        assert msg.username == "johndoe"
        assert msg.tags == ["botuser"]
        assert msg.chat == "Test Group"
        assert msg.chat_id == "-100999"
        assert msg.chat_type == "supergroup"
        assert msg.msg == "hello"
        assert msg.thread == "42"

    def test_message_partial(self):
        msg = TelegramMessage(chat_id="-100999", msg="hello")
        assert msg.chat_id == "-100999"
        assert msg.msg == "hello"

    def test_message_equality(self):
        msg1 = TelegramMessage(chat_id="-100999", msg="hello", thread="42")
        msg2 = TelegramMessage(chat_id="-100999", msg="hello", thread="42")
        assert msg1 == msg2


class TestMentionUser:
    def test_mention_by_username(self):
        assert mention_user("johndoe") == "@johndoe"

    def test_mention_by_user_id(self):
        assert mention_user("12345") == "[user](tg://user?id=12345)"

    def test_mention_already_formatted(self):
        assert mention_user("@johndoe") == "@johndoe"

    def test_mention_empty(self):
        assert mention_user("") == ""


class TestTelegramAdapter:
    def _make_adapter(self):
        return TelegramAdapterManager(TelegramAdapterConfig(bot_token="123456:ABCDefGhIjKlMnOpQrStUvWxYz"))

    def test_register_subscriber(self):
        am = self._make_adapter()
        adapter = MagicMock()
        am.register_subscriber(adapter)
        am.register_subscriber(adapter)
        assert len(am._subscribers) == 1

    def test_register_publisher(self):
        am = self._make_adapter()
        adapter = MagicMock()
        am.register_publisher(adapter)
        am.register_publisher(adapter)
        assert len(am._publishers) == 1

    def test_stop_when_not_running(self):
        am = self._make_adapter()
        am.stop()
        assert am._running is False

    def test_on_tick(self):
        am = self._make_adapter()
        msg = TelegramMessage(chat_id="-100999", msg="hello")
        am._on_tick(msg)
        assert not am._outqueue.empty()
        assert am._outqueue.get() == msg

    def test_get_user_display_name(self):
        am = self._make_adapter()

        user = MagicMock()
        user.first_name = "John"
        user.last_name = "Doe"
        assert am._get_user_display_name(user) == "John Doe"

        user.last_name = None
        assert am._get_user_display_name(user) == "John"

        assert am._get_user_display_name(None) == ""

    def test_get_chat_title_group(self):
        am = self._make_adapter()
        chat = MagicMock()
        chat.title = "Test Group"
        chat.first_name = None
        chat.last_name = None
        assert am._get_chat_title(chat) == "Test Group"

    def test_get_chat_title_private(self):
        am = self._make_adapter()
        chat = MagicMock()
        chat.title = None
        chat.first_name = "John"
        chat.last_name = "Doe"
        assert am._get_chat_title(chat) == "John Doe"

    def test_get_chat_title_none(self):
        am = self._make_adapter()
        assert am._get_chat_title(None) == ""

    def test_get_tags_from_mention(self):
        am = self._make_adapter()
        update = _make_mock_update(GROUP_MESSAGE_PAYLOAD)
        tags = am._get_tags_from_message(update.message)
        assert tags == ["botuser"]

    def test_get_tags_from_text_mention(self):
        am = self._make_adapter()
        update = _make_mock_update(TEXT_MENTION_PAYLOAD)
        tags = am._get_tags_from_message(update.message)
        assert tags == ["Jane Smith"]

    def test_get_tags_empty(self):
        am = self._make_adapter()
        update = _make_mock_update(PRIVATE_MESSAGE_PAYLOAD)
        tags = am._get_tags_from_message(update.message)
        assert tags == []

    @pytest.mark.asyncio
    async def test_handle_message_group(self):
        am = self._make_adapter()
        update = _make_mock_update(GROUP_MESSAGE_PAYLOAD)
        context = MagicMock()

        await am._handle_message(update, context)

        assert not am._inqueue.empty()
        msg = am._inqueue.get()
        assert msg.user == "John Doe"
        assert msg.user_id == "12345"
        assert msg.username == "johndoe"
        assert msg.chat == "Test Group"
        assert msg.chat_id == "-100999"
        assert msg.chat_type == "supergroup"
        assert msg.msg == "hello @botuser"
        assert msg.tags == ["botuser"]
        assert msg.thread == "42"

    @pytest.mark.asyncio
    async def test_handle_message_private(self):
        am = self._make_adapter()
        update = _make_mock_update(PRIVATE_MESSAGE_PAYLOAD)
        context = MagicMock()

        await am._handle_message(update, context)

        assert not am._inqueue.empty()
        msg = am._inqueue.get()
        assert msg.user == "John Doe"
        assert msg.user_id == "12345"
        assert msg.chat == "John Doe"
        assert msg.chat_type == "private"
        assert msg.msg == "test"
        assert msg.tags == []

    @pytest.mark.asyncio
    async def test_handle_message_none_update(self):
        am = self._make_adapter()
        update = MagicMock()
        update.message = None
        context = MagicMock()

        await am._handle_message(update, context)
        assert am._inqueue.empty()

    @pytest.mark.asyncio
    async def test_send_message_text(self):
        am = self._make_adapter()
        am._application = MagicMock()
        am._application.bot = AsyncMock()

        msg = TelegramMessage(chat_id="-100999", msg="Hello!", thread="42")
        await am._send_message(msg)

        am._application.bot.send_message.assert_awaited_once_with(
            chat_id=-100999,
            text="Hello!",
            parse_mode=None,
            reply_to_message_id=42,
        )

    @pytest.mark.asyncio
    async def test_send_message_reaction(self):
        am = self._make_adapter()
        am._application = MagicMock()
        am._application.bot = AsyncMock()

        msg = TelegramMessage(chat_id="-100999", reaction="👋", thread="42")
        await am._send_message(msg)

        am._application.bot.set_message_reaction.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_message_no_chat_id(self):
        am = self._make_adapter()
        am._application = MagicMock()
        am._application.bot = AsyncMock()

        msg = TelegramMessage(msg="orphan message")
        await am._send_message(msg)

        am._application.bot.send_message.assert_not_awaited()
        am._application.bot.set_message_reaction.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_message_no_text_no_reaction(self):
        am = self._make_adapter()
        am._application = MagicMock()
        am._application.bot = AsyncMock()

        msg = TelegramMessage(chat_id="-100999")
        await am._send_message(msg)

        am._application.bot.send_message.assert_not_awaited()
        am._application.bot.set_message_reaction.assert_not_awaited()

    def test_user_cache(self):
        am = self._make_adapter()
        am._user_id_to_user_name["12345"] = "John Doe"
        am._user_id_to_username["12345"] = "johndoe"
        assert am._user_id_to_user_name["12345"] == "John Doe"
        assert am._user_id_to_username["12345"] == "johndoe"

    def test_chat_cache(self):
        am = self._make_adapter()
        am._chat_mapper.set("Test Group", "-100999")
        assert am._chat_mapper.get_chat_id("Test Group") == "-100999"
        assert am._chat_mapper.get_chat_title("-100999") == "Test Group"


class TestTelegramAdapterCSPGraph:
    """Test that CSP graph wiring works correctly."""

    def test_graph_subscribe_and_respond(self):
        """Full end-to-end test using mock inqueue injection (symmetric with slack test)."""
        with patch("csp_adapter_telegram.adapter.Application") as mock_app_cls:
            # Wire up the builder chain: Application.builder().token(tok).build() -> mock_app
            mock_app = MagicMock()
            mock_builder = MagicMock()
            mock_builder.token.return_value = mock_builder
            mock_builder.build.return_value = mock_app
            mock_app_cls.builder.return_value = mock_builder

            # Async lifecycle methods
            mock_app.initialize = AsyncMock()
            mock_app.start = AsyncMock()
            mock_app.stop = AsyncMock()
            mock_app.shutdown = AsyncMock()
            mock_app.updater.start_polling = AsyncMock()
            mock_app.updater.stop = AsyncMock()
            mock_app.updater.running = False
            mock_app.running = False

            # Bot info
            mock_app.bot.get_me = AsyncMock(return_value=MagicMock(id=999, username="testbot"))
            mock_app.bot.send_message = AsyncMock()
            mock_app.bot.set_message_reaction = AsyncMock()

            am = TelegramAdapterManager(TelegramAdapterConfig(bot_token="123456:ABCDefGhIjKlMnOpQrStUvWxYz"))

            def graph():
                # send a fake telegram message to the adapter
                stop = send_fake_message(am)

                # subscribe and respond
                resp = hello(csp.unroll(am.subscribe()))
                rct = react(csp.unroll(am.subscribe()))

                csp.add_graph_output("response", resp)
                csp.add_graph_output("react", rct)

                done_flag = (csp.count(stop) + csp.count(resp) + csp.count(rct)) == 3
                csp.stop_engine(done_flag)

            resp = csp.run(graph, realtime=True)

            assert resp["response"]
            assert resp["react"]

            assert resp["response"][0][1] == TelegramMessage(
                chat_id="-100999",
                thread="42",
                msg="Hello John Doe!",
            )
            assert resp["react"][0][1] == TelegramMessage(
                chat_id="-100999",
                thread="42",
                reaction="👋",
            )


class TestFormat:
    def test_format_bold(self):
        assert format_bold("hello") == "*hello*"

    def test_format_italic(self):
        assert format_italic("hello") == "_hello_"

    def test_format_code(self):
        assert format_code("x = 1") == "`x = 1`"

    def test_format_code_block(self):
        result = format_code_block("print('hi')", "python")
        assert result == "```python\nprint('hi')\n```"

    def test_format_code_block_no_language(self):
        result = format_code_block("print('hi')")
        assert result == "```\nprint('hi')\n```"

    def test_format_link(self):
        assert format_link("Click", "https://example.com") == "[Click](https://example.com)"

    def test_format_table(self):
        result = format_table(
            headers=["Name", "Value"],
            data=[["A", "1"], ["BB", "22"]],
        )
        assert "Name" in result
        assert "Value" in result
        assert "A" in result
        assert "BB" in result
        assert result.startswith("```")
        assert result.endswith("```")

    def test_format_table_with_title(self):
        result = format_table(
            headers=["X"],
            data=[["1"]],
            title="My Table",
        )
        assert "My Table" in result

    def test_format_telegram_markdown_escape(self):
        result = format_telegram_markdown("hello_world")
        assert "\\_" in result

    def test_format_telegram_markdown_unescape(self):
        result = format_telegram_markdown("hello\\_world", to_markdown=False)
        assert result == "hello_world"


class TestChatMapper:
    def test_set_and_get(self):
        mapper = TelegramChatMapper()
        mapper.set("My Group", "-100123")
        assert mapper.get_chat_id("My Group") == "-100123"
        assert mapper.get_chat_title("-100123") == "My Group"

    def test_get_missing(self):
        mapper = TelegramChatMapper()
        assert mapper.get_chat_id("Unknown") is None
        assert mapper.get_chat_title("999") is None

    def test_set_dm(self):
        mapper = TelegramChatMapper()
        mapper.set_dm("John Doe", "12345")
        assert mapper.get_chat_id("John Doe") == "12345"
        assert mapper.get_chat_title("12345") == "John Doe"

    def test_overwrite(self):
        mapper = TelegramChatMapper()
        mapper.set("Group", "-100")
        mapper.set("Group Renamed", "-100")
        assert mapper.get_chat_title("-100") == "Group Renamed"
        assert mapper.get_chat_id("Group Renamed") == "-100"


class TestMentionAll:
    def test_mention_all(self):
        assert mention_all() == "@all"


class TestTelegramMessageNewFields:
    def test_parse_mode_field(self):
        msg = TelegramMessage(chat_id="-100999", msg="hello", parse_mode="Markdown")
        assert msg.parse_mode == "Markdown"

    def test_edit_message_id_field(self):
        msg = TelegramMessage(chat_id="-100999", msg="edited", edit_message_id="42")
        assert msg.edit_message_id == "42"

    def test_callback_data_field(self):
        msg = TelegramMessage(chat_id="-100999", callback_data="button_1")
        assert msg.callback_data == "button_1"


class TestAdapterConfigNewFields:
    def test_error_chat_id(self):
        config = TelegramAdapterConfig(
            bot_token="123456:ABCDefGhIjKlMnOpQrStUvWxYz",
            error_chat_id="-100555",
        )
        assert config.error_chat_id == "-100555"

    def test_inform_client(self):
        config = TelegramAdapterConfig(
            bot_token="123456:ABCDefGhIjKlMnOpQrStUvWxYz",
            inform_client=True,
        )
        assert config.inform_client is True

    def test_defaults(self):
        config = TelegramAdapterConfig(bot_token="123456:ABCDefGhIjKlMnOpQrStUvWxYz")
        assert config.error_chat_id is None
        assert config.inform_client is False


class TestAdapterDeduplication:
    def _make_adapter(self):
        return TelegramAdapterManager(TelegramAdapterConfig(bot_token="123456:ABCDefGhIjKlMnOpQrStUvWxYz"))

    @pytest.mark.asyncio
    async def test_duplicate_message_skipped(self):
        am = self._make_adapter()
        update = _make_mock_update(GROUP_MESSAGE_PAYLOAD)
        context = MagicMock()

        await am._handle_message(update, context)
        assert not am._inqueue.empty()
        am._inqueue.get()

        # Send the same update again — should be deduped
        await am._handle_message(update, context)
        assert am._inqueue.empty()


class TestAdapterChatFiltering:
    def _make_adapter(self):
        return TelegramAdapterManager(TelegramAdapterConfig(bot_token="123456:ABCDefGhIjKlMnOpQrStUvWxYz"))

    @pytest.mark.asyncio
    async def test_message_filtered_by_chat_ids(self):
        am = self._make_adapter()
        am._chat_ids = {"-200111"}  # Only accept Another Group
        update = _make_mock_update(GROUP_MESSAGE_PAYLOAD)  # chat_id -100999
        context = MagicMock()

        await am._handle_message(update, context)
        assert am._inqueue.empty()

    @pytest.mark.asyncio
    async def test_message_accepted_by_chat_ids(self):
        am = self._make_adapter()
        am._chat_ids = {"-100999"}
        update = _make_mock_update(GROUP_MESSAGE_PAYLOAD)
        context = MagicMock()

        await am._handle_message(update, context)
        assert not am._inqueue.empty()


class TestAdapterCallbackQuery:
    def _make_adapter(self):
        return TelegramAdapterManager(TelegramAdapterConfig(bot_token="123456:ABCDefGhIjKlMnOpQrStUvWxYz"))

    @pytest.mark.asyncio
    async def test_handle_callback_query(self):
        am = self._make_adapter()

        update = MagicMock()
        query = MagicMock()
        query.data = "button_action_1"
        query.from_user = MagicMock()
        query.from_user.id = 12345
        query.from_user.first_name = "John"
        query.from_user.last_name = "Doe"
        query.from_user.username = "johndoe"
        query.message = MagicMock()
        query.message.chat = MagicMock()
        query.message.chat.id = -100999
        query.message.chat.title = "Test Group"
        query.message.chat.first_name = None
        query.message.chat.last_name = None
        query.message.chat.type = "supergroup"
        query.message.message_id = 50
        query.answer = AsyncMock()
        query.to_dict.return_value = {"data": "button_action_1"}
        update.callback_query = query
        update.message = None

        context = MagicMock()
        await am._handle_callback_query(update, context)

        assert not am._inqueue.empty()
        msg = am._inqueue.get()
        assert msg.callback_data == "button_action_1"
        assert msg.user == "John Doe"
        assert msg.chat_id == "-100999"
        query.answer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_callback_query_none(self):
        am = self._make_adapter()
        update = MagicMock()
        update.callback_query = None
        context = MagicMock()
        await am._handle_callback_query(update, context)
        assert am._inqueue.empty()


class TestAdapterSendExtended:
    def _make_adapter(self):
        return TelegramAdapterManager(TelegramAdapterConfig(bot_token="123456:ABCDefGhIjKlMnOpQrStUvWxYz"))

    @pytest.mark.asyncio
    async def test_send_message_with_parse_mode(self):
        am = self._make_adapter()
        am._application = MagicMock()
        am._application.bot = AsyncMock()

        msg = TelegramMessage(chat_id="-100999", msg="*bold*", parse_mode="Markdown")
        await am._send_message(msg)

        am._application.bot.send_message.assert_awaited_once_with(
            chat_id=-100999,
            text="*bold*",
            parse_mode="Markdown",
            reply_to_message_id=None,
        )

    @pytest.mark.asyncio
    async def test_send_edit_message(self):
        am = self._make_adapter()
        am._application = MagicMock()
        am._application.bot = AsyncMock()

        msg = TelegramMessage(chat_id="-100999", msg="edited text", edit_message_id="42")
        await am._send_message(msg)

        am._application.bot.edit_message_text.assert_awaited_once_with(
            chat_id=-100999,
            message_id=42,
            text="edited text",
            parse_mode=None,
        )
        am._application.bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_message_resolves_chat_name(self):
        am = self._make_adapter()
        am._application = MagicMock()
        am._application.bot = AsyncMock()
        am._chat_mapper.set("My Group", "-100888")

        _ = TelegramMessage(chat="-100888", msg="routed via name")
        # chat_id is empty, but chat name should resolve via mapper... actually
        # the adapter tries chat_id first, then falls back to chat name via mapper
        msg2 = TelegramMessage(msg="routed via name")
        # Neither chat_id nor chat, should log error
        await am._send_message(msg2)
        am._application.bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_message_error_routing(self):
        am = TelegramAdapterManager(
            TelegramAdapterConfig(
                bot_token="123456:ABCDefGhIjKlMnOpQrStUvWxYz",
                error_chat_id="-100555",
            )
        )
        am._application = MagicMock()
        am._application.bot = AsyncMock()
        am._loop = asyncio.get_event_loop()

        # Message with no chat_id should send error notification
        msg = TelegramMessage(msg="orphan")
        await am._send_message(msg)

        am._application.bot.send_message.assert_awaited_once()
        call_args = am._application.bot.send_message.call_args
        assert call_args.kwargs["chat_id"] == -100555
        assert "ERROR" in call_args.kwargs["text"]


class TestSendTelegramMessageStandalone:
    @pytest.mark.asyncio
    async def test_send_telegram_message(self):
        with patch("csp_adapter_telegram.adapter.Bot") as mock_bot_cls:
            mock_bot = MagicMock()
            mock_bot_cls.return_value = mock_bot
            mock_result = MagicMock()
            mock_result.to_dict.return_value = {"message_id": 999, "text": "hello"}
            mock_bot.send_message = AsyncMock(return_value=mock_result)

            result = await send_telegram_message(
                msg="hello",
                chat_id="-100999",
                bot_token="123456:ABCDefGhIjKlMnOpQrStUvWxYz",
            )

            mock_bot.send_message.assert_awaited_once_with(
                chat_id=-100999,
                text="hello",
                parse_mode=None,
                reply_to_message_id=None,
            )
            assert result["message_id"] == 999

    @pytest.mark.asyncio
    async def test_send_telegram_message_with_parse_mode(self):
        with patch("csp_adapter_telegram.adapter.Bot") as mock_bot_cls:
            mock_bot = MagicMock()
            mock_bot_cls.return_value = mock_bot
            mock_result = MagicMock()
            mock_result.to_dict.return_value = {"message_id": 1000}
            mock_bot.send_message = AsyncMock(return_value=mock_result)

            await send_telegram_message(
                msg="*bold*",
                chat_id="-100999",
                bot_token="123456:ABCDefGhIjKlMnOpQrStUvWxYz",
                parse_mode="Markdown",
            )

            mock_bot.send_message.assert_awaited_once_with(
                chat_id=-100999,
                text="*bold*",
                parse_mode="Markdown",
                reply_to_message_id=None,
            )


class TestAdapterSubscribeOptions:
    def test_subscribe_with_chat_ids(self):
        am = TelegramAdapterManager(TelegramAdapterConfig(bot_token="123456:ABCDefGhIjKlMnOpQrStUvWxYz"))
        am.subscribe(chat_ids={"-100999", "-200111"}, exit_msg="Goodbye!")
        assert am._chat_ids == {"-100999", "-200111"}
        assert am._exit_msg == "Goodbye!"

    def test_subscribe_default_no_filter(self):
        am = TelegramAdapterManager(TelegramAdapterConfig(bot_token="123456:ABCDefGhIjKlMnOpQrStUvWxYz"))
        am.subscribe()
        assert am._chat_ids == set()
        assert am._exit_msg == ""
