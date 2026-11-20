"""Tests de l'agent : execution des outils et boucle de tool calling (juria/chat.py).

Rien n'est appele pour de vrai : Chainlit, les recherches, Legifrance et les
LLM (Anthropic / Ollama) sont remplaces par des doublures. On teste la
logique propre a jurIA : quel outil est appele avec quels arguments, ce qui
est renvoye au LLM, et comment la boucle s'arrete.
"""

import copy
import json
from types import SimpleNamespace

import pytest

from juria import chat
from juria.ingestion import legifrance_client, legifrance_sync
from juria.rag import query_engine


# ---------------------------------------------------------------------------
# Doublures Chainlit
# ---------------------------------------------------------------------------

class FauxStep:
    """Imite cl.Step : context manager async qui memorise nom et sortie."""

    def __init__(self, name, type, icon, show_input):
        self.name_initial = name
        self.name = name
        self.icon = icon
        self.output = None

    async def __aenter__(self):
        FauxChainlit.steps.append(self)
        return self

    async def __aexit__(self, *exc):
        return False


class FauxSession:
    def __init__(self):
        self.valeurs = {}

    def get(self, cle):
        return self.valeurs.get(cle)


class FauxChainlit:
    steps: list[FauxStep] = []
    Step = FauxStep

    def __init__(self):
        FauxChainlit.steps = []
        self.user_session = FauxSession()

    @staticmethod
    def make_async(fonction):
        async def wrapper(*args, **kwargs):
            return fonction(*args, **kwargs)
        return wrapper


class FauxMessage:
    def __init__(self):
        self.tokens = []
        self.envoye = False

    async def stream_token(self, token):
        self.tokens.append(token)

    async def send(self):
        self.envoye = True


@pytest.fixture
def faux_cl(monkeypatch):
    faux = FauxChainlit()
    monkeypatch.setattr(chat, "cl", faux)
    return faux


# ---------------------------------------------------------------------------
# _citer
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("entree, attendu", [
    ("contrat de travail", "« contrat de travail »"),
    ("  plusieurs\n  espaces  ", "« plusieurs espaces »"),
    ("x" * 60, "« " + "x" * 60 + " »"),
    ("x" * 61, "« " + "x" * 59 + "… »"),
    (42, "« 42 »"),
])
def test_citer(entree, attendu):
    assert chat._citer(entree) == attendu


# ---------------------------------------------------------------------------
# _executer_outil
# ---------------------------------------------------------------------------

class TestOutilsBaseDocumentaire:

    async def test_rechercher_base_documentaire(self, faux_cl, monkeypatch, resultat):
        appels = []

        def faux_rechercher(requete, domaine=None):
            appels.append((requete, domaine))
            return [resultat("Art. L.169", source="lpf.pdf")]

        monkeypatch.setattr(query_engine, "rechercher", faux_rechercher)

        reponse = await chat._executer_outil(
            "rechercher_base_documentaire",
            {"requete": "droit de reprise", "domaine": "procedure_fiscale"},
        )

        assert appels == [("droit de reprise", "procedure_fiscale")]
        assert reponse == "[1] (Source: lpf.pdf)\nArt. L.169"
        (step,) = faux_cl.steps
        assert step.name_initial == "Recherche dans la base documentaire : « droit de reprise »"
        assert step.name == "Base documentaire : 1 source(s) pour « droit de reprise »"
        assert "lpf.pdf" in step.output

    async def test_base_vide_renvoie_le_marqueur_de_fallback(self, faux_cl, monkeypatch):
        monkeypatch.setattr(query_engine, "rechercher", lambda requete, domaine=None: [])

        reponse = await chat._executer_outil("rechercher_base_documentaire", {"requete": "x"})

        assert reponse == "AUCUN_RESULTAT_PERTINENT"

    async def test_rechercher_mes_cours_utilise_l_utilisateur_connecte(
            self, faux_cl, monkeypatch, resultat):
        appels = []
        monkeypatch.setattr(query_engine, "rechercher_docs_utilisateur",
                            lambda requete, user: appels.append(user) or [resultat("td")])
        faux_cl.user_session.valeurs["user"] = SimpleNamespace(identifier="alice")

        await chat._executer_outil("rechercher_mes_cours", {"requete": "td 3"})

        assert appels == ["alice"]
        assert faux_cl.steps[0].name == "Vos documents : 1 passage(s) pour « td 3 »"

    async def test_rechercher_mes_cours_sans_utilisateur(self, faux_cl, monkeypatch):
        appels = []
        monkeypatch.setattr(query_engine, "rechercher_docs_utilisateur",
                            lambda requete, user: appels.append(user) or [])

        await chat._executer_outil("rechercher_mes_cours", {"requete": "x"})

        assert appels == ["anonymous"]


