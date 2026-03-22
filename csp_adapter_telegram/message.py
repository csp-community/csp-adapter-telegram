from typing import List

from csp.impl.struct import Struct

__all__ = ("TelegramMessage",)


class TelegramMessage(Struct):
    user: str
    """display name of the author of the message"""

    user_id: str
    """platform-specific id of the author of the message"""

    username: str
    """telegram username of the author (without @), if available"""

    tags: List[str]
    """list of users mentioned in the message via entities"""

    chat: str
    """title of the chat (group/channel name), or user display name for private chats"""

    chat_id: str
    """id of the chat for the telegram message"""

    chat_type: str
    """type of the chat: "private", "group", "supergroup", or "channel" """

    msg: str
    """parsed text of the message"""

    reaction: str
    """emoji reaction to put on a message. Exclusive with `msg`, requires `thread`"""

    thread: str
    """message_id to reply to, or message_id on which to apply reaction"""

    parse_mode: str
    """parse mode for the message text: "", "Markdown", "MarkdownV2", or "HTML" """

    edit_message_id: str
    """if set, edit this existing message instead of sending a new one"""

    callback_data: str
    """callback data from an inline keyboard button press (like Symphony's form_values)"""

    payload: dict
    """raw telegram message payload"""
