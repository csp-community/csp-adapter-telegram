__all__ = ("mention_user", "mention_all")


def mention_user(user_id_or_username: str) -> str:
    """Convenience method to create a Telegram user mention.

    Telegram supports two mention formats:
    - By user ID (works for all users): creates a text_mention entity in the API
    - By username (only works for users with usernames): @username

    For inline text usage, this returns the @username format or a
    Markdown-compatible link for numeric IDs.
    """
    if not user_id_or_username:
        return ""
    # Already formatted
    if user_id_or_username.startswith("@"):
        return user_id_or_username
    # Numeric user ID -> use Markdown link format
    if user_id_or_username.isdigit():
        return f"[user](tg://user?id={user_id_or_username})"
    # Username
    return f"@{user_id_or_username}"


def mention_all() -> str:
    """Return a mention that notifies all members in a group.

    Note: Telegram does not have a built-in @all.  This is a
    convention that some bots use; the text is not rendered
    specially by the Telegram client.
    """
    return "@all"