class FauxLegifrance:
    def __init__(self, resultats=None, article=None):
        self.resultats = resultats or []
        self.article = article or {}
        self.recherches = []

    async def search(self, mots_cles, nom_code=None):
        self.recherches.append((mots_cles, nom_code))
        return self.resultats

    async def get_article(self, article_id):
        return self.article


@pytest.fixture
def legifrance(monkeypatch):
    faux = FauxLegifrance()
    monkeypatch.setattr(legifrance_client, "get_legifrance_client", lambda: faux)
    return faux


class TestOutilsLegifrance:

    async def test_search_legifrance(self, faux_cl, legifrance):
        legifrance.resultats = [
            {"id": "LEGIARTI1", "code": "Code civil", "num": "1240", "extrait": "Tout fait"},
        ]

        reponse = await chat._executer_outil(
            "search_legifrance", {"mots_cles": "responsabilite", "nom_code": "Code civil"})

        assert legifrance.recherches == [("responsabilite", "Code civil")]
        assert reponse == "- ID: LEGIARTI1 | Code civil Art. 1240 — Tout fait"
        step = faux_cl.steps[0]
        assert step.name_initial == "Recherche Légifrance (Code civil) : « responsabilite »"
        assert "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI1" in step.output

    async def test_search_legifrance_extrait_tronque(self, faux_cl, legifrance):
        legifrance.resultats = [{"id": "L1", "extrait": "a" * 300}]

        reponse = await chat._executer_outil("search_legifrance", {"mots_cles": "x"})

        assert reponse.endswith("— " + "a" * 120)

    async def test_search_legifrance_sans_resultat(self, faux_cl, legifrance):
        reponse = await chat._executer_outil("search_legifrance", {"mots_cles": "xyz"})

        assert reponse == "Aucun article trouve sur Legifrance pour ces mots-cles."
        assert faux_cl.steps[0].output == "Aucun article trouvé."

    async def test_get_article_synchronise_et_renvoie_le_texte(
            self, faux_cl, legifrance, monkeypatch):
        legifrance.article = {"texte": "Tout fait quelconque...", "etat": "VIGUEUR",
                              "num": "1240", "url": "https://lf/1240"}
        syncs = []
        monkeypatch.setattr(legifrance_sync, "synchroniser_article",
                            lambda *args, meta: syncs.append((*args, meta)) or "ajoute")

        reponse = await chat._executer_outil(
            "get_article_legifrance", {"article_id": "LEGIARTI1", "nom_code": "Code civil"})

        assert syncs == [("LEGIARTI1", "Tout fait quelconque...", "VIGUEUR",
                          {"code": "Code civil", "num": "1240", "url": "https://lf/1240"})]
        assert reponse == (
            "Article 1240 (Code civil)\nEtat: VIGUEUR\nSynchronisation: ajoute\n"
            "URL: https://lf/1240\n\nTout fait quelconque..."
        )
        assert faux_cl.steps[0].name == "Article 1240 du Code civil (en vigueur)"

    async def test_get_article_abroge_affiche_son_etat(self, faux_cl, legifrance, monkeypatch):
        legifrance.article = {"texte": "", "etat": "MODIFIE_MORT_NE", "num": "12", "url": ""}
        monkeypatch.setattr(legifrance_sync, "synchroniser_article", lambda *a, meta: "ignore")

        await chat._executer_outil("get_article_legifrance", {"article_id": "L1"})

        assert faux_cl.steps[0].name == "Article 12 (modifie mort ne)"

    async def test_get_article_erreur_api(self, faux_cl, legifrance, monkeypatch):
        legifrance.article = {"texte": "", "erreur": "500 Server Error"}
        syncs = []
        monkeypatch.setattr(legifrance_sync, "synchroniser_article",
                            lambda *a, meta: syncs.append(a))

        reponse = await chat._executer_outil("get_article_legifrance", {"article_id": "L1"})

        assert reponse == "Erreur lors de la recuperation de l'article L1 : 500 Server Error"
        assert syncs == []  # rien n'est synchronise en cas d'erreur
        assert faux_cl.steps[0].name == "Article L1 indisponible sur Légifrance"


