import os

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
import chainlit as cl

from juria.auth import is_dev_mode
from juria.prompts import SYSTEM_PROMPT

# ---------------------------------------------------------------------------
# Client & model selection based on environment
# ---------------------------------------------------------------------------

if is_dev_mode():
    _ollama_client = AsyncOpenAI(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        api_key="ollama",  # Ollama doesn't need a real key but the SDK requires one
    )
    _ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
else:
    _anthropic_client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    _anthropic_model = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Streaming helpers
# ---------------------------------------------------------------------------

async def _stream_ollama(history: list[dict], msg: cl.Message) -> str:
    full_response = ""
    stream = await _ollama_client.chat.completions.create(
        model=_ollama_model,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
        max_tokens=2048,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            full_response += delta
            await msg.stream_token(delta)

    await msg.update()
    return full_response


async def _stream_anthropic(history: list[dict], msg: cl.Message) -> str:
    full_response = ""
    async with _anthropic_client.messages.stream(
        model=_anthropic_model,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=history,
    ) as stream:
        async for text in stream.text_stream:
            full_response += text
            await msg.stream_token(text)

    await msg.update()
    return full_response


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def stream_response(history: list[dict], msg: cl.Message) -> str:
    """Call the LLM with streaming, updating the Chainlit message in real time."""
    if is_dev_mode():
        return await _stream_ollama(history, msg)
    return await _stream_anthropic(history, msg)
