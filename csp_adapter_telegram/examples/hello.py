import csp
from csp import ts

from csp_adapter_telegram import TelegramAdapter, TelegramConfig, TelegramMessage

config = TelegramConfig(bot_token="123456:ABCDefGhIjKlMnOpQrStUvWxYz")


@csp.node
def reply_hello(msg: ts[TelegramMessage]) -> ts[TelegramMessage]:
    """Reply to every message that starts with hello."""
    if msg.content.lower().startswith("hello"):
        return TelegramMessage(
            chat_id=msg.chat_id,
            content=f"Hello {msg.author.name}!",
        )


def graph():
    # Create a Telegram Adapter object
    adapter = TelegramAdapter(config)

    # Subscribe and unroll the messages
    msgs = csp.unroll(adapter.subscribe())

    # Print it out locally for debugging
    csp.print("msgs", msgs)

    # Add the reply node
    responses = reply_hello(msgs)

    # Print it out locally for debugging
    csp.print("responses", responses)

    # Publish the responses
    adapter.publish(responses)


if __name__ == "__main__":
    csp.run(graph, realtime=True)
