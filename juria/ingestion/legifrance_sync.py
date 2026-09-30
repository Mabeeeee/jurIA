"""Synchronisation d'articles Legifrance dans ChromaDB."""

import logging
from datetime import date

from juria.config import get_embedding_model
from juria.rag.vector_store import get_vector_store

logger = logging.getLogger(__name__)


def synchroniser_article(
    article_id: str,
    texte: str,
    etat: str,
    meta: dict,
) -> str:
    """Synchronise un article Legifrance dans ChromaDB.

    Args:
        article_id: Identifiant LEGIARTI de l'article.
        texte: Texte integral de l'article.
        etat: Etat juridique (ex: "VIGUEUR", "ABROGE").
        meta: Dict avec au moins {code, num, url}.

    Returns:
        Statut: "retire", "ignore", "ajoute", "verifie" ou "mis_a_jour".
    """
    store = get_vector_store()
    doc_id = f"legi_{article_id}"
    today = date.today().isoformat()

    # --- Article non en vigueur ---
    if etat != "VIGUEUR":
        existant = store.collection.get(ids=[doc_id])
        if existant and existant["ids"]:
            store.collection.delete(ids=[doc_id])
            logger.info("Article %s retire (etat=%s)", article_id, etat)
            return "retire"
        return "ignore"

    # --- Article en vigueur : upsert ---
    existant = store.collection.get(ids=[doc_id], include=["documents", "metadatas"])
    ancien_texte = ""
    date_ajout = today
    if existant and existant["ids"]:
        ancien_texte = (existant["documents"] or [""])[0]
        ancien_meta = (existant["metadatas"] or [{}])[0]
        date_ajout = ancien_meta.get("date_ajout", today)

    embedding = get_embedding_model().encode(texte).tolist()

    metadatas = {
        "legi_id": article_id,
        "code": meta.get("code", ""),
        "num": meta.get("num", ""),
        "url": meta.get("url", ""),
        "etat": etat,
        "source_type": "legifrance",
        "source": "legifrance_fallback",
        "date_ajout": date_ajout,
        "date_verification": today,
    }

    store.upsert(
        ids=[doc_id],
        embeddings=[embedding],
        documents=[texte],
        metadatas=[metadatas],
    )

    if not ancien_texte:
        logger.info("Article %s ajoute dans ChromaDB", article_id)
        return "ajoute"
    if ancien_texte == texte:
        logger.info("Article %s verifie (inchange)", article_id)
        return "verifie"

    logger.info("Article %s mis a jour dans ChromaDB", article_id)
    return "mis_a_jour"
