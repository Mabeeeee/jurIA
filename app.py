import os
from dotenv import load_dotenv
from anthropic import AsyncAnthropic
import chainlit as cl

load_dotenv()

client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = "claude-sonnet-5"

@cl.on_chat_start
async def start():
    # historique de la conversation stocké dans la session Chainlit
    cl.user_session.set("history", [])
    await cl.Message(content="Salut ! Je suis prêt, pose ta question.").send()


@cl.on_message
async def main(message: cl.Message):
    history = cl.user_session.get("history")
    history.append({"role": "user", "content": message.content})

    msg = cl.Message(content="")
    await msg.send()  # affiche le message vide tout de suite, puis on stream dedans

    full_response = ""
    async with client.messages.stream(
        model=MODEL,
        max_tokens=1024,
        messages=history,
    ) as stream:
        async for text in stream.text_stream:
            full_response += text
            await msg.stream_token(text)

    await msg.update()
    history.append({"role": "assistant", "content": full_response})
    cl.user_session.set("history", history)
