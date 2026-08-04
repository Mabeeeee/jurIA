import os
import shutil
import sqlite3
from datetime import datetime

from chainlit.element import Element

DB_PATH = os.path.join("data", "juria_app.db")
DOCS_DIR = os.path.join("data", "user_docs")

SUPPORTED_MIME = {
    "application/pdf",
    "text/plain",
    "text/markdown",
}


def _ensure_docs_table():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            mime_type TEXT,
            stored_path TEXT NOT NULL,
            uploaded_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


async def handle_upload(elements: list[Element], user_id: str) -> list[str]:
    """Process uploaded file elements. Store files and record metadata.

    Returns a list of confirmation messages (one per file).
    """
    _ensure_docs_table()
    confirmations: list[str] = []

    user_dir = os.path.join(DOCS_DIR, user_id)
    os.makedirs(user_dir, exist_ok=True)

    for el in elements:
        mime = getattr(el, "mime", None) or ""
        if mime not in SUPPORTED_MIME:
            confirmations.append(
                f"**{el.name}** : type non supporte (`{mime}`). "
                f"Formats acceptes : PDF, TXT, MD."
            )
            continue

        # Copy file to user storage
        dest = os.path.join(user_dir, el.name)
        if el.path:
            shutil.copy2(el.path, dest)
        elif el.content:
            with open(dest, "wb") as f:
                f.write(el.content if isinstance(el.content, bytes) else el.content.encode())
        else:
            confirmations.append(f"**{el.name}** : fichier vide, ignore.")
            continue

        # Record metadata in SQLite
        now = datetime.utcnow().isoformat()
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO user_documents (user_id, filename, mime_type, stored_path, uploaded_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, el.name, mime, dest, now),
        )
        conn.commit()
        conn.close()

        confirmations.append(
            f"**{el.name}** enregistre. "
            f"L'indexation pour la recherche sera disponible prochainement."
        )

    return confirmations
