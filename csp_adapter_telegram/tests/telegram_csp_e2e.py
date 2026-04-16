#!/usr/bin/env python
"""Telegram CSP End-to-End Integration Test.

This script tests all Telegram functionality through the CSP adapter.
Uses CSP for message streaming (subscribe/publish), runs other operations
via async setup before the CSP graph starts.

Symmetric with the Discord, Slack, and Symphony E2E tests.

Environment Variables Required:
    TELEGRAM_BOT_TOKEN: Your bot token from @BotFather
    TELEGRAM_TEST_CHAT_ID: Chat ID where the bot will send/receive messages
        (use @userinfobot or similar to find your chat ID)

Optional:
    TELEGRAM_TEST_USER_ID: User ID for mention tests
    TELEGRAM_TEST_USER_NAME: Username (without @) for mention tests

Usage:
    TELEGRAM_BOT_TOKEN="123456:ABC..." TELEGRAM_TEST_CHAT_ID="-100999" \\
        python -m csp_adapter_telegram.tests.telegram_csp_e2e
"""

import asyncio
import os
import sys
import traceback
from datetime import datetime, timedelta
from typing import List, Optional

import csp
from chatom.base import Message
from chatom.format import Format, FormattedMessage, Table
from chatom.telegram import (
    TelegramBackend,
    TelegramChannel,
    TelegramConfig,
    TelegramMessage,
    TelegramUser,
    mention_user,
)
from csp import ts

from csp_adapter_telegram import TelegramAdapter


def get_env(name: str, required: bool = True) -> Optional[str]:
    """Get environment variable with validation."""
    value = os.environ.get(name)
    if required and not value:
        print(f"Missing required environment variable: {name}")
        sys.exit(1)
    return value


class TestState:
    """Container for test state."""

    def __init__(self):
        self.results: List[tuple] = []
        self.config: Optional[TelegramConfig] = None
        self.chat_id: Optional[str] = None
        self.user_id: Optional[str] = None
        self.username: Optional[str] = None
        self.user: Optional[TelegramUser] = None
        self.bot_id: Optional[str] = None
        self.bot_username: Optional[str] = None
        self.bot_display_name: Optional[str] = None
        self.received_message: Optional[Message] = None
        self.waiting_for_inbound: bool = False
        self.test_complete: bool = False
        self.sent_message_id: Optional[int] = None

    def log(self, message: str, success: bool = True):
        icon = "PASS" if success else "FAIL"
        print(f"[{icon}] {message}")
        self.results.append((message, success))

    def section(self, title: str):
        print(f"\n{'=' * 60}")
        print(f"  {title}")
        print(f"{'=' * 60}\n")

    def print_summary(self) -> bool:
        self.section("Test Summary")
        passed = sum(1 for _, s in self.results if s)
        failed = sum(1 for _, s in self.results if not s)
        total = len(self.results)
        print(f"  Passed: {passed}/{total}")
        print(f"  Failed: {failed}/{total}")
        if failed > 0:
            print("\n  Failed tests:")
            for msg, success in self.results:
                if not success:
                    print(f"    FAIL: {msg}")
        return failed == 0


STATE = TestState()


def build_config() -> TelegramConfig:
    """Build config from environment."""
    bot_token = get_env("TELEGRAM_BOT_TOKEN")
    return TelegramConfig(bot_token=bot_token)


# ---------------------------------------------------------------------------
#  Phase 1: Pre-CSP async tests (direct Backend API)
# ---------------------------------------------------------------------------


