"""Tests du wrapper ChromaDB (juria/rag/vector_store.py).

Ces tests utilisent une vraie base ChromaDB, creee dans un dossier temporaire
par la fixture `chroma_tmp` (voir conftest.py).
"""

import pytest

from juria.rag.vector_store import (
    COLLECTION_NAME,
    UserVectorStore,
    VectorStore,
    get_user_vector_store,
    get_vector_store,
    nom_collection_utilisateur,
)

pytestmark = pytest.mark.chroma


def _remplir(store):
    store.ajouter(
        ids=["c1", "c2", "c3"],
        embeddings=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.9, 0.1, 0.0]],
        documents=["civil 1", "fiscal", "civil 2"],
        metadatas=[
            {"source": "civil.pdf", "domaine": "civil"},
            {"source": "fiscal.pdf", "domaine": "procedure_fiscale"},
            {"source": "civil.pdf", "domaine": "civil"},
        ],
    )


class TestVectorStore:

    def test_collection_creee_en_cosinus(self, chroma_tmp):
        store = VectorStore()

        assert store.collection.name == COLLECTION_NAME
        assert store.collection.metadata["hnsw:space"] == "cosine"
        assert store.compter() == 0
        assert chroma_tmp.exists()  # persistance dans le dossier temporaire

    def test_ajouter_puis_rechercher_trie_par_distance(self, chroma_tmp):
        store = VectorStore()
        _remplir(store)

        res = store.rechercher([1.0, 0.0, 0.0], top_k=2)

        assert res["ids"] == [["c1", "c3"]]
        assert res["documents"] == [["civil 1", "civil 2"]]
        assert res["distances"][0][0] == pytest.approx(0.0, abs=1e-6)
        assert res["metadatas"][0][0]["source"] == "civil.pdf"

    def test_rechercher_avec_filtre(self, chroma_tmp):
        store = VectorStore()
        _remplir(store)

        res = store.rechercher([1.0, 0.0, 0.0], filtre={"domaine": "procedure_fiscale"})

        assert res["ids"] == [["c2"]]

    def test_upsert_remplace_un_document_existant(self, chroma_tmp):
        store = VectorStore()
        _remplir(store)

        store.upsert(ids=["c2"], embeddings=[[0.0, 1.0, 0.0]],
                     documents=["fiscal v2"], metadatas=[{"source": "fiscal.pdf"}])

        assert store.compter() == 3
        assert store.collection.get(ids=["c2"])["documents"] == ["fiscal v2"]

    def test_supprimer_par_source(self, chroma_tmp):
        store = VectorStore()
        _remplir(store)

        store.supprimer_par_source("civil.pdf")

        assert store.compter() == 1
        assert store.collection.get()["ids"] == ["c2"]

    def test_get_vector_store_est_un_singleton(self, chroma_tmp):
        assert get_vector_store() is get_vector_store()


class TestUserVectorStore:

    def test_collection_dediee_par_utilisateur(self, chroma_tmp):
        alice = UserVectorStore("alice")
        bob = UserVectorStore("bob")
        alice.ajouter(ids=["a"], embeddings=[[1.0, 0.0]], documents=["cours"],
                      metadatas=[{"source": "td.pdf"}])

        assert alice.collection.name == "store_quizz_alice"
        assert alice.compter() == 1
        assert bob.compter() == 0  # isolation entre utilisateurs

    def test_rechercher_et_supprimer(self, chroma_tmp):
        store = UserVectorStore("alice")
        store.ajouter(ids=["a", "b"], embeddings=[[1.0, 0.0], [0.0, 1.0]],
                      documents=["td1", "td2"],
                      metadatas=[{"source": "td1.pdf"}, {"source": "td2.pdf"}])

        assert store.rechercher([1.0, 0.0], top_k=1)["documents"] == [["td1"]]
        assert store.rechercher([1.0, 0.0], filtre={"source": "td2.pdf"})["ids"] == [["b"]]

        store.supprimer_par_source("td1.pdf")
        assert store.compter() == 1

    def test_cache_par_username(self, chroma_tmp):
        assert get_user_vector_store("alice") is get_user_vector_store("alice")
        assert get_user_vector_store("alice") is not get_user_vector_store("bob")

    @pytest.mark.parametrize("username", ["marie@exemple.fr", "abc-", "../x", "é"])
    def test_username_invalide_refuse(self, chroma_tmp, username):
        # ChromaDB n'accepte que [a-zA-Z0-9._-] : on refuse avant de l'appeler
        with pytest.raises(ValueError, match="Identifiant invalide"):
            UserVectorStore(username)

    def test_nom_collection_utilisateur(self):
        assert nom_collection_utilisateur("marie_dupont-2") == "store_quizz_marie_dupont-2"
