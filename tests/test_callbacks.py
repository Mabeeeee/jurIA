"""Tests de l'affichage des sources dans les Steps Chainlit (juria/rag/callbacks.py)."""

from juria.rag.callbacks import formater_sources


def test_aucune_source():
    assert formater_sources([]) == "Aucune source trouvee."


def test_document_local_complet(resultat):
    r = resultat(score=0.123, source="cours.pdf", chapitre="Chap. 1",
                 section="Sect. 2", article_num="Art. 3", pages="4")

    assert formater_sources([r]) == (
        "- **[1]** cours.pdf - Chap. 1 - Sect. 2 - Art. 3 - p. 4 (pertinence: 88%)"
    )


def test_document_sans_metadonnees(resultat):
    assert formater_sources([resultat(score=0.0)]) == (
        "- **[1]** Source inconnue (pertinence: 100%)"
    )


def test_article_legifrance_avec_lien(resultat):
    r = resultat(score=0.2, source_type="legifrance", legi_id="LEGIARTI1", num="1240",
                 date_verification="2026-01-01", url="https://legifrance/1")

    assert formater_sources([r]) == (
        "- **[1]** [Art. 1240 (LEGIARTI1) — verifie le 2026-01-01]"
        "(https://legifrance/1) (pertinence: 80%)"
    )


def test_article_legifrance_minimal_sans_lien(resultat):
    r = resultat(score=0.3, source_type="legifrance", legi_id="LEGIARTI1")

    assert formater_sources([r]) == "- **[1]** Legifrance LEGIARTI1 (pertinence: 70%)"


def test_une_ligne_par_source_numerotee(resultat):
    lignes = formater_sources([resultat(source="a"), resultat(source="b")]).splitlines()

    assert [ligne[:9] for ligne in lignes] == ["- **[1]**", "- **[2]**"]
