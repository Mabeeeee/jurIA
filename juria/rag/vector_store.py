"""Wrapper ChromaDB pour le stockage de vecteurs."""

import chromadb
from chromadb.config import Settings

from juria.config import VECTORSTORE_DIR

COLLECTION_NAME = "juria_documents"

_vector_store = None


class VectorStore:
    """Client persistant ChromaDB avec collection unique."""

    def __init__(self):
        self.client = chromadb.PersistentClient(
            path=VECTORSTORE_DIR,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def ajouter(self, ids: list[str], embeddings: list[list[float]],
                documents: list[str], metadatas: list[dict]):
        """Ajoute des chunks dans la collection."""
        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    def rechercher(self, query_embedding: list[float], top_k: int = 5,
                   filtre: dict | None = None) -> dict:
        """Recherche les chunks les plus proches."""
        kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if filtre:
            kwargs["where"] = filtre
        return self.collection.query(**kwargs)

    def supprimer_par_source(self, source: str):
        """Supprime tous les chunks provenant d'une source donnee."""
        self.collection.delete(where={"source": source})

    def compter(self) -> int:
        """Retourne le nombre total de chunks dans la collection."""
        return self.collection.count()


def get_vector_store() -> VectorStore:
    """Singleton pour le vector store."""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
