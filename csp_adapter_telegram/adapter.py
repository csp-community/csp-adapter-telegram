"""Telegram CSP adapter using chatom backend.

This module provides a CSP adapter for Telegram that wraps the chatom TelegramBackend.
"""

import asyncio
import logging
import threading
from typing import Optional, Set

import csp
from chatom.csp import BackendAdapter
from chatom.telegram import TelegramBackend, TelegramConfig, TelegramMessage
from csp import ts

__all__ = ("TelegramAdapter", "TelegramAdapterManager")

log = logging.getLogger(__name__)


class TelegramAdapter(BackendAdapter):
    """CSP adapter for Telegram using the chatom TelegramBackend.

    This adapter wraps the chatom TelegramBackend and provides CSP
    graph/node methods for reading and writing messages.

    Attributes:
        backend: The underlying TelegramBackend.

    Example:
        >>> from csp_adapter_telegram import TelegramAdapter, TelegramConfig
        >>>
        >>> config = TelegramConfig(bot_token="123456:ABC-DEF...")
        >>> adapter = TelegramAdapter(config=config)
        >>>
        >>> @csp.graph
        ... def my_graph():
        ...     messages = adapter.subscribe()
        ...     responses = process(messages)
        ...     adapter.publish(responses)
        >>>
        >>> csp.run(my_graph, starttime=datetime.now(), endtime=timedelta(hours=1))
    """

    def __init__(self, config: TelegramConfig):
        """Initialize the Telegram adapter.

        Args:
            config: Telegram configuration.
        """
        backend = TelegramBackend(config=config)
        super().__init__(backend)

    # NOTE: Cannot use @csp.graph decorator, https://github.com/Point72/csp/issues/183
    def subscribe(
        self,
        channels: Optional[Set[str]] = None,
        chats: Optional[Set[str]] = None,
        skip_own: bool = True,
        skip_history: bool = True,
    ) -> ts[[TelegramMessage]]:
        """Subscribe to messages from Telegram.

        Args:
            channels: Optional set of chat IDs or names to filter (alias for chats).
            chats: Optional set of chat IDs or names to filter.
                Names will be resolved to IDs at connection time.
            skip_own: If True, skip messages from the bot itself.
            skip_history: If True, skip messages before stream started.

        Returns:
            Time series of TelegramMessage lists.

        Example:
            >>> @csp.graph
            ... def my_graph():
            ...     messages = adapter.subscribe(chats={"-100999", "My Group"})
            ...     csp.print("Received", messages)
        """
        filter_channels = channels if channels is not None else chats
        return super().subscribe(
            channels=filter_channels,
            skip_own=skip_own,
            skip_history=skip_history,
        )

    # NOTE: Cannot use @csp.graph decorator, https://github.com/Point72/csp/issues/183
    def publish(self, msg: ts[TelegramMessage]):
        """Publish messages to Telegram.

        Args:
            msg: Time series of TelegramMessage to send.

        Example:
            >>> @csp.graph
            ... def my_graph():
            ...     response = csp.const(TelegramMessage(
            ...         chat_id="-100999",
            ...         content="Hello, World!",
            ...     ))
            ...     adapter.publish(response)
        """
        super().publish(msg=msg)

    @csp.node
    def _add_reaction(self, msg: ts[TelegramMessage], emoji: ts[str], timeout: float = 5.0):
        """Internal node for adding reactions to messages."""
        if csp.ticked(msg, emoji):
            message = msg
            reaction_emoji = emoji
            config = self._backend.config
            backend_class = type(self._backend)

            def run_reaction():
                async def add_reaction_async():
                    thread_backend = backend_class(config=config)
                    try:
                        await asyncio.wait_for(thread_backend.connect(), timeout=timeout)
                        await asyncio.wait_for(
                            thread_backend.add_reaction(
                                message=message,
                                emoji=reaction_emoji,
                            ),
                            timeout=timeout,
                        )
                    except asyncio.TimeoutError:
                        log.error("Timeout adding reaction")
                    except Exception:
                        log.exception("Failed adding reaction")
                    finally:
                        try:
                            await thread_backend.disconnect()
                        except Exception:
                            pass

                try:
                    asyncio.run(add_reaction_async())
                except Exception:
                    log.exception("Error in reaction thread")

            thread = threading.Thread(target=run_reaction, daemon=True)
            thread.start()

    # NOTE: Cannot use @csp.graph decorator, https://github.com/Point72/csp/issues/183
    def publish_reaction(self, msg: ts[TelegramMessage], emoji: ts[str], timeout: float = 5.0):
        """Add a reaction to a Telegram message.

        Args:
            msg: Time series of TelegramMessages to react to.
            emoji: Time series of emoji strings (e.g., "👋", "❤️").
            timeout: Timeout for reaction API calls.

        Example:
            >>> @csp.graph
            ... def my_graph():
            ...     messages = adapter.subscribe()
            ...     emoji = csp.apply(messages, lambda m: "👋", str)
            ...     adapter.publish_reaction(messages, emoji)
        """
        self._add_reaction(msg=msg, emoji=emoji, timeout=timeout)


# Legacy alias for backwards compatibility
TelegramAdapterManager = TelegramAdapter
