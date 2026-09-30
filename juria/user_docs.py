import hashlib
import os
import shutil
import sqlite3
from datetime import datetime

import chainlit as cl
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

        # Indexation automatique des PDF
        if mime == "application/pdf":
            confirmations.append(await _indexer_pdf(dest, el.name, user_id))
        else:
            confirmations.append(
                f"**{el.name}** enregistre (stockage seul, pas d'indexation pour ce format)."
            )

    return confirmations


def _generer_id(source: str, index: int) -> str:
    """Genere un ID deterministe pour un chunk."""
    h = hashlib.md5(f"{source}:{index}".encode()).hexdigest()[:12]
    return f"{source}_{index}_{h}"


async def _indexer_pdf(chemin_pdf: str, filename: str, user_id: str) -> str:
    """Chunke, encode et indexe un PDF dans la collection ChromaDB de l'utilisateur."""
    from juria.ingestion.chunking import chunker_document
    from juria.config import get_embedding_model
    from juria.rag.vector_store import get_user_vector_store

    progress_msg = cl.Message(content=f"**{filename}** : Indexation en cours...")
    await progress_msg.send()

    try:
        # 1. Chunking
        chunks = chunker_document(chemin_pdf, source=filename)
        if not chunks:
            await progress_msg.update(
                content=f"**{filename}** enregistre, mais aucun texte extractible pour l'indexation."
            )
            return f"**{filename}** enregistre (PDF sans texte extractible)."

        # 2. Encodage
        modele = get_embedding_model()
        textes = [c.texte for c in chunks]
        embeddings = modele.encode(textes, show_progress_bar=False, batch_size=32)
        embeddings = [e.tolist() for e in embeddings]

        # 3. Insertion dans ChromaDB
        store = get_user_vector_store(user_id)

        # Supprimer les anciens chunks du meme fichier (idempotence)
        try:
            store.supprimer_par_source(filename)
        except Exception:
            pass

        ids = [_generer_id(filename, i) for i in range(len(chunks))]
        metadatas = [c.metadata for c in chunks]

        batch_size = 500
        for i in range(0, len(ids), batch_size):
            store.ajouter(
                ids=ids[i:i + batch_size],
                embeddings=embeddings[i:i + batch_size],
                documents=textes[i:i + batch_size],
                metadatas=metadatas[i:i + batch_size],
            )

        confirmation = (
            f"**{filename}** enregistre et indexe "
            f"({len(chunks)} passages extraits). "
            f"Tu peux maintenant me poser des questions sur ce document."
        )
        await progress_msg.update(content=confirmation)
        return confirmation

    except Exception as e:
        err = f"**{filename}** enregistre, mais erreur lors de l'indexation : {e}"
        await progress_msg.update(content=err)
        return err
