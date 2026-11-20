"""Tests du client API Legifrance / PISTE (juria/ingestion/legifrance_client.py).

Aucun appel reseau : on branche un httpx.MockTransport sur le client HTTP.
Le transport recoit chaque requete et renvoie la reponse que l'on veut
simuler (token OAuth, resultats de recherche, erreur 500...).
"""

import json
import logging

import httpx
import pytest

from juria.ingestion import legifrance_client
from juria.ingestion.legifrance_client import (
    LegifranceClient,
    ResultatLegifrance,
    formater_contexte_legifrance,
    get_legifrance_client,
)

OAUTH_URL = "https://oauth.test/token"
API_BASE = "https://api.test/lf"


# ---------------------------------------------------------------------------
# Faux serveur PISTE
# ---------------------------------------------------------------------------

class FauxPiste:
    """Simule l'API : file de reponses par chemin + historique des requetes."""

    def __init__(self):
        self.requetes: list[httpx.Request] = []
        self.reponses: dict[str, list] = {"/token": [], "/search": [], "/consult/getArticle": []}
        self.numero_token = 0

    def repondre(self, chemin, *reponses):
        """Empile des reponses (dict -> JSON 200, int -> code HTTP, Exception -> levee)."""
        self.reponses[chemin].extend(reponses)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requetes.append(request)
        chemin = request.url.path.removeprefix("/lf")

        if chemin == "/token" and not self.reponses["/token"]:
            self.numero_token += 1
            return httpx.Response(200, json={"access_token": f"tok{self.numero_token}",
                                             "expires_in": 3600})

        reponse = self.reponses[chemin].pop(0)
        if isinstance(reponse, Exception):
            raise reponse
        if isinstance(reponse, int):
            return httpx.Response(reponse, json={"error": "simulee"})
        return httpx.Response(200, json=reponse)

    def appels(self, chemin):
        return [r for r in self.requetes if r.url.path.endswith(chemin)]

    def corps(self, chemin, index=0):
        return json.loads(self.appels(chemin)[index].content)


@pytest.fixture
def piste():
    return FauxPiste()


@pytest.fixture
def client(monkeypatch, piste):
    monkeypatch.setenv("LEGIFRANCE_CLIENT_ID", "id")
    monkeypatch.setenv("LEGIFRANCE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("PISTE_OAUTH_URL", OAUTH_URL)
    monkeypatch.setenv("PISTE_API_BASE", API_BASE)
    c = LegifranceClient()
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(piste))
    return c


def _resultat_search(code, *extraits):
    """Un 'result' de /search : un code contenant des extraits d'articles."""
    return {
        "titles": [{"title": code}],
        "sections": [{"extracts": list(extraits)}],
    }


def _extrait(id_, num="", valeur="", **autres):
    return {"id": id_, "num": num, "values": [valeur], **autres}


# ---------------------------------------------------------------------------
# formater_contexte_legifrance (retrocompat)
# ---------------------------------------------------------------------------

class TestFormaterContexteLegifrance:

    def test_aucun_resultat(self):
        assert formater_contexte_legifrance([]) == "Aucun resultat trouve sur Legifrance."

    def test_message_brut_sans_reference(self):
        r = ResultatLegifrance(texte="Service indisponible", titre="", reference="", url="")
        assert formater_contexte_legifrance([r]) == "Service indisponible"

    def test_plusieurs_resultats(self):
        resultats = [
            ResultatLegifrance(texte="T1", titre="", reference="Art. 1", url="https://u/1"),
            ResultatLegifrance(texte="T2", titre="", reference="Art. 2", url=""),
        ]
        assert formater_contexte_legifrance(resultats) == (
            "[1] Art. 1\n    Lien: https://u/1\nT1\n\n---\n\n[2] Art. 2\nT2"
        )


# ---------------------------------------------------------------------------
# _parse_search_results
# ---------------------------------------------------------------------------

