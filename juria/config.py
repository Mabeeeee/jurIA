"""Configuration centrale pour le pipeline RAG."""

import os

# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VECTORSTORE_DIR = os.path.join(BASE_DIR, "data", "vectorstore")

# ---------------------------------------------------------------------------
# Modele d'embeddings
# ---------------------------------------------------------------------------
EMBEDDING_MODEL_NAME = "OrdalieTech/Solon-embeddings-large-0.1"
EMBEDDING_DIMENSIONS = 1024

# ---------------------------------------------------------------------------
# Parametres de recherche
# ---------------------------------------------------------------------------
DEFAULT_TOP_K = 5
SCORE_THRESHOLD = 0.3  # distance cosinus max (plus petit = plus similaire)

# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
CHUNK_SIZE = 1000       # caracteres
CHUNK_OVERLAP = 200     # caracteres

# ---------------------------------------------------------------------------
# Singleton lazy pour le modele d'embeddings
# ---------------------------------------------------------------------------
_embedding_model = None


def get_embedding_model():
    """Charge le modele Solon une seule fois (lazy loading, ~2 Go RAM).

    Essaie d'abord le cache local uniquement (local_files_only) pour eviter
    les allers-retours reseau vers Hugging Face Hub (verification d'etag,
    redirections 307...) une fois le modele deja telecharge. Si le cache
    est absent ou incomplet, on retombe sur le telechargement normal.
    """
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        try:
            _embedding_model = SentenceTransformer(
                EMBEDDING_MODEL_NAME, local_files_only=True
            )
        except Exception:
            _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedding_model
