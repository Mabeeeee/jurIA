"""Tests de l'upload et de l'indexation des documents utilisateur (juria/user_docs.py)."""

import sqlite3
from types import SimpleNamespace

import fitz
import pytest

from juria import user_docs
from juria.rag.vector_store import get_user_vector_store


class FauxMessage:
    """Remplace cl.Message : memorise le contenu envoye puis mis a jour."""

    envoyes: list["FauxMessage"] = []

    def __init__(self, content=""):
        self.content = content
        self.historique = [content]
        FauxMessage.envoyes.append(self)

    async def send(self):
        return self

    async def update(self, content=None):
        self.content = content
        self.historique.append(content)


@pytest.fixture
def faux_cl(monkeypatch):
    FauxMessage.envoyes = []
    monkeypatch.setattr(user_docs, "cl", SimpleNamespace(Message=FauxMessage))
    return FauxMessage


def _element(name, mime, path=None, content=None):
    """Imite un element Chainlit (fichier uploade)."""
    return SimpleNamespace(name=name, mime=mime, path=path, content=content)


def _documents_en_base(db_path):
    conn = sqlite3.connect(db_path)
    lignes = conn.execute(
        "SELECT user_id, filename, mime_type, stored_path FROM user_documents"
    ).fetchall()
    conn.close()
    return lignes


def _pdf(chemin, *lignes):
    doc = fitz.open()
    page = doc.new_page()
    for i, texte in enumerate(lignes):
        page.insert_text((72, 72 + 20 * i), texte, fontsize=11)
    doc.save(str(chemin))
    doc.close()
    return str(chemin)


# ---------------------------------------------------------------------------
# _generer_id
# ---------------------------------------------------------------------------

def test_generer_id_deterministe_et_unique():
    assert user_docs._generer_id("cours.pdf", 0) == user_docs._generer_id("cours.pdf", 0)
    assert user_docs._generer_id("cours.pdf", 0) != user_docs._generer_id("cours.pdf", 1)
    assert user_docs._generer_id("cours.pdf", 3).startswith("cours.pdf_3_")


# ---------------------------------------------------------------------------
# handle_upload
# ---------------------------------------------------------------------------

class TestHandleUpload:

    async def test_type_non_supporte_refuse(self, db_tmp):
        el = _element("photo.png", "image/png", content=b"...")

        (message,) = await user_docs.handle_upload([el], "alice")

        assert "type non supporte" in message
        assert _documents_en_base(db_tmp) == []

    async def test_fichier_texte_stocke_sans_indexation(self, db_tmp, tmp_path):
        el = _element("notes.txt", "text/plain", content="Mes notes de cours")

        (message,) = await user_docs.handle_upload([el], "alice")

        assert "stockage seul" in message
        copie = tmp_path / "data" / "user_docs" / "alice" / "notes.txt"
        assert copie.read_text() == "Mes notes de cours"
        assert _documents_en_base(db_tmp) == [("alice", "notes.txt", "text/plain", str(copie))]

    async def test_fichier_copie_depuis_un_chemin(self, db_tmp, tmp_path):
        source = tmp_path / "upload.md"
        source.write_bytes(b"# Titre")

        await user_docs.handle_upload([_element("cours.md", "text/markdown", path=str(source))], "bob")

        assert (tmp_path / "data" / "user_docs" / "bob" / "cours.md").read_bytes() == b"# Titre"

    async def test_fichier_vide_ignore(self, db_tmp):
        (message,) = await user_docs.handle_upload([_element("vide.txt", "text/plain")], "alice")

        assert "fichier vide" in message
        assert _documents_en_base(db_tmp) == []

    async def test_pdf_envoye_a_l_indexation(self, db_tmp, monkeypatch):
        appels = []

        async def faux_indexer(chemin, filename, user_id):
            appels.append((filename, user_id))
            return "indexe"

        monkeypatch.setattr(user_docs, "_indexer_pdf", faux_indexer)

        messages = await user_docs.handle_upload(
            [_element("td.pdf", "application/pdf", content=b"%PDF")], "alice")

        assert messages == ["indexe"]
        assert appels == [("td.pdf", "alice")]

    async def test_un_message_par_fichier(self, db_tmp):
        elements = [
            _element("a.txt", "text/plain", content="a"),
            _element("b.exe", "application/octet-stream", content=b"b"),
        ]

        messages = await user_docs.handle_upload(elements, "alice")

        assert len(messages) == 2
        assert len(_documents_en_base(db_tmp)) == 1


# ---------------------------------------------------------------------------
# _indexer_pdf (vrai PDF + vraie ChromaDB temporaire + faux embeddings)
# ---------------------------------------------------------------------------

@pytest.mark.chroma
class TestIndexerPdf:

    async def test_pdf_indexe_dans_la_collection_utilisateur(
            self, tmp_path, faux_cl, faux_modele, chroma_tmp):
        chemin = _pdf(tmp_path / "td.pdf", "Le contrat est un accord de volontes.")

        message = await user_docs._indexer_pdf(chemin, "td.pdf", "alice")

        assert "indexe (1 passages extraits)" in message
        store = get_user_vector_store("alice")
        assert store.compter() == 1
        assert store.collection.get()["metadatas"][0]["source"] == "td.pdf"
        # Le message de progression a ete mis a jour avec la confirmation
        assert faux_cl.envoyes[0].historique == ["**td.pdf** : Indexation en cours...", message]

    async def test_reindexation_remplace_les_anciens_passages(
            self, tmp_path, faux_cl, faux_modele, chroma_tmp):
        chemin = _pdf(tmp_path / "td.pdf", "Version 1")
        await user_docs._indexer_pdf(chemin, "td.pdf", "alice")

        chemin = _pdf(tmp_path / "td.pdf", "Version 2")
        await user_docs._indexer_pdf(chemin, "td.pdf", "alice")

        assert get_user_vector_store("alice").collection.get()["documents"] == ["Version 2"]

    async def test_pdf_sans_texte(self, tmp_path, faux_cl, faux_modele, chroma_tmp):
        chemin = _pdf(tmp_path / "scan.pdf")

        message = await user_docs._indexer_pdf(chemin, "scan.pdf", "alice")

        assert "sans texte extractible" in message

    async def test_erreur_rapportee_sans_lever_d_exception(self, tmp_path, faux_cl, faux_modele):
        message = await user_docs._indexer_pdf(str(tmp_path / "absent.pdf"), "absent.pdf", "alice")

        assert "erreur lors de l'indexation" in message
        assert faux_cl.envoyes[0].content == message
