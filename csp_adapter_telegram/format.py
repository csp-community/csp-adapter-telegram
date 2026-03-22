from typing import List, Optional

__all__ = ("format_telegram_markdown", "format_bold", "format_italic", "format_code", "format_code_block", "format_link", "format_table")

# Telegram MarkdownV2 special characters that need escaping
_MARKDOWNV2_SPECIAL = r"_*[]()~`>#+-=|{}.!"


def format_telegram_markdown(text: str, to_markdown: bool = True) -> str:
    """Escape or unescape Telegram MarkdownV2 special characters.

    Symmetric with Symphony's ``format_with_message_ml``.

    If *to_markdown* is True, special characters are escaped so the text
    renders as literal text in MarkdownV2 mode.  If False, the escaping
    is reversed.
    """
    for ch in _MARKDOWNV2_SPECIAL:
        escaped = f"\\{ch}"
        if to_markdown:
            text = text.replace(ch, escaped)
        else:
            text = text.replace(escaped, ch)
    return text


def format_bold(text: str) -> str:
    """Wrap *text* in Telegram Markdown bold markers."""
    return f"*{text}*"


def format_italic(text: str) -> str:
    """Wrap *text* in Telegram Markdown italic markers."""
    return f"_{text}_"


def format_code(text: str) -> str:
    """Wrap *text* in Telegram Markdown inline-code markers."""
    return f"`{text}`"


def format_code_block(text: str, language: str = "") -> str:
    """Wrap *text* in a fenced code block with an optional language tag."""
    return f"```{language}\n{text}\n```"


def format_link(text: str, url: str) -> str:
    """Create a Telegram Markdown hyperlink."""
    return f"[{text}]({url})"


def format_table(headers: List[str], data: List[List[str]], title: Optional[str] = None) -> str:
    """Render a table as a fixed-width code block (Telegram has no native tables).

    The result is a pre-formatted code block suitable for ``parse_mode="Markdown"``.
    """
    all_rows = [headers] + data
    col_widths = [max(len(str(row[i])) for row in all_rows) for i in range(len(headers))]

    def _fmt_row(row):
        return " | ".join(str(cell).ljust(w) for cell, w in zip(row, col_widths))

    lines = []
    if title:
        lines.append(title)
    lines.append(_fmt_row(headers))
    lines.append("-+-".join("-" * w for w in col_widths))
    for row in data:
        lines.append(_fmt_row(row))

    return format_code_block("\n".join(lines))
