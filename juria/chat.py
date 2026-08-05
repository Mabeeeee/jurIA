import os

from anthropic import AsyncAnthropic
import chainlit as cl

from juria.prompts import SYSTEM_PROMPT

client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = "claude-sonnet-4-6"


async def stream_response(history: list[dict], msg: cl.Message) -> str:
    """Call Claude with streaming, updating the Chainlit message in real time.

    Returns the full response text.
    """
    full_response = ""
    async with client.messages.stream(
        model=MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=history,
    ) as stream:
        async for text in stream.text_stream:
            full_response += text
            await msg.stream_token(text)

    await msg.update()
    return full_response