class TestParseSearchResults:

    def test_extrait_les_articles_et_retire_le_surlignage(self):
        data = {"results": [_resultat_search(
            "<mark>Code</mark> civil",
            _extrait("LEGIARTI1", "1240", "Tout <mark>fait</mark> quelconque"),
        )]}

        assert LegifranceClient._parse_search_results(data) == [
            {"id": "LEGIARTI1", "code": "Code civil", "num": "1240",
             "extrait": "Tout fait quelconque"},
        ]

    def test_ignore_les_extraits_sans_id_et_utilise_le_titre_a_defaut_de_num(self):
        data = {"results": [_resultat_search(
            "Code penal",
            {"num": "1", "values": ["sans id"]},
            {"id": "LEGIARTI2", "title": "Article 121-3", "values": []},
        )]}

        assert LegifranceClient._parse_search_results(data) == [
            {"id": "LEGIARTI2", "code": "Code penal", "num": "Article 121-3", "extrait": ""},
        ]

    def test_tolere_les_champs_absents_ou_nuls(self):
        data = {"results": [{"titles": None, "sections": None}, {}]}
        assert LegifranceClient._parse_search_results(data) == []
        assert LegifranceClient._parse_search_results({}) == []

    def test_limite_a_10_articles_sur_plusieurs_codes(self):
        data = {"results": [
            _resultat_search("A", *[_extrait(f"A{i}") for i in range(6)]),
            _resultat_search("B", *[_extrait(f"B{i}") for i in range(6)]),
        ]}

        ids = [r["id"] for r in LegifranceClient._parse_search_results(data)]

        assert ids == [f"A{i}" for i in range(6)] + [f"B{i}" for i in range(4)]


# ---------------------------------------------------------------------------
# OAuth2 et _api_post
# ---------------------------------------------------------------------------

class TestAuthentification:

    async def test_token_demande_une_seule_fois_puis_mis_en_cache(self, client, piste):
        piste.repondre("/search", {"results": []}, {"results": []})

        await client._api_post("/search", {})
        await client._api_post("/search", {})

        assert len(piste.appels("/token")) == 1
        assert piste.appels("/search")[1].headers["Authorization"] == "Bearer tok1"

    async def test_demande_de_token_en_client_credentials(self, client, piste):
        piste.repondre("/search", {})

        await client._api_post("/search", {})

        formulaire = piste.appels("/token")[0].content.decode()
        assert "grant_type=client_credentials" in formulaire
        assert "client_id=id" in formulaire
        assert "client_secret=secret" in formulaire

    async def test_token_renouvele_60s_avant_expiration(self, client, piste):
        piste.repondre("/search", {}, {})
        await client._api_post("/search", {})

        # On simule un token qui expire dans 30 s : il doit etre renouvele
        client._token_expires_at = legifrance_client.time.time() + 30
        await client._api_post("/search", {})

        assert len(piste.appels("/token")) == 2
        assert piste.appels("/search")[1].headers["Authorization"] == "Bearer tok2"

    async def test_retry_unique_sur_401(self, client, piste):
        piste.repondre("/search", 401, {"ok": True})

        assert await client._api_post("/search", {}) == {"ok": True}
        assert len(piste.appels("/token")) == 2  # token jete puis redemande

    async def test_deux_401_consecutifs_levent_une_erreur(self, client, piste):
        piste.repondre("/search", 401, 401)

        with pytest.raises(httpx.HTTPStatusError):
            await client._api_post("/search", {})
        assert len(piste.appels("/search")) == 2  # pas de boucle infinie


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

