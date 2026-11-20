"""Fixtures partagees par tous les tests.

pytest charge ce fichier automatiquement : toute fonction decoree par
@pytest.fixture ici est injectable dans n'importe quel test du dossier,
simplement en la nommant comme parametre du test.
"""

import hashlib

import pytest

from juria import config
from juria.rag import vector_store
from juria.rag.query_engine import ResultatRecherche


# ---------------------------------------------------------------------------
# Faux modele d'embeddings
# ---------------------------------------------------------------------------

class _Vecteur(list):
    """Liste qui imite un numpy array : expose .tolist()."""

    def tolist(self):
        return list(self)


class FauxModeleEmbeddings:
    """Remplace Solon (~2 Go) par un encodeur deterministe et instantane.

    - `vecteurs` permet d'imposer le vecteur d'un texte precis (pour controler
      les distances cosinus dans les tests de recherche) ;
    - sinon le vecteur est derive d'un hash du texte (stable d'un run a l'autre).
    Chaque appel est enregistre dans `appels` pour pouvoir verifier ce qui a
    ete encode.
    """

    def __init__(self, dimensions: int = 8):
        self.dimensions = dimensions
        self.vecteurs: dict[str, list[float]] = {}
        self.appels: list = []

    def _encoder_un(self, texte: str) -> _Vecteur:
        if texte in self.vecteurs:
            return _Vecteur(self.vecteurs[texte])
        h = hashlib.sha256(texte.encode()).digest()
        return _Vecteur(b / 255 + 0.01 for b in h[: self.dimensions])

    def encode(self, textes, **kwargs):
        self.appels.append(textes)
        if isinstance(textes, str):
            return self._encoder_un(textes)
        return [self._encoder_un(t) for t in textes]


@pytest.fixture
def faux_modele(monkeypatch):
    """Injecte le faux modele dans le singleton de juria.config."""
    modele = FauxModeleEmbeddings()
    monkeypatch.setattr(config, "_embedding_model", modele)
    return modele


# ---------------------------------------------------------------------------
# ChromaDB isole dans un dossier temporaire
# ---------------------------------------------------------------------------

@pytest.fixture
def chroma_tmp(tmp_path, monkeypatch):
    """Redirige ChromaDB vers un dossier temporaire et vide les singletons.

    La vraie base data/vectorstore n'est jamais touchee. Retourne le chemin
    du dossier utilise.
    """
    dossier = tmp_path / "vectorstore"
    monkeypatch.setattr(vector_store, "VECTORSTORE_DIR", str(dossier))
    monkeypatch.setattr(vector_store, "_vector_store", None)
    monkeypatch.setattr(vector_store, "_user_stores", {})
    return dossier


# ---------------------------------------------------------------------------
# Base SQLite isolee
# ---------------------------------------------------------------------------

@pytest.fixture
def db_tmp(tmp_path, monkeypatch):
    """Redirige les modules qui ecrivent dans data/juria_app.db vers tmp_path."""
    from juria import auth, user_docs

    chemin = str(tmp_path / "data" / "juria_app.db")
    monkeypatch.setattr(auth, "DB_PATH", chemin)
    monkeypatch.setattr(user_docs, "DB_PATH", chemin)
    monkeypatch.setattr(user_docs, "DOCS_DIR", str(tmp_path / "data" / "user_docs"))
    return chemin


# ---------------------------------------------------------------------------
# Fabriques de donnees
# ---------------------------------------------------------------------------

@pytest.fixture
def resultat():
    """Fabrique de ResultatRecherche : resultat(texte, score, **metadata)."""

    def _fabriquer(texte="Texte", score=0.1, **metadata):
        return ResultatRecherche(texte=texte, score=score, metadata=metadata)

    return _fabriquer
