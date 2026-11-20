"""Tests du decoupage des PDF juridiques (juria/ingestion/chunking.py)."""

import fitz
import pytest

from juria.ingestion import chunking
from juria.ingestion.chunking import (
    Chunk,
    _chunker_par_taille,
    _chunker_structurel,
    _creer_chunk,
    chunker_document,
    detecter_structure,
    extraire_texte_pdf,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _page(num, *blocs):
    """Construit une page au format de extraire_texte_pdf : blocs = (texte, taille)."""
    return {"page": num, "blocs": [{"texte": t, "taille_police": s} for t, s in blocs]}


def _ecrire_pdf(chemin, pages):
    """Cree un vrai PDF : pages = liste de listes de (texte, taille_police)."""
    doc = fitz.open()
    for lignes in pages:
        page = doc.new_page()
        y = 72
        for texte, taille in lignes:
            page.insert_text((72, y), texte, fontsize=taille)
            y += taille * 1.8
    doc.save(str(chemin))
    doc.close()
    return str(chemin)


@pytest.fixture
def petits_chunks(monkeypatch):
    """Reduit la taille des chunks pour des tests lisibles (10 car., overlap 3)."""
    monkeypatch.setattr(chunking, "CHUNK_SIZE", 10)
    monkeypatch.setattr(chunking, "CHUNK_OVERLAP", 3)


# ---------------------------------------------------------------------------
# extraire_texte_pdf
# ---------------------------------------------------------------------------

class TestExtraireTextePdf:

    def test_extrait_texte_et_taille_de_police_par_page(self, tmp_path):
        chemin = _ecrire_pdf(tmp_path / "doc.pdf", [
            [("Chapitre 1", 18), ("Du texte courant", 11)],
            [("Page deux", 11)],
        ])

        pages = extraire_texte_pdf(chemin)

        assert [p["page"] for p in pages] == [1, 2]
        assert pages[0]["blocs"] == [
            {"texte": "Chapitre 1", "taille_police": 18.0},
            {"texte": "Du texte courant", "taille_police": 11.0},
        ]
        assert pages[1]["blocs"][0]["texte"] == "Page deux"

    def test_ignore_les_pages_vides(self, tmp_path):
        chemin = _ecrire_pdf(tmp_path / "doc.pdf", [[], [("Seule page remplie", 11)]])

        pages = extraire_texte_pdf(chemin)

        assert len(pages) == 1
        assert pages[0]["page"] == 2  # la numerotation reste celle du PDF


# ---------------------------------------------------------------------------
# detecter_structure
# ---------------------------------------------------------------------------

class TestDetecterStructure:

    def test_liste_vide(self):
        assert detecter_structure([]) == []

    def test_pages_sans_blocs_renvoyees_telles_quelles(self):
        pages = [{"page": 1, "blocs": []}]
        assert detecter_structure(pages) == pages

    @pytest.mark.parametrize("texte, niveau_attendu", [
        ("Première partie : les obligations", "partie"),
        ("DEUXIEME PARTIE", "partie"),
        ("Titre II - Des contrats", "titre"),
        ("Chapitre 3 La formation", "chapitre"),
        ("Section 1 : Le consentement", "section"),
        ("Article 1128", "article"),
    ])
    def test_titre_en_gros_caracteres_reconnu(self, texte, niveau_attendu):
        # mediane = 10 ; 14 > 10 * 1.15 -> candidat titre
        pages = [_page(1, (texte, 14), ("corps", 10), ("corps", 10))]

        bloc = detecter_structure(pages)[0]["blocs"][0]

        assert bloc["niveau"] == niveau_attendu
        assert bloc["valeur"] == texte

    def test_tres_gros_texte_sans_motif_devient_titre_generique(self):
        pages = [_page(1, ("Introduction generale", 15), ("corps", 10), ("corps", 10))]

        bloc = detecter_structure(pages)[0]["blocs"][0]

        assert bloc["niveau"] == "titre_generique"

    def test_texte_moyennement_grand_sans_motif_ignore(self):
        # 12 > 11.5 (1.15x) mais < 14 (1.4x) : ni motif, ni titre generique
        pages = [_page(1, ("Remarque", 12), ("corps", 10), ("corps", 10))]

        bloc = detecter_structure(pages)[0]["blocs"][0]

        assert "niveau" not in bloc

    def test_article_detecte_meme_en_taille_normale(self):
        pages = [_page(1, ("Article L. 10", 10), ("corps", 10))]

        assert detecter_structure(pages)[0]["blocs"][0]["niveau"] == "article"

    def test_chapitre_en_taille_normale_non_detecte(self):
        # Hors article, un titre doit etre plus grand que le texte courant
        pages = [_page(1, ("Chapitre 1", 10), ("corps", 10))]

        assert "niveau" not in detecter_structure(pages)[0]["blocs"][0]


# ---------------------------------------------------------------------------
# _creer_chunk
# ---------------------------------------------------------------------------

def test_creer_chunk_remplit_les_metadonnees():
    hierarchie = {"partie": "P1", "titre": "T1", "chapitre": "C1",
                  "section": "S1", "article": "Article 5"}

    chunk = _creer_chunk("texte", "cours.pdf", "civil", hierarchie, {3, 1, 2}, 7)

    assert chunk == Chunk(texte="texte", metadata={
        "source": "cours.pdf",
        "domaine": "civil",
        "partie": "P1",
        "chapitre": "C1",
        "section": "S1",
        "article_num": "Article 5",
        "pages": "1,2,3",
        "chunk_index": 7,
    })


def test_creer_chunk_sans_pages():
    chunk = _creer_chunk("t", "s", "", {}, set(), 0)
    assert chunk.metadata["pages"] == ""
    assert chunk.metadata["chapitre"] == ""


# ---------------------------------------------------------------------------
# _chunker_structurel
# ---------------------------------------------------------------------------

class TestChunkerStructurel:

    def _pages(self):
        pages = [
            _page(1, ("Chapitre 1", 14), ("Intro du chapitre", 10),
                  ("Section 1", 14), ("Texte S1", 10)),
            _page(2, ("Article 1", 10), ("Texte A1", 10),
                  ("Chapitre 2", 14), ("Texte C2", 10)),
        ]
        return detecter_structure(pages)

    def test_un_chunk_par_element_de_structure(self):
        chunks = _chunker_structurel(self._pages(), "cours.pdf", "civil")

        assert [c.texte for c in chunks] == [
            "Chapitre 1\nIntro du chapitre",
            "Section 1\nTexte S1",
            "Article 1\nTexte A1",
            "Chapitre 2\nTexte C2",
        ]
        assert [c.metadata["chunk_index"] for c in chunks] == [0, 1, 2, 3]

    def test_hierarchie_propagee_dans_les_metadonnees(self):
        chunks = _chunker_structurel(self._pages(), "cours.pdf", "civil")
        article = chunks[2].metadata

        assert article["chapitre"] == "Chapitre 1"
        assert article["section"] == "Section 1"
        assert article["article_num"] == "Article 1"
        assert article["pages"] == "2"

    def test_nouveau_chapitre_reinitialise_section_et_article(self):
        chunks = _chunker_structurel(self._pages(), "cours.pdf", "civil")
        chap2 = chunks[3].metadata

        assert chap2["chapitre"] == "Chapitre 2"
        assert chap2["section"] == ""
        assert chap2["article_num"] == ""

    def test_section_trop_longue_decoupee(self, petits_chunks):
        # CHUNK_SIZE = 10 : coupure des que le texte depasse 20 caracteres
        pages = detecter_structure([
            _page(1, ("Article 1", 10), ("a" * 15, 10), ("b" * 15, 10)),
        ])

        chunks = _chunker_structurel(pages, "s", "")

        assert [c.texte for c in chunks] == ["Article 1\n" + "a" * 15, "b" * 15]
        assert all(c.metadata["article_num"] == "Article 1" for c in chunks)

    def test_texte_avant_le_premier_titre_conserve(self):
        pages = detecter_structure([_page(1, ("Preambule", 10), ("Article 1", 10), ("x", 10))])

        chunks = _chunker_structurel(pages, "s", "")

        assert chunks[0].texte == "Preambule"
        assert chunks[0].metadata["article_num"] == ""


# ---------------------------------------------------------------------------
# _chunker_par_taille
# ---------------------------------------------------------------------------

class TestChunkerParTaille:

    def test_fenetre_glissante_avec_chevauchement(self, petits_chunks):
        # "abcdefghijklmnopqrst\n" = 21 caracteres ; fenetres de 10, pas de 7
        pages = [_page(1, ("abcdefghijklmnopqrst", 10))]

        chunks = _chunker_par_taille(pages, "s", "d")

        assert [c.texte for c in chunks] == ["abcdefghij", "hijklmnopq", "opqrst"]
        # Le chevauchement de 3 caracteres garde le contexte entre deux chunks
        assert chunks[0].texte[-3:] == chunks[1].texte[:3]

    def test_metadonnees(self, petits_chunks):
        chunks = _chunker_par_taille([_page(1, ("abc", 10))], "cours.pdf", "civil")

        assert chunks[0].metadata == {
            "source": "cours.pdf", "domaine": "civil", "pages": "1", "chunk_index": 0,
        }

    def test_pages_couvertes_par_chaque_chunk(self, petits_chunks):
        pages = [_page(1, ("aaaaaaa", 10)), _page(2, ("bbbbbbb", 10))]

        chunks = _chunker_par_taille(pages, "s", "")

        assert chunks[0].metadata["pages"] == "1,2"  # "aaaaaaa\nbb"
        assert chunks[-1].metadata["pages"] == "2"

    @pytest.mark.xfail(strict=True, reason=(
        "Bug connu : le calcul des pages suppose qu'une page fait au plus "
        "CHUNK_SIZE caracteres. Une page longue n'est plus rattachee aux chunks "
        "de sa fin."
    ))
    def test_page_longue_rattachee_a_tous_ses_chunks(self, petits_chunks):
        pages = [_page(1, ("x" * 40, 10)), _page(2, ("y" * 5, 10))]

        chunks = _chunker_par_taille(pages, "s", "")

        # Le chunk qui chevauche la fin de la page 1 et le debut de la page 2
        chevauchant = next(c for c in chunks if "x" in c.texte and "y" in c.texte)
        assert chevauchant.metadata["pages"] == "1,2"


# ---------------------------------------------------------------------------
# chunker_document (pipeline complet sur un vrai PDF)
# ---------------------------------------------------------------------------

class TestChunkerDocument:

    def test_pdf_structure_decoupe_par_articles(self, tmp_path):
        lignes = [("Chapitre 1", 18)]
        for i in range(1, 6):
            lignes += [(f"Article {i}", 11), (f"Contenu de l'article {i}.", 11)]
        chemin = _ecrire_pdf(tmp_path / "code.pdf", [lignes])

        chunks = chunker_document(chemin, source="code.pdf", domaine="civil")

        # >= 5 niveaux detectes -> decoupage structurel
        assert "article_num" in chunks[0].metadata
        assert [c.metadata["article_num"] for c in chunks if c.metadata["article_num"]] == [
            f"Article {i}" for i in range(1, 6)
        ]
        assert all(c.metadata["domaine"] == "civil" for c in chunks)

    def test_pdf_sans_structure_decoupe_par_taille(self, tmp_path):
        chemin = _ecrire_pdf(tmp_path / "notes.pdf", [[("Des notes sans titre.", 11)]])

        chunks = chunker_document(chemin, source="notes.pdf")

        assert len(chunks) == 1
        assert "article_num" not in chunks[0].metadata  # format du fallback
        assert chunks[0].texte == "Des notes sans titre."

    def test_pdf_vide(self, tmp_path):
        chemin = _ecrire_pdf(tmp_path / "vide.pdf", [[]])

        assert chunker_document(chemin, source="vide.pdf") == []
