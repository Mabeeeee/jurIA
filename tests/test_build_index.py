"""Tests du script d'indexation de PDF (juria/ingestion/build_index.py)."""

import fitz
import pytest

from juria.ingestion import build_index
from juria.rag.vector_store import get_vector_store


def _pdf(chemin, *lignes):
    doc = fitz.open()
    page = doc.new_page()
    for i, texte in enumerate(lignes):
        page.insert_text((72, 72 + 20 * i), texte, fontsize=11)
    doc.save(str(chemin))
    doc.close()
    return str(chemin)


def test_generer_id_identique_a_user_docs():
    from juria.user_docs import _generer_id as generer_id_user_docs

    assert build_index._generer_id("code.pdf", 4) == generer_id_user_docs("code.pdf", 4)


@pytest.mark.chroma
class TestIngererPdf:

    def test_indexe_les_chunks_avec_le_domaine(self, tmp_path, faux_modele, chroma_tmp, capsys):
        chemin = _pdf(tmp_path / "lpf.pdf", "Le droit de reprise de l'administration.")

        build_index.ingerer_pdf(chemin, "procedure_fiscale")

        store = get_vector_store()
        assert store.compter() == 1
        meta = store.collection.get()["metadatas"][0]
        assert meta["source"] == "lpf.pdf"
        assert meta["domaine"] == "procedure_fiscale"
        assert "Ingestion terminee. 1 chunks" in capsys.readouterr().out

    def test_reingestion_idempotente(self, tmp_path, faux_modele, chroma_tmp):
        chemin = _pdf(tmp_path / "lpf.pdf", "Texte")

        build_index.ingerer_pdf(chemin, "procedure_fiscale")
        build_index.ingerer_pdf(chemin, "procedure_fiscale")

        assert get_vector_store().compter() == 1

    def test_pdf_sans_texte_arrete_le_script(self, tmp_path, faux_modele, chroma_tmp):
        chemin = _pdf(tmp_path / "vide.pdf")

        with pytest.raises(SystemExit) as exc:
            build_index.ingerer_pdf(chemin, "x")

        assert exc.value.code == 1


class TestMain:

    def test_fichier_introuvable(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["build_index", "--pdf", "absent.pdf", "--domaine", "x"])

        with pytest.raises(SystemExit) as exc:
            build_index.main()

        assert exc.value.code == 1
        assert "Fichier introuvable" in capsys.readouterr().out

    def test_arguments_obligatoires(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["build_index", "--pdf", "a.pdf"])

        with pytest.raises(SystemExit) as exc:
            build_index.main()

        assert exc.value.code == 2  # code standard d'argparse

    def test_transmet_les_arguments(self, monkeypatch, tmp_path):
        chemin = _pdf(tmp_path / "a.pdf", "x")
        appels = []
        monkeypatch.setattr(build_index, "ingerer_pdf", lambda pdf, domaine: appels.append((pdf, domaine)))
        monkeypatch.setattr("sys.argv", ["build_index", "--pdf", chemin, "--domaine", "civil"])

        build_index.main()

        assert appels == [(chemin, "civil")]