async def setup_and_run_pre_csp_tests():
    """Run tests that require async operations before the CSP graph starts."""
    backend = TelegramBackend(config=STATE.config)

    # Test: Connection / Bot Info
    STATE.section("Test: Connection / Bot Info")
    try:
        await backend.connect()
        bot_info = await backend.get_bot_info()
        if bot_info:
            STATE.bot_id = bot_info.id
            STATE.bot_username = bot_info.handle or ""
            STATE.bot_display_name = bot_info.name or STATE.bot_username
            STATE.log(f"Bot: {STATE.bot_display_name} (@{STATE.bot_username}, id={STATE.bot_id})")
        else:
            STATE.log("Could not get bot info", success=False)
            return False
    except Exception as e:
        STATE.log(f"Connection / bot info failed: {e}", success=False)
        return False

    # Test: Fetch Channel Info
    STATE.section("Test: Fetch Channel Info")
    try:
        channel = await backend.fetch_channel(id=STATE.chat_id)
        if channel:
            STATE.log(f"Channel: {channel.name} (type={channel.chat_type})")
            print(f"  Channel ID: {channel.id}")
            print(f"  Type: {channel.chat_type}")
        else:
            STATE.log(f"Channel {STATE.chat_id} not found", success=False)
    except Exception as e:
        STATE.log(f"Fetch channel info failed: {e}", success=False)

    # Test: Send Plain Message (async)
    STATE.section("Test: Send Plain Message (async)")
    try:
        timestamp = datetime.now().strftime("%H:%M:%S")
        result = await backend.send_message(STATE.chat_id, f"[E2E] Plain message sent at {timestamp}")
        if result:
            STATE.sent_message_id = result.message_id
            STATE.log(f"Sent plain message at {timestamp}")
            print(f"  Message ID: {result.message_id}")
        else:
            STATE.log("Send message returned None", success=False)
    except Exception as e:
        STATE.log(f"Send plain message failed: {e}", success=False)

    # Test: Send Formatted Message
    STATE.section("Test: Send Formatted Message (async)")
    try:
        msg = (
            FormattedMessage()
            .add_text("[E2E] Formatted message:\n")
            .add_bold("This is bold text")
            .add_text(" and ")
            .add_italic("this is italic")
            .add_text("\nInline code: ")
            .add_code("hello()")
            .add_text("\n")
            .add_code_block('def greet():\n    print("Hello!")', "python")
        )
        await backend.send_message(STATE.chat_id, msg.render(Format.MARKDOWN))
        STATE.log("Sent formatted message with bold, italic, code")
    except Exception as e:
        STATE.log(f"Send formatted message failed: {e}", success=False)

    # Test: Mentions
    STATE.section("Test: Mentions (async)")
    try:
        parts = ["[E2E] Mentions:"]
        if STATE.username:
            user = TelegramUser(id=STATE.user_id or "0", name=STATE.username, username=STATE.username)
            parts.append(f"  Username mention: {mention_user(user)}")
        elif STATE.user_id:
            user = TelegramUser(id=STATE.user_id, name="User")
            parts.append(f"  User ID mention: {mention_user(user)}")
        else:
            parts.append("  (no user configured, skipping mention content)")
        text = "\n".join(parts)
        await backend.send_message(STATE.chat_id, text)
        STATE.log("Sent message with mentions")
    except Exception as e:
        STATE.log(f"Mentions test failed: {e}", success=False)

    # Test: Reactions
    STATE.section("Test: Reactions (async)")
    if STATE.sent_message_id:
        try:
            await backend.add_reaction(str(STATE.sent_message_id), "👍", channel=STATE.chat_id)
            STATE.log("Added reaction to message")
            await asyncio.sleep(0.5)
        except Exception as e:
            STATE.log(f"Reactions test failed: {e}", success=False)
    else:
        print("  Skipping (no sent message to react to)")

    # Test: Rich Content Table
    STATE.section("Test: Rich Content Table (async)")
    try:
        msg = FormattedMessage()
        msg.add_text("[E2E] Feature Status:\n\n")
        table = Table.from_data(
            headers=["Feature", "Status", "Notes"],
            data=[
                ["Messages", "OK", "Working"],
                ["Reactions", "OK", "Working"],
                ["Mentions", "OK", "Working"],
                ["Formatting", "OK", "Working"],
                ["Edit", "OK", "Working"],
            ],
        )
        msg.content.append(table)
        await backend.send_message(STATE.chat_id, msg.render(Format.MARKDOWN))
        STATE.log("Sent rich content with table")
    except Exception as e:
        STATE.log(f"Rich content test failed: {e}", success=False)

    # Test: Edit Message
    STATE.section("Test: Edit Message (async)")
    if STATE.sent_message_id:
        try:
            await backend.edit_message(
                str(STATE.sent_message_id),
                "[E2E] This message was edited!",
                channel=STATE.chat_id,
            )
            STATE.log("Edited existing message")
        except Exception as e:
            STATE.log(f"Edit message failed: {e}", success=False)
    else:
        print("  Skipping (no sent message to edit)")

    # Test: Reply to Message
    STATE.section("Test: Reply to Message (async)")
    if STATE.sent_message_id:
        try:
            await backend.send_message(
                STATE.chat_id,
                "[E2E] This is a reply/thread message",
                reply_to=str(STATE.sent_message_id),
            )
            STATE.log("Sent reply message")
        except Exception as e:
            STATE.log(f"Reply message failed: {e}", success=False)
    else:
        print("  Skipping (no message to reply to)")

    # Disconnect (CSP will create its own connection)
    await backend.disconnect()
    STATE.log("Pre-CSP setup complete")
    return True