async def test_outil_inconnu(faux_cl):
    reponse = await chat._executer_outil("supprimer_la_base", {})

    assert json.loads(reponse) == {"erreur": "Outil inconnu : supprimer_la_base"}
    assert faux_cl.steps == []


# ---------------------------------------------------------------------------
# Boucle Anthropic
# ---------------------------------------------------------------------------

def _bloc_texte(texte):
    return SimpleNamespace(type="text", text=texte)


def _bloc_outil(id_, nom, entree):
    return SimpleNamespace(type="tool_use", id=id_, name=nom, input=entree)


class FauxAnthropic:
    """Client Anthropic factice : renvoie les reponses programmees, une par appel."""

    def __init__(self, *reponses):
        self.reponses = list(reponses)
        self.appels = []
        self.messages = self  # pour client.messages.create(...)

    async def create(self, **kwargs):
        self.appels.append(copy.deepcopy(kwargs))
        return SimpleNamespace(content=self.reponses.pop(0))


@pytest.fixture
def outils_espion(monkeypatch):
    """Remplace _executer_outil : memorise les appels, renvoie un resultat fixe."""
    appels = []

    async def faux_executer(nom, arguments):
        appels.append((nom, arguments))
        return f"resultat de {nom}"

    monkeypatch.setattr(chat, "_executer_outil", faux_executer)
    return appels


