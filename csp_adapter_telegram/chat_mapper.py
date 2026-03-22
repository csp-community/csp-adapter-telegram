import threading
from logging import getLogger
from typing import Dict, Optional

__all__ = ("TelegramChatMapper",)

log = getLogger(__file__)


class TelegramChatMapper:
    """Thread-safe bidirectional mapper between chat titles/usernames and chat IDs.

    Symmetric with Symphony's ``SymphonyRoomMapper``.
    """

    def __init__(self):
        self._title_to_id: Dict[str, str] = {}
        self._id_to_title: Dict[str, str] = {}
        self._lock = threading.Lock()

    def get_chat_id(self, title_or_username: str) -> Optional[str]:
        """Return the cached chat ID for a given title or username, or ``None``."""
        with self._lock:
            return self._title_to_id.get(title_or_username)

    def get_chat_title(self, chat_id: str) -> Optional[str]:
        """Return the cached title for a given chat ID, or ``None``."""
        with self._lock:
            return self._id_to_title.get(chat_id)

    def set(self, title: str, chat_id: str) -> None:
        """Register a bidirectional mapping between *title* and *chat_id*."""
        with self._lock:
            self._title_to_id[title] = chat_id
            self._id_to_title[chat_id] = title

    def set_dm(self, user_display_name: str, chat_id: str) -> None:
        """Register a private/DM chat, keyed by the user's display name."""
        self.set(user_display_name, chat_id)
