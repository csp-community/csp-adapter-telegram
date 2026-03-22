from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator

__all__ = ("TelegramAdapterConfig",)


class TelegramAdapterConfig(BaseModel):
    """A config class that holds the required information to interact with Telegram."""

    bot_token: str = Field(description="The bot token from @BotFather")
    error_chat_id: Optional[str] = Field(None, description="Chat ID to redirect error messages to, if a message fails to send")
    inform_client: bool = Field(False, description="Whether to inform the intended chat that a message failed to send")

    @field_validator("bot_token")
    def validate_bot_token(cls, v):
        # Token can be provided as a file path
        if Path(v).exists():
            v = Path(v).read_text().strip()
        # Telegram tokens look like "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        if ":" in v:
            parts = v.split(":", 1)
            if parts[0].isdigit() and len(parts[1]) >= 10:
                return v
        raise ValueError("Bot token must be a valid Telegram bot token (numeric_id:alphanumeric_string) or a file path")
