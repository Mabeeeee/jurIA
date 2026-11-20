"""Tests du chargement du modele d'embeddings (juria/config.py)."""

import sys
import types

import pytest

from juria import config


@pytest.fixture
def faux_sentence_transformers(monkeypatch):
    """Remplace le paquet sentence_transformers par un module factice.

    Permet de tester le chargement sans telecharger ni charger Solon (~2 Go).
    `cache_present` controle si le chargement local_files_only=True reussit.
    """
    module = types.ModuleType("sentence_transformers")
    module.appels = []
    module.cache_present = True

    class FauxSentenceTransformer:
        def __init__(self, nom, local_files_only=False):
            module.appels.append({"nom": nom, "local_files_only": local_files_only})
            if local_files_only and not module.cache_present:
                raise OSError("modele absent du cache")

    module.SentenceTransformer = FauxSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    monkeypatch.setattr(config, "_embedding_model", None)
    return module


def test_charge_depuis_le_cache_local_en_priorite(faux_sentence_transformers):
    config.get_embedding_model()

    assert faux_sentence_transformers.appels == [
        {"nom": config.EMBEDDING_MODEL_NAME, "local_files_only": True},
    ]


def test_telecharge_si_cache_absent(faux_sentence_transformers):
    faux_sentence_transformers.cache_present = False

    modele = config.get_embedding_model()

    assert modele is not None
    assert [a["local_files_only"] for a in faux_sentence_transformers.appels] == [True, False]


def test_modele_charge_une_seule_fois(faux_sentence_transformers):
    premier = config.get_embedding_model()

    assert config.get_embedding_model() is premier
    assert len(faux_sentence_transformers.appels) == 1


def test_parametres_rag_coherents():
    assert 0 < config.SCORE_THRESHOLD < 2  # distance cosinus dans [0, 2]
    assert 0 <= config.CHUNK_OVERLAP < config.CHUNK_SIZE  # sinon boucle infinie au chunking
    assert config.DEFAULT_TOP_K > 0
    assert config.FRAICHEUR_JOURS > 0