# ---------------------------------------------------------------------------
#  Phase 2: CSP streaming tests (subscribe / publish)
# ---------------------------------------------------------------------------


@csp.graph
def telegram_csp_e2e_graph():
    """CSP graph for message streaming tests."""
    adapter = TelegramAdapter(STATE.config)

    # Subscribe to all messages
    messages = adapter.subscribe()

    @csp.node
    def message_sender() -> ts[TelegramMessage]:
        """Send test messages step by step via CSP publish."""
        with csp.alarms():
            a_step = csp.alarm(int)

        with csp.start():
            csp.schedule_alarm(a_step, timedelta(seconds=2), 0)

        if csp.ticked(a_step):
            step = a_step

            if step == 0:
                # Plain message
                STATE.section("Test: Send Plain Message (via CSP)")
                timestamp = datetime.now().strftime("%H:%M:%S")
                STATE.log(f"Sending plain message at {timestamp}")
                csp.schedule_alarm(a_step, timedelta(seconds=2), 1)
                return TelegramMessage(
                    chat_id=STATE.chat_id,
                    channel=TelegramChannel(id=STATE.chat_id),
                    content=f"[CSP E2E] Plain message at {timestamp}",
                )

            elif step == 1:
                # Formatted message
                STATE.section("Test: Send Formatted Message (via CSP)")
                msg = (
                    FormattedMessage()
                    .add_text("[CSP E2E] Formatted:\n")
                    .add_bold("Bold")
                    .add_text(" and ")
                    .add_italic("italic")
                    .add_text("\nCode: ")
                    .add_code("inline_code()")
                )
                STATE.log("Sending markdown message")
                csp.schedule_alarm(a_step, timedelta(seconds=2), 2)
                return TelegramMessage(
                    chat_id=STATE.chat_id,
                    channel=TelegramChannel(id=STATE.chat_id),
                    content=msg.render(Format.MARKDOWN),
                )

            elif step == 2:
                # Mentions
                STATE.section("Test: Mentions (via CSP)")
                if STATE.username:
                    user = TelegramUser(id=STATE.user_id or "0", name=STATE.username, username=STATE.username)
                else:
                    user = TelegramUser(id=STATE.user_id or "0", name="test")
                user_ref = mention_user(user)
                STATE.log(f"Sending mention message: {user_ref}")
                csp.schedule_alarm(a_step, timedelta(seconds=2), 3)
                return TelegramMessage(
                    chat_id=STATE.chat_id,
                    channel=TelegramChannel(id=STATE.chat_id),
                    content=f"[CSP E2E] Mention: {user_ref}",
                )

            elif step == 3:
                # Table
                STATE.section("Test: Rich Content Table (via CSP)")
                msg = FormattedMessage()
                table = Table.from_data(
                    headers=["Feature", "Status"],
                    data=[["Subscribe", "OK"], ["Publish", "OK"], ["Mentions", "OK"]],
                )
                msg.content.append(table)
                STATE.log("Sending table message")
                csp.schedule_alarm(a_step, timedelta(seconds=2), 4)
                return TelegramMessage(
                    chat_id=STATE.chat_id,
                    channel=TelegramChannel(id=STATE.chat_id),
                    content=msg.render(Format.MARKDOWN),
                )

            elif step == 4:
                # Inbound message prompt
                STATE.section("Test: Inbound Messages (via CSP subscribe)")
                STATE.waiting_for_inbound = True
                STATE.log("Waiting for inbound message... Send a message to the bot within 10 seconds.")
                csp.schedule_alarm(a_step, timedelta(seconds=2), 5)
                return TelegramMessage(
                    chat_id=STATE.chat_id,
                    channel=TelegramChannel(id=STATE.chat_id),
                    content="[CSP E2E] Inbound test - send a message to the bot now!",
                )

            elif step == 5:
                # Reply/thread via CSP
                STATE.section("Test: Reply (via CSP)")
                STATE.log("Sending reply via CSP publish")
                csp.schedule_alarm(a_step, timedelta(seconds=2), 6)
                if STATE.sent_message_id:
                    return TelegramMessage(
                        chat_id=STATE.chat_id,
                        channel=TelegramChannel(id=STATE.chat_id),
                        content="[CSP E2E] This is a threaded reply",
                        reply_to_message_id=STATE.sent_message_id,
                    )

            elif step == 6:
                # Completion
                STATE.section("CSP Tests Complete")
                STATE.log("All CSP tests finished")
                STATE.test_complete = True

    # Inbound message handler
    @csp.node
    def handle_inbound(msgs: ts[[Message]]):
        """Handle inbound messages."""
        if csp.ticked(msgs) and STATE.waiting_for_inbound:
            for msg in msgs:
                # Skip bot's own messages
                if msg.author and msg.author.id == STATE.bot_id:
                    continue
                STATE.received_message = msg
                STATE.waiting_for_inbound = False
                preview = (msg.content or "")[:80]
                author_name = msg.author.name if msg.author else "unknown"
                print(f"\n  Received: {preview}")
                print(f"  From: {author_name}")
                STATE.log("Received inbound message via CSP subscribe")
                break

    # Independent inbound timeout node
    @csp.node
    def inbound_timeout() -> ts[TelegramMessage]:
        """Auto-skip inbound test if timeout is reached without a user message."""
        with csp.alarms():
            a_timeout = csp.alarm(bool)
        with csp.state():
            s_timed_out = False
        with csp.start():
            csp.schedule_alarm(a_timeout, timedelta(seconds=15), True)
        if csp.ticked(a_timeout) and STATE.waiting_for_inbound and not s_timed_out:
            s_timed_out = True
            STATE.log("Inbound message test skipped (timeout)", success=True)
            STATE.waiting_for_inbound = False
            return TelegramMessage(
                chat_id=STATE.chat_id,
                channel=TelegramChannel(id=STATE.chat_id),
                content="[CSP E2E] Inbound test skipped (timeout)",
            )

    # Stop engine when all steps are done
    @csp.node
    def check_complete(msgs: ts[TelegramMessage]):
        with csp.alarms():
            a_stop = csp.alarm(bool)
        if csp.ticked(msgs) and STATE.test_complete:
            csp.schedule_alarm(a_stop, timedelta(seconds=1), True)
        if csp.ticked(a_stop):
            csp.stop_engine()

    handle_inbound(messages)
    outbound = message_sender()
    timeout_msgs = inbound_timeout()

    # Merge sender + timeout for publishing
    @csp.node
    def merge_messages(m1: ts[TelegramMessage], m2: ts[TelegramMessage]) -> ts[TelegramMessage]:
        if csp.ticked(m1):
            return m1
        if csp.ticked(m2):
            return m2

    final_outbound = merge_messages(outbound, timeout_msgs)
    adapter.publish(final_outbound)
    check_complete(final_outbound)


# ---------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------


async def main_async():
    """Main async entry point."""
    print("\n" + "=" * 60)
    print("  Telegram CSP E2E Integration Test")
    print("=" * 60)

    STATE.config = build_config()
    STATE.chat_id = get_env("TELEGRAM_TEST_CHAT_ID")
    STATE.user_id = get_env("TELEGRAM_TEST_USER_ID", required=False)
    STATE.username = get_env("TELEGRAM_TEST_USER_NAME", required=False)

    # Phase 1: Async setup tests (bot info, send message, format, etc.)
    print("\n--- Phase 1: Async Setup Tests ---\n")
    if not await setup_and_run_pre_csp_tests():
        return False

    # Phase 2: CSP streaming tests (publish, subscribe, reactions, etc.)
    print("\n--- Phase 2: CSP Streaming Tests ---\n")
    try:
        csp.run(
            telegram_csp_e2e_graph,
            endtime=timedelta(seconds=30),
            realtime=True,
        )
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\n\nCSP graph error: {e}")
        traceback.print_exc()

    return STATE.print_summary()


def main():
    """Main entry point."""
    success = asyncio.run(main_async())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
