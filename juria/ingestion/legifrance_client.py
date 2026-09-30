"""Client API Legifrance (PISTE) — OAuth2 + recherche + consultation d'articles."""

import logging
import os
import re
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dataclass resultat (conservee pour retrocompat avec chat.py)
# ---------------------------------------------------------------------------


@dataclass
class ResultatLegifrance:
    """Un resultat de recherche Legifrance."""
    texte: str
    titre: str
    reference: str
    url: str


def formater_contexte_legifrance(resultats: list[ResultatLegifrance]) -> str:
    """Formate les resultats Legifrance en texte pour le prompt LLM.

    Conservee pour retrocompat — a terme supprimable.
    """
    if not resultats:
        return "Aucun resultat trouve sur Legifrance."
    if len(resultats) == 1 and resultats[0].reference == "":
        return resultats[0].texte
    parties = []
    for i, r in enumerate(resultats, 1):
        header = f"[{i}] {r.reference}"
        if r.url:
            header += f"\n    Lien: {r.url}"
        parties.append(f"{header}\n{r.texte}")
    return "\n\n---\n\n".join(parties)


# ---------------------------------------------------------------------------
# URLs par defaut (sandbox PISTE)
# ---------------------------------------------------------------------------

_DEFAULT_OAUTH_URL = "https://sandbox-oauth.piste.gouv.fr/api/oauth/token"
_DEFAULT_API_BASE = "https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app"


# ---------------------------------------------------------------------------
# LegifranceClient
# ---------------------------------------------------------------------------


class LegifranceClient:
    """Client asynchrone pour l'API Legifrance via PISTE.

    - Token OAuth2 cache en memoire, renouvele 60s avant expiration
    - httpx.AsyncClient singleton lazy, recree si ferme
    - Retry unique sur 401 (token expire)
    """

    def __init__(self):
        self._client_id = os.getenv("LEGIFRANCE_CLIENT_ID", "")
        self._client_secret = os.getenv("LEGIFRANCE_CLIENT_SECRET", "")
        self._oauth_url = os.getenv("PISTE_OAUTH_URL", _DEFAULT_OAUTH_URL)
        self._api_base = os.getenv("PISTE_API_BASE", _DEFAULT_API_BASE)

        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._http: httpx.AsyncClient | None = None

    # --- HTTP client lifecycle ---

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    # --- OAuth2 ---

    async def _ensure_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expires_at - 60:
            return self._token

        http = self._get_http()
        resp = await http.post(
            self._oauth_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": "openid",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        self._token = data["access_token"]
        self._token_expires_at = now + data.get("expires_in", 3600)
        return self._token

    async def _api_post(self, path: str, body: dict, *, _retried: bool = False) -> dict:
        """POST vers l'API PISTE avec gestion du token et retry 401 unique."""
        token = await self._ensure_token()
        http = self._get_http()

        resp = await http.post(
            f"{self._api_base}{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=body,
        )

        if resp.status_code == 401 and not _retried:
            logger.info("Token expire, renouvellement...")
            self._token = None
            return await self._api_post(path, body, _retried=True)

        resp.raise_for_status()
        return resp.json()

    # --- Recherche ---

    async def search(
        self,
        mots_cles: str,
        nom_code: str | None = None,
    ) -> list[dict]:
        """Recherche dans les codes en vigueur.

        Essaie d'abord TOUS_LES_MOTS_DANS_UN_CHAMP, puis fallback
        UN_DES_MOTS si aucun resultat.

        Retourne liste de dicts {id, code, num, extrait}.
        """
        if not self._client_id or not self._client_secret:
            logger.warning("Credentials Legifrance non configurees.")
            return []

        for type_recherche in ("TOUS_LES_MOTS_DANS_UN_CHAMP", "UN_DES_MOTS"):
            resultats = await self._search_with_type(
                mots_cles, type_recherche, nom_code
            )
            if resultats:
                return resultats

        return []

    async def _search_with_type(
        self,
        mots_cles: str,
        type_recherche: str,
        nom_code: str | None,
    ) -> list[dict]:
        filtres = [{"facette": "DATE_VERSION", "valeur": "VIGUEUR"}]
        if nom_code:
            filtres.append({"facette": "NOM_CODE", "valeur": nom_code})

        body = {
            "recherche": {
                "champs": [
                    {
                        "typeChamp": "ALL",
                        "criteres": [
                            {
                                "typeRecherche": type_recherche,
                                "valeur": mots_cles,
                                "operateur": "ET",
                            }
                        ],
                        "operateur": "ET",
                    }
                ],
                "filtres": filtres,
                "pageNumber": 1,
                "pageSize": 8,
                "sort": "PERTINENCE",
                "typePagination": "DEFAUT",
            },
            "fond": "CODE_DATE",
        }

        data = await self._api_post("/search", body)
        return self._parse_search_results(data)

    @staticmethod
    def _parse_search_results(data: dict) -> list[dict]:
        resultats = []
        for item in data.get("results", []):
            article_id = item.get("id", "")
            titles = item.get("titles", [])
            code = titles[0].get("title", "") if titles else ""
            num = item.get("num", "")

            extrait = ""
            sections = item.get("sections", [])
            if sections:
                extracts = sections[0].get("extracts", [])
                if extracts:
                    extrait = extracts[0].get("text", "")
            if not extrait:
                extrait = item.get("text", "")

            resultats.append({
                "id": article_id,
                "code": code,
                "num": num,
                "extrait": extrait,
            })
        return resultats

    # --- Consultation d'article ---

    async def get_article(self, article_id: str) -> dict:
        """Recupere le texte integral d'un article.

        Retourne {texte, etat, num, url}.
        """
        if not self._client_id or not self._client_secret:
            logger.warning("Credentials Legifrance non configurees.")
            return {"texte": "", "etat": "", "num": "", "url": ""}

        data = await self._api_post("/consult/getArticle", {"id": article_id})

        article = data.get("article", data)
        texte_html = article.get("texte", article.get("texteHtml", ""))
        texte = re.sub(r"<[^>]+>", "", texte_html).strip()

        etat = article.get("etat", article.get("articleVersions", [{}])[0].get("etat", ""))
        num = article.get("num", "")

        url = f"https://www.legifrance.gouv.fr/codes/article_lc/{article_id}"

        return {
            "texte": texte,
            "etat": etat,
            "num": num,
            "url": url,
        }


# ---------------------------------------------------------------------------
# Singleton lazy
# ---------------------------------------------------------------------------

_client: LegifranceClient | None = None


def get_legifrance_client() -> LegifranceClient:
    """Retourne le singleton LegifranceClient."""
    global _client
    if _client is None:
        _client = LegifranceClient()
    return _client