class TestStreamAnthropic:

    @pytest.fixture
    def anthropic(self, monkeypatch):
        def installer(*reponses):
            client = FauxAnthropic(*reponses)
            monkeypatch.setattr(chat, "_anthropic_client", client, raising=False)
            monkeypatch.setattr(chat, "_anthropic_model", "modele-test", raising=False)
            return client
        return installer

    async def test_reponse_directe_sans_outil(self, anthropic, outils_espion):
        client = anthropic([_bloc_texte("Bonjour"), _bloc_texte(" !")])
        msg = FauxMessage()

        reponse = await chat._stream_anthropic([{"role": "user", "content": "salut"}], msg)

        assert reponse == "Bonjour !"
        assert msg.tokens == ["Bonjour !"] and msg.envoye
        assert outils_espion == []
        appel = client.appels[0]
        assert appel["model"] == "modele-test"
        assert appel["system"] == chat.SYSTEM_PROMPT
        assert [t["name"] for t in appel["tools"]] == [
            "rechercher_base_documentaire", "rechercher_mes_cours",
            "search_legifrance", "get_article_legifrance",
        ]

    async def test_boucle_outil_puis_reponse(self, anthropic, outils_espion):
        client = anthropic(
            [_bloc_texte("Je cherche."),
             _bloc_outil("t1", "rechercher_base_documentaire", {"requete": "dol"})],
            [_bloc_texte("Le dol est...")],
        )
        historique = [{"role": "user", "content": "dol ?"}]

        reponse = await chat._stream_anthropic(historique, FauxMessage())

        assert reponse == "Le dol est..."
        assert outils_espion == [("rechercher_base_documentaire", {"requete": "dol"})]
        # Le 2e appel contient la demande d'outil puis son resultat
        assert client.appels[1]["messages"][1:] == [
            {"role": "assistant", "content": [
                {"type": "text", "text": "Je cherche."},
                {"type": "tool_use", "id": "t1", "name": "rechercher_base_documentaire",
                 "input": {"requete": "dol"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": "resultat de rechercher_base_documentaire"},
            ]},
        ]
        assert historique == [{"role": "user", "content": "dol ?"}]  # pas modifie

    async def test_plusieurs_outils_dans_un_meme_tour(self, anthropic, outils_espion):
        client = anthropic(
            [_bloc_outil("a", "search_legifrance", {"mots_cles": "bail"}),
             _bloc_outil("b", "rechercher_mes_cours", {"requete": "bail"})],
            [_bloc_texte("ok")],
        )

        await chat._stream_anthropic([], FauxMessage())

        assert [nom for nom, _ in outils_espion] == ["search_legifrance", "rechercher_mes_cours"]
        resultats = client.appels[1]["messages"][-1]["content"]
        assert [r["tool_use_id"] for r in resultats] == ["a", "b"]


# ---------------------------------------------------------------------------
# Boucle Ollama (API compatible OpenAI)
# ---------------------------------------------------------------------------

def _reponse_openai(contenu=None, tool_calls=None):
    message = SimpleNamespace(content=contenu, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _tool_call(id_, nom, arguments):
    return SimpleNamespace(id=id_, function=SimpleNamespace(name=nom, arguments=json.dumps(arguments)))


class FauxOllama:
    def __init__(self, *reponses):
        self.reponses = list(reponses)
        self.appels = []
        self.chat = SimpleNamespace(completions=self)

    async def create(self, **kwargs):
        self.appels.append(list(kwargs["messages"]))
        return self.reponses.pop(0)


class TestStreamOllama:

    @pytest.fixture
    def ollama(self, monkeypatch):
        def installer(*reponses):
            client = FauxOllama(*reponses)
            monkeypatch.setattr(chat, "_ollama_client", client, raising=False)
            monkeypatch.setattr(chat, "_ollama_model", "mistral", raising=False)
            return client
        return installer

    async def test_prompt_systeme_en_tete(self, ollama, outils_espion):
        client = ollama(_reponse_openai("Bonjour"))

        reponse = await chat._stream_ollama([{"role": "user", "content": "salut"}], FauxMessage())

        assert reponse == "Bonjour"
        assert client.appels[0][0] == {"role": "system", "content": chat.SYSTEM_PROMPT}

    async def test_arguments_json_decodes_et_resultat_renvoye(self, ollama, outils_espion):
        client = ollama(
            _reponse_openai(tool_calls=[_tool_call("c1", "search_legifrance", {"mots_cles": "dol"})]),
            _reponse_openai("Reponse finale"),
        )

        reponse = await chat._stream_ollama([], FauxMessage())

        assert reponse == "Reponse finale"
        assert outils_espion == [("search_legifrance", {"mots_cles": "dol"})]
        assert client.appels[1][-1] == {"role": "tool", "tool_call_id": "c1",
                                        "content": "resultat de search_legifrance"}

    async def test_contenu_none_devient_chaine_vide(self, ollama, outils_espion):
        ollama(_reponse_openai(None))
        msg = FauxMessage()

        assert await chat._stream_ollama([], msg) == ""
        assert msg.envoye


# ---------------------------------------------------------------------------
# stream_response : choix du backend
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("use_anthropic, attendu", [(True, "anthropic"), (False, "ollama")])
async def test_stream_response_choisit_le_backend(monkeypatch, use_anthropic, attendu):
    async def faux_anthropic(history, msg):
        return "anthropic"

    async def faux_ollama(history, msg):
        return "ollama"

    monkeypatch.setattr(chat, "_use_anthropic", use_anthropic)
    monkeypatch.setattr(chat, "_stream_anthropic", faux_anthropic)
    monkeypatch.setattr(chat, "_stream_ollama", faux_ollama)

    assert await chat.stream_response([], FauxMessage()) == attendu
