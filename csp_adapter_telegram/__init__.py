"""CSP adapter for Telegram using chatom backend."""

__version__ = "0.2.0"

# Re-export from chatom.telegram for convenience
from chatom.telegram import (
    MockTelegramBackend,
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

# Export the adapter
from .adapter import TelegramAdapter, TelegramAdapterManager

# Legacy imports for backwards compatibility
from .adapter_config import TelegramAdapterConfig

__all__ = (
    # Adapter
    "TelegramAdapter",
    "TelegramAdapterManager",  # Legacy alias
    # Backend and config (from chatom)
    "TelegramBackend",
    "TelegramConfig",
    # Models (from chatom)
    "TelegramMessage",
    "TelegramUser",
    "TelegramChannel",
    "TelegramChatType",
    "TelegramPresence",
    # Utilities (from chatom)
    "mention_user",
    "mention_channel",
    # Testing
    "MockTelegramBackend",
    # Legacy
    "TelegramAdapterConfig",
)
