"""Tests for csp-adapter-telegram."""

import tempfile

import pytest
from pydantic import ValidationError

from csp_adapter_telegram import (
    MockTelegramBackend,
    TelegramAdapter,
    TelegramAdapterConfig,
    TelegramAdapterManager,
    TelegramBackend,
    TelegramChannel,
    TelegramChatType,
    TelegramConfig,
    TelegramMessage,
    TelegramPresence,
    TelegramUser,
    mention_channel,
    mention_user,
)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


class TestImports:
    def test_all_exports(self):
        """All __all__ exports are importable and non-None."""
        assert TelegramAdapter is not None
        assert TelegramAdapterManager is TelegramAdapter
        assert TelegramBackend is not None
        assert TelegramConfig is not None
        assert TelegramMessage is not None
        assert TelegramUser is not None
        assert TelegramChannel is not None
        assert TelegramChatType is not None
        assert TelegramPresence is not None
        assert MockTelegramBackend is not None
        assert TelegramAdapterConfig is not None
        assert mention_user is not None
        assert mention_channel is not None

    def test_version(self):
        import csp_adapter_telegram

        assert hasattr(csp_adapter_telegram, "__version__")
        assert isinstance(csp_adapter_telegram.__version__, str)


# ---------------------------------------------------------------------------
# Legacy TelegramAdapterConfig
# ---------------------------------------------------------------------------


class TestTelegramAdapterConfig:
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

    def test_token_from_file(self):
        token = "123456:ABCDefGhIjKlMnOpQrStUvWxYz"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(token)
            f.flush()
            config = TelegramAdapterConfig(bot_token=f.name)
        assert config.bot_token == token

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

    def test_to_telegram_config(self):
        token = "123456:ABCDefGhIjKlMnOpQrStUvWxYz"
        legacy = TelegramAdapterConfig(bot_token=token)
        chatom_config = legacy.to_telegram_config()
        assert chatom_config.bot_token_str == token


# ---------------------------------------------------------------------------
# Telegram models (chatom re-exports)
# ---------------------------------------------------------------------------


class TestTelegramMessage:
    def test_create_basic(self):
        msg = TelegramMessage(content="Hello!", channel=TelegramChannel(id="456", name="general"))
        assert msg.content == "Hello!"
        assert msg.channel_id == "456"
        assert msg.channel_name == "general"

    def test_create_with_author(self):
        msg = TelegramMessage(
            chat_id="-100999",
            content="Hello!",
            author=TelegramUser(id="123", name="TestUser"),
        )
        assert msg.author.id == "123"
        assert msg.author.name == "TestUser"

    def test_text_alias(self):
        msg = TelegramMessage(text="Hello via alias!")
        assert msg.content == "Hello via alias!"

    def test_default_values(self):
        msg = TelegramMessage()
        assert msg.content == ""
        assert msg.is_edited is False
        assert msg.is_pinned is False
        assert msg.is_bot is False

    def test_chat_id_field(self):
        msg = TelegramMessage(chat_id="-100999")
        assert msg.chat_id == "-100999"

    def test_message_id_field(self):
        msg = TelegramMessage(message_id=42)
        assert msg.message_id == 42

    def test_reply_to_message_id(self):
        msg = TelegramMessage(reply_to_message_id=42)
        assert msg.reply_to_message_id == 42


class TestTelegramUser:
    def test_create_basic(self):
        user = TelegramUser(id="123", name="TestUser")
        assert user.id == "123"
        assert user.name == "TestUser"

    def test_with_handle(self):
        user = TelegramUser(id="123", name="TestUser", handle="testuser")
        assert user.handle == "testuser"

    def test_bot_user(self):
        user = TelegramUser(id="999", name="Bot", is_bot=True)
        assert user.is_bot is True

    def test_username(self):
        user = TelegramUser(id="123", name="TestUser", username="testuser")
        assert user.username == "testuser"

    def test_first_last_name(self):
        user = TelegramUser(id="123", name="John Doe", first_name="John", last_name="Doe")
        assert user.first_name == "John"
        assert user.last_name == "Doe"


