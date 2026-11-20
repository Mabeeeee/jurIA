"""Tests de la synchronisation Legifrance -> ChromaDB (juria/ingestion/legifrance_sync.py).

On combine une vraie base ChromaDB temporaire (chroma_tmp) et le faux modele
d'embeddings (faux_modele) : on verifie ainsi l'etat reel de la base apres
chaque synchronisation.
"""

from datetime import date

import pytest

from juria.ingestion import legifrance_sync
from juria.ingestion.legifrance_sync import synchroniser_article
from juria.rag.vector_store import get_vector_store

pytestmark = pytest.mark.chroma

ARTICLE_ID = "LEGIARTI000032041571"
DOC_ID = f"legi_{ARTICLE_ID}"
META = {"code": "Code civil", "num": "1240",
        "url": "https://www.legifrance.gouv.fr/codes/article_lc/" + ARTICLE_ID}


@pytest.fixture
def base(chroma_tmp, faux_modele):
    return get_vector_store()


def _lire(base):
    return base.collection.get(ids=[DOC_ID], include=["documents", "metadatas"])


class TestArticleEnVigueur:

    def test_absent_de_la_base_ajoute(self, base, faux_modele):
        statut = synchroniser_article(ARTICLE_ID, "Tout fait quelconque...", "VIGUEUR", META)

        assert statut == "ajoute"
        stocke = _lire(base)
        assert stocke["documents"] == ["Tout fait quelconque..."]
        assert faux_modele.appels == ["Tout fait quelconque..."]

    def test_metadonnees_stockees(self, base):
        synchroniser_article(ARTICLE_ID, "texte", "VIGUEUR", META)

        aujourd_hui = date.today().isoformat()
        assert _lire(base)["metadatas"][0] == {
            "legi_id": ARTICLE_ID,
            "code": "Code civil",
            "num": "1240",
            "url": META["url"],
            "etat": "VIGUEUR",
            "source_type": "legifrance",
            "source": "legifrance_fallback",
            "date_ajout": aujourd_hui,
            "date_verification": aujourd_hui,
        }

    def test_meta_incomplete_remplacee_par_des_chaines_vides(self, base):
        synchroniser_article(ARTICLE_ID, "texte", "VIGUEUR", {})

        meta = _lire(base)["metadatas"][0]
        assert meta["code"] == meta["num"] == meta["url"] == ""

    def test_texte_identique_verifie(self, base):
        synchroniser_article(ARTICLE_ID, "texte", "VIGUEUR", META)

        assert synchroniser_article(ARTICLE_ID, "texte", "VIGUEUR", META) == "verifie"
        assert base.compter() == 1

    def test_texte_modifie_mis_a_jour(self, base):
        synchroniser_article(ARTICLE_ID, "ancienne version", "VIGUEUR", META)

        statut = synchroniser_article(ARTICLE_ID, "nouvelle version", "VIGUEUR", META)

        assert statut == "mis_a_jour"
        assert _lire(base)["documents"] == ["nouvelle version"]

    def test_re_verification_conserve_date_ajout_et_rafraichit_date_verification(self, base):
        # Article ajoute il y a longtemps, donc marque [A_REVERIFIER]
        base.upsert(ids=[DOC_ID], embeddings=[[0.1] * 8], documents=["texte"],
                    metadatas=[{"date_ajout": "2024-01-01", "date_verification": "2024-01-01"}])

        synchroniser_article(ARTICLE_ID, "texte", "VIGUEUR", META)

        meta = _lire(base)["metadatas"][0]
        assert meta["date_ajout"] == "2024-01-01"
        assert meta["date_verification"] == date.today().isoformat()


class TestArticleNonEnVigueur:

    @pytest.mark.parametrize("etat", ["ABROGE", "MODIFIE", "PERIME", ""])
    def test_present_dans_la_base_retire(self, base, etat):
        synchroniser_article(ARTICLE_ID, "texte", "VIGUEUR", META)

        assert synchroniser_article(ARTICLE_ID, "texte", etat, META) == "retire"
        assert base.compter() == 0

    def test_absent_de_la_base_ignore(self, base, faux_modele):
        assert synchroniser_article(ARTICLE_ID, "texte", "ABROGE", META) == "ignore"
        assert base.compter() == 0
        assert faux_modele.appels == []  # aucun encodage inutile

    def test_ne_touche_pas_aux_autres_articles(self, base):
        synchroniser_article("AUTRE", "autre", "VIGUEUR", META)
        synchroniser_article(ARTICLE_ID, "texte", "VIGUEUR", META)

        synchroniser_article(ARTICLE_ID, "texte", "ABROGE", META)

        assert base.collection.get()["ids"] == ["legi_AUTRE"]


def test_utilise_la_collection_principale(monkeypatch, faux_modele):
    """Variante sans ChromaDB : on verifie seulement ce qui est envoye au store."""

    class StoreEspion:
        def __init__(self):
            self.collection = self
            self.upserts = []

        def get(self, ids, include=None):
            return {"ids": [], "documents": [], "metadatas": []}

        def upsert(self, **kwargs):
            self.upserts.append(kwargs)

    espion = StoreEspion()
    monkeypatch.setattr(legifrance_sync, "get_vector_store", lambda: espion)

    synchroniser_article("L1", "texte", "VIGUEUR", META)

    (appel,) = espion.upserts
    assert appel["ids"] == ["legi_L1"]
    assert appel["embeddings"] == [faux_modele.encode("texte").tolist()]
