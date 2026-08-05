import os
import sqlite3

from dotenv import load_dotenv
import chainlit as cl
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer

from juria.auth import is_dev_mode, get_user_db, verify_password
from juria.chat import stream_response
from juria.user_docs import handle_upload

load_dotenv()

# ---------------------------------------------------------------------------
# Data layer – SQLite persistence for threads, messages, elements
# ---------------------------------------------------------------------------

_DB_PATH = "data/juria_app.db"


def _init_db():
    """Create the tables expected by Chainlit's SQLAlchemyDataLayer if they
    don't exist yet."""
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            "id"         TEXT PRIMARY KEY,
            "identifier" TEXT UNIQUE,
            "createdAt"  TEXT,
            "metadata"   TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS threads (
            "id"         TEXT PRIMARY KEY,
            "createdAt"  TEXT,
            "name"       TEXT,
            "userId"     TEXT,
            "userIdentifier" TEXT,
            "tags"       TEXT,
            "metadata"   TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS steps (
            "id"              TEXT PRIMARY KEY,
            "threadId"        TEXT,
            "parentId"        TEXT,
            "name"            TEXT,
            "type"            TEXT,
            "streaming"       BOOLEAN,
            "waitForAnswer"   BOOLEAN,
            "isError"         BOOLEAN,
            "input"           TEXT,
            "output"          TEXT,
            "createdAt"       TEXT,
            "start"           TEXT,
            "end"             TEXT,
            "showInput"       TEXT,
            "defaultOpen"     BOOLEAN,
            "autoCollapse"    BOOLEAN,
            "metadata"        TEXT DEFAULT '{}',
            "generation"      TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS elements (
            "id"        TEXT PRIMARY KEY,
            "threadId"  TEXT,
            "type"      TEXT,
            "chainlitKey" TEXT,
            "url"       TEXT,
            "objectKey" TEXT,
            "name"      TEXT,
            "display"   TEXT,
            "size"      TEXT,
            "language"  TEXT,
            "page"      TEXT,
            "forId"     TEXT,
            "mime"      TEXT
        );

        CREATE TABLE IF NOT EXISTS feedbacks (
            "id"       TEXT PRIMARY KEY,
            "forId"    TEXT,
            "threadId" TEXT,
            "value"    INTEGER,
            "comment"  TEXT
        );
    """)
    conn.close()


_init_db()


@cl.data_layer
def get_data_layer():
    return SQLAlchemyDataLayer(
        conninfo=f"sqlite+aiosqlite:///{_DB_PATH}",
    )

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

if not is_dev_mode():

    @cl.password_auth_callback
    async def auth_callback(username: str, password: str):
        user = get_user_db(username)
        if user is None:
            return None
        if not verify_password(password, user["password_hash"]):
            return None
        return cl.User(
            identifier=user["username"],
            metadata={"role": "user", "display_name": user["display_name"]},
        )

# ---------------------------------------------------------------------------
# Starters
# ---------------------------------------------------------------------------

@cl.set_starters
async def set_starters():
    return [
        cl.Starter(
            label="Responsabilite contractuelle",
            message="Quels articles du Code civil traitent de la responsabilite contractuelle ?",
            icon="/public/idea.svg",
        ),
        cl.Starter(
            label="Dol et erreur",
            message="Explique-moi la difference entre dol et erreur en droit des contrats.",
            icon="/public/idea.svg",
        ),
        cl.Starter(
            label="Prescription penale",
            message="Quels sont les delais de prescription en matiere penale ?",
            icon="/public/idea.svg",
        ),
    ]

# ---------------------------------------------------------------------------
# Chat start
# ---------------------------------------------------------------------------

@cl.on_chat_start
async def start():
    cl.user_session.set("history", [])

# ---------------------------------------------------------------------------
# Chat resume (from sidebar history)
# ---------------------------------------------------------------------------

@cl.on_chat_resume
async def on_chat_resume(thread):
    history = []
    for step in thread.get("steps", []):
        step_type = step.get("type")
        output = step.get("output", "")
        if not output:
            continue
        if step_type == "user_message":
            history.append({"role": "user", "content": output})
        elif step_type == "assistant_message":
            history.append({"role": "assistant", "content": output})
    cl.user_session.set("history", history)

# ---------------------------------------------------------------------------
# Message handler
# ---------------------------------------------------------------------------

@cl.on_message
async def main(message: cl.Message):
    # Handle file uploads
    if message.elements:
        user = cl.user_session.get("user")
        user_id = user.identifier if user else "anonymous"
        confirmations = await handle_upload(message.elements, user_id)
        if confirmations:
            await cl.Message(content="\n".join(confirmations)).send()
        # If the message only contains files with no text, stop here
        if not message.content.strip():
            return

    history = cl.user_session.get("history")
    history.append({"role": "user", "content": message.content})

    msg = cl.Message(content="")
    await msg.send()

    full_response = await stream_response(history, msg)

    history.append({"role": "assistant", "content": full_response})
    cl.user_session.set("history", history)