class TestTelegramChannel:
    def test_create_basic(self):
        channel = TelegramChannel(id="456", name="general")
        assert channel.id == "456"
        assert channel.name == "general"

    def test_chat_type(self):
        assert TelegramChatType is not None
        assert TelegramChatType.PRIVATE == "private"
        assert TelegramChatType.GROUP == "group"
        assert TelegramChatType.SUPERGROUP == "supergroup"
        assert TelegramChatType.CHANNEL == "channel"

    def test_with_chat_type(self):
        channel = TelegramChannel(id="456", name="general", chat_type=TelegramChatType.SUPERGROUP)
        assert channel.chat_type == TelegramChatType.SUPERGROUP


class TestTelegramPresence:
    def test_create_basic(self):
        presence = TelegramPresence(status="online")
        assert str(presence.status.value) == "online"


# ---------------------------------------------------------------------------
# Mentions (chatom re-exports)
# ---------------------------------------------------------------------------


class TestMentions:
    def test_mention_user(self):
        user = TelegramUser(id="123", name="TestUser", username="testuser")
        assert mention_user(user) == "@testuser"

    def test_mention_user_no_username(self):
        user = TelegramUser(id="123", name="TestUser")
        result = mention_user(user)
        assert "123" in result
        assert "TestUser" in result

    def test_mention_channel(self):
        channel = TelegramChannel(id="456", name="general")
        assert mention_channel(channel) == "#general"


# ---------------------------------------------------------------------------
# MockTelegramBackend
# ---------------------------------------------------------------------------


class TestMockBackend:
    def _make_mock(self):
        config = TelegramConfig(bot_token="123456:ABCDefGhIjKlMnOpQrStUvWxYz")
        mock = MockTelegramBackend(config=config)
        return mock

    @pytest.mark.asyncio
    async def test_connect_disconnect(self):
        mock = self._make_mock()
        await mock.connect()
        await mock.disconnect()

    def test_add_mock_user(self):
        mock = self._make_mock()
        user = mock.add_mock_user(id="123", name="TestUser", handle="testuser")
        assert user.id == "123"
        assert user.name == "TestUser"
        assert user.handle == "testuser"

    def test_add_mock_channel(self):
        mock = self._make_mock()
        channel = mock.add_mock_channel(id="-100456", name="general")
        assert channel.id == "-100456"
        assert channel.name == "general"

    @pytest.mark.asyncio
    async def test_fetch_user(self):
        mock = self._make_mock()
        mock.add_mock_user(id="123", name="TestUser", handle="testuser")
        await mock.connect()
        user = await mock.fetch_user(id="123")
        assert user is not None
        assert user.name == "TestUser"

    @pytest.mark.asyncio
    async def test_fetch_user_not_found(self):
        mock = self._make_mock()
        await mock.connect()
        user = await mock.fetch_user(id="nonexistent")
        assert user is None

    @pytest.mark.asyncio
    async def test_fetch_channel(self):
        mock = self._make_mock()
        mock.add_mock_channel(id="-100456", name="general")
        await mock.connect()
        channel = await mock.fetch_channel(id="-100456")
        assert channel is not None
        assert channel.name == "general"

    @pytest.mark.asyncio
    async def test_fetch_channel_not_found(self):
        mock = self._make_mock()
        await mock.connect()
        channel = await mock.fetch_channel(id="nonexistent")
        assert channel is None

    @pytest.mark.asyncio
    async def test_send_message(self):
        mock = self._make_mock()
        mock.add_mock_channel(id="-100456", name="general")
        await mock.connect()
        msg = await mock.send_message("-100456", "Hello!")
        assert msg is not None
        assert msg.content == "Hello!"
        assert len(mock._sent_messages) == 1

    @pytest.mark.asyncio
    async def test_add_reaction(self):
        mock = self._make_mock()
        mock.add_mock_user(id="123", name="TestUser")
        mock.add_mock_channel(id="-100456", name="general")
        mock.add_mock_message(channel_id="-100456", user_id="123", content="React to this")
        await mock.connect()

        sent_msg = await mock.send_message("-100456", "test")
        await mock.add_reaction(sent_msg, "👋")
        assert len(mock._reactions) == 1


# ---------------------------------------------------------------------------
# TelegramAdapter
# ---------------------------------------------------------------------------


class TestTelegramAdapter:
    def test_create_adapter(self):
        config = TelegramConfig(bot_token="123456:ABCDefGhIjKlMnOpQrStUvWxYz")
        adapter = TelegramAdapter(config)
        assert adapter is not None

    def test_adapter_manager_alias(self):
        assert TelegramAdapterManager is TelegramAdapter
