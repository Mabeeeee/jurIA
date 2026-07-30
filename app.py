import chainlit as cl
from anthropic import AsyncAnthropic

from llama_index.core import Settings
from llama_index.core.callbacks import CallbackManager
from llama_index.llms.anthropic import Anthropic
import chainlit as cl

Settings.llm = Anthropic(model="claude-sonnet-5", api_key="...")

@cl.on_chat_start
async def start():
    Settings.callback_manager = CallbackManager([cl.LlamaIndexCallbackHandler()])
