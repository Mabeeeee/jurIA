"""Tests du moteur de recherche RAG (juria/rag/query_engine.py)."""

from datetime import date, timedelta

import pytest

from juria.config import FRAICHEUR_JOURS, SCORE_THRESHOLD
from juria.rag import query_engine
from juria.rag.query_engine import (
    ResultatRecherche,
    formater_contexte,
    rechercher,
    rechercher_docs_utilisateur,
)


class FauxStore:
    """Store ChromaDB factice : renvoie une reponse brute fixee et memorise l'appel."""

    def __init__(self, documents, distances, metadatas):
        self.reponse = {
            "documents": [documents],
            "distances": [distances],
            "metadatas": [metadatas],
        }
        self.appels = []

    def rechercher(self, query_embedding, top_k=5, filtre=None):
        self.appels.append({"embedding": query_embedding, "top_k": top_k, "filtre": filtre})
        return self.reponse


@pytest.fixture
def faux_store(monkeypatch, faux_modele):
    store = FauxStore(
        documents=["proche", "limite", "trop loin"],
        distances=[0.05, SCORE_THRESHOLD, SCORE_THRESHOLD + 0.01],
        metadatas=[{"source": "a"}, {"source": "b"}, {"source": "c"}],
    )
    monkeypatch.setattr(query_engine, "get_vector_store", lambda: store)
    monkeypatch.setattr(query_engine, "get_user_vector_store", lambda username: store)
    return store


# ---------------------------------------------------------------------------
# rechercher / rechercher_docs_utilisateur
# ---------------------------------------------------------------------------

class TestRechercher:

    def test_filtre_par_seuil_de_distance(self, faux_store):
        resultats = rechercher("responsabilite")

        # le seuil est inclusif (<=)
        assert [r.texte for r in resultats] == ["proche", "limite"]
        assert resultats[0] == ResultatRecherche(texte="proche", score=0.05, metadata={"source": "a"})

    def test_encode_la_requete_et_la_transmet_au_store(self, faux_store, faux_modele):
        rechercher("dol", top_k=3)

        assert faux_modele.appels == ["dol"]
        appel = faux_store.appels[0]
        assert appel["embedding"] == faux_modele.encode("dol").tolist()
        assert appel["top_k"] == 3
        assert appel["filtre"] is None

    def test_domaine_transforme_en_filtre_chroma(self, faux_store):
        rechercher("tva", domaine="procedure_fiscale")

        assert faux_store.appels[0]["filtre"] == {"domaine": "procedure_fiscale"}

    def test_reponse_vide_de_chroma(self, faux_store):
        faux_store.reponse = {}

        assert rechercher("x") == []

    def test_docs_utilisateur_utilise_le_store_de_l_utilisateur(self, monkeypatch, faux_store):
        demandes = []
        monkeypatch.setattr(
            query_engine, "get_user_vector_store",
            lambda username: demandes.append(username) or faux_store,
        )

        resultats = rechercher_docs_utilisateur("cours", "alice")

        assert demandes == ["alice"]
        assert [r.texte for r in resultats] == ["proche", "limite"]


# ---------------------------------------------------------------------------
# formater_contexte
# ---------------------------------------------------------------------------

class TestFormaterContexte:

    def test_aucun_resultat_declenche_le_fallback(self):
        # Ce marqueur est attendu tel quel par le prompt systeme
        assert formater_contexte([]) == "AUCUN_RESULTAT_PERTINENT"

    def test_resultat_document_local(self, resultat):
        r = resultat("Le contrat est...", source="cours.pdf", chapitre="Chapitre 1",
                     section="Section 2", article_num="Article 3", pages="4,5")

        assert formater_contexte([r]) == (
            "[1] (Source: cours.pdf | Chapitre: Chapitre 1 | Section: Section 2 "
            "| Article: Article 3 | Pages: 4,5)\nLe contrat est..."
        )

    def test_metadonnees_absentes(self, resultat):
        assert formater_contexte([resultat("t")]) == "[1] (Source inconnue)\nt"

    def test_resultats_numerotes_et_separes(self, resultat):
        texte = formater_contexte([resultat("A", source="a"), resultat("B", source="b")])

        assert texte == "[1] (Source: a)\nA\n\n---\n\n[2] (Source: b)\nB"

    def test_article_legifrance_frais(self, resultat):
        aujourd_hui = date.today().isoformat()
        r = resultat("Tout fait quelconque...", source_type="legifrance",
                     legi_id="LEGIARTI000032041571", code="Code civil", num="1240",
                     source="legifrance_fallback", date_verification=aujourd_hui)

        assert formater_contexte([r]) == (
            "[1] (Legifrance: LEGIARTI000032041571 | Code: Code civil | Art. 1240 "
            f"| Source: legifrance_fallback | Verifie: {aujourd_hui})\nTout fait quelconque..."
        )

    @pytest.mark.parametrize("anciennete_jours, a_reverifier", [
        (0, False),
        (FRAICHEUR_JOURS, False),       # pile a la limite : encore frais
        (FRAICHEUR_JOURS + 1, True),
        (1000, True),
    ])
    def test_tag_a_reverifier_selon_fraicheur(self, resultat, anciennete_jours, a_reverifier):
        date_verif = (date.today() - timedelta(days=anciennete_jours)).isoformat()
        r = resultat("t", source_type="legifrance", legi_id="L1", date_verification=date_verif)

        assert ("[A_REVERIFIER]" in formater_contexte([r])) is a_reverifier

    def test_legifrance_sans_date_ni_identifiant(self, resultat):
        r = resultat("t", source_type="legifrance")

        assert formater_contexte([r]) == "[1] (Source: legifrance)\nt"