class TestSearch:

    async def test_sans_credentials_aucun_appel(self, monkeypatch, piste):
        monkeypatch.delenv("LEGIFRANCE_CLIENT_ID", raising=False)
        monkeypatch.delenv("LEGIFRANCE_CLIENT_SECRET", raising=False)
        c = LegifranceClient()
        c._http = httpx.AsyncClient(transport=httpx.MockTransport(piste))

        assert await c.search("bail") == []
        assert piste.requetes == []

    async def test_premiere_strategie_suffit(self, client, piste):
        piste.repondre("/search", {"results": [_resultat_search("Code civil", _extrait("L1", "1"))]})

        resultats = await client.search("bail habitation")

        assert [r["id"] for r in resultats] == ["L1"]
        assert len(piste.appels("/search")) == 1
        critere = piste.corps("/search")["recherche"]["champs"][0]["criteres"][0]
        assert critere == {"typeRecherche": "TOUS_LES_MOTS_DANS_UN_CHAMP",
                           "valeur": "bail habitation", "operateur": "ET"}

    async def test_fallback_un_des_mots_si_rien_trouve(self, client, piste):
        piste.repondre("/search",
                       {"results": []},
                       {"results": [_resultat_search("Code civil", _extrait("L2"))]})

        resultats = await client.search("vice cache")

        assert [r["id"] for r in resultats] == ["L2"]
        types = [piste.corps("/search", i)["recherche"]["champs"][0]["criteres"][0]["typeRecherche"]
                 for i in range(2)]
        assert types == ["TOUS_LES_MOTS_DANS_UN_CHAMP", "UN_DES_MOTS"]

    async def test_aucun_resultat_avec_les_deux_strategies(self, client, piste):
        piste.repondre("/search", {"results": []}, {"results": []})

        assert await client.search("xyz") == []

    async def test_corps_de_requete_et_filtres(self, client, piste):
        piste.repondre("/search", {"results": [_resultat_search("C", _extrait("L1"))]})

        await client.search("dol", nom_code="Code civil")

        corps = piste.corps("/search")
        assert corps["fond"] == "CODE_DATE"
        date_version, nom_code = corps["recherche"]["filtres"]
        # Regression : DATE_VERSION doit etre un timestamp en ms, pas "VIGUEUR"
        assert date_version["facette"] == "DATE_VERSION"
        assert isinstance(date_version["singleDate"], int)
        assert date_version["singleDate"] > 1_600_000_000_000
        assert nom_code == {"facette": "NOM_CODE", "valeurs": ["Code civil"]}

    async def test_sans_nom_code_un_seul_filtre(self, client, piste):
        piste.repondre("/search", {"results": [_resultat_search("C", _extrait("L1"))]})

        await client.search("dol")

        assert len(piste.corps("/search")["recherche"]["filtres"]) == 1

    async def test_erreur_500_renvoie_liste_vide_et_warning(self, client, piste, caplog):
        piste.repondre("/search", 500)

        with caplog.at_level(logging.WARNING, logger=legifrance_client.__name__):
            assert await client.search("dol") == []

        assert "echoue" in caplog.text
        assert len(piste.appels("/search")) == 1  # pas de 2e strategie apres une erreur

    async def test_erreur_reseau_renvoie_liste_vide(self, client, piste):
        piste.repondre("/search", httpx.ConnectTimeout("timeout"))

        assert await client.search("dol") == []


# ---------------------------------------------------------------------------
# get_article
# ---------------------------------------------------------------------------

class TestGetArticle:

    async def test_texte_nettoye_du_html(self, client, piste):
        piste.repondre("/consult/getArticle", {"article": {
            "texte": "<p>Tout fait <b>quelconque</b> de l'homme...</p>",
            "etat": "VIGUEUR", "num": "1240",
        }})

        article = await client.get_article("LEGIARTI000032041571")

        assert article == {
            "texte": "Tout fait quelconque de l'homme...",
            "etat": "VIGUEUR",
            "num": "1240",
            "url": "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000032041571",
        }
        assert piste.corps("/consult/getArticle") == {"id": "LEGIARTI000032041571"}

    async def test_repli_sur_textehtml_et_articleversions(self, client, piste):
        piste.repondre("/consult/getArticle", {
            "texteHtml": "<p>Ancien texte</p>",
            "articleVersions": [{"etat": "ABROGE"}],
        })

        article = await client.get_article("L1")

        assert article["texte"] == "Ancien texte"
        assert article["etat"] == "ABROGE"
        assert article["num"] == ""

    async def test_erreur_api_renvoie_champs_vides_et_message(self, client, piste):
        piste.repondre("/consult/getArticle", 500)

        article = await client.get_article("L1")

        assert article["texte"] == article["etat"] == article["url"] == ""
        assert "500" in article["erreur"]

    async def test_sans_credentials(self, monkeypatch):
        monkeypatch.delenv("LEGIFRANCE_CLIENT_ID", raising=False)
        monkeypatch.delenv("LEGIFRANCE_CLIENT_SECRET", raising=False)

        article = await LegifranceClient().get_article("L1")

        assert article == {"texte": "", "etat": "", "num": "", "url": ""}


# ---------------------------------------------------------------------------
# Client HTTP et singleton
# ---------------------------------------------------------------------------

async def test_client_http_recree_s_il_est_ferme():
    c = LegifranceClient()
    premier = c._get_http()
    assert c._get_http() is premier

    await premier.aclose()

    assert c._get_http() is not premier


def test_singleton(monkeypatch):
    monkeypatch.setattr(legifrance_client, "_client", None)
    assert get_legifrance_client() is get_legifrance_client()
