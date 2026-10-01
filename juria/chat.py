"""LLM backend selection, streaming, and tool calling for jurIA."""

import json
import os

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
import chainlit as cl

from juria.auth import is_dev_mode, is_petite_config
from juria.prompts import (
    SYSTEM_PROMPT, TOOL_RECHERCHE, TOOL_RECHERCHE_OPENAI,
    TOOL_RECHERCHE_COURS, TOOL_RECHERCHE_COURS_OPENAI,
    TOOL_SEARCH_LEGIFRANCE, TOOL_SEARCH_LEGIFRANCE_OPENAI,
    TOOL_GET_ARTICLE_LEGIFRANCE, TOOL_GET_ARTICLE_LEGIFRANCE_OPENAI,
)

# ---------------------------------------------------------------------------
# Client & model selection based on environment
# ---------------------------------------------------------------------------

# Modele leger utilise en repli quand JURIA_PETITE_CONFIG=true, qu'aucun
# OLLAMA_MODEL explicite n'est fourni, et qu'aucune ANTHROPIC_API_KEY n'est
# disponible : garde un tool calling fiable tout en restant raisonnable en
# RAM/CPU (~2 Go), contrairement a mistral (7B). donc on met : llama3.2:3b
OLLAMA_MODEL_PETITE_CONFIG = "mistral"

# En petite config, on prefere l'API Claude (Haiku, rapide/peu cher) a un
# modele Ollama local qui reste trop lourd/lent pour la machine. On ne bascule
# ainsi que si une cle API est effectivement disponible ; sinon on retombe sur
# le modele Ollama allege ci-dessus.
_use_anthropic = (not is_dev_mode()) or (
    is_petite_config() and bool(os.getenv("ANTHROPIC_API_KEY"))
)

if _use_anthropic:
    _anthropic_client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    _anthropic_model = "claude-sonnet-5-5" if is_dev_mode() else "claude-sonnet-5-5" #claude-haiku-4-5-20251001
else:
    _ollama_client = AsyncOpenAI(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        api_key="ollama",
    )
    _default_ollama_model = OLLAMA_MODEL_PETITE_CONFIG if is_petite_config() else "mistral"
    _ollama_model = os.getenv("OLLAMA_MODEL", _default_ollama_model)


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def _citer(texte: str, max_len: int = 60) -> str:
    """Mots-cles entre guillemets pour le libelle d'un Step, tronques si besoin."""
    texte = " ".join(str(texte).split())
    if len(texte) > max_len:
        texte = texte[: max_len - 1] + "…"
    return f"« {texte} »"


async def _executer_outil(nom: str, arguments: dict) -> str:
    """Execute un outil RAG et l'affiche dans un Step Chainlit repliable.

    Pendant l'execution, le libelle (« Recherche ... : <mots-cles> ») est anime
    par public/juria.css ; une fois termine, il resume le resultat et se deplie
    sur le detail. Les appels ChromaDB sont synchrones : on les passe par
    cl.make_async pour ne pas bloquer la boucle (sinon l'animation ne
    s'affiche pas).
    """
    from juria.rag.query_engine import rechercher, rechercher_docs_utilisateur, formater_contexte
    from juria.rag.callbacks import formater_sources
    from juria.ingestion.legifrance_client import get_legifrance_client
    from juria.ingestion.legifrance_sync import synchroniser_article

    if nom == "rechercher_base_documentaire":
        requete = arguments.get("requete", "")
        domaine = arguments.get("domaine")
        async with cl.Step(
            name=f"Recherche dans la base documentaire : {_citer(requete)}",
            type="tool", icon="library", show_input=False,
        ) as step:
            resultats = await cl.make_async(rechercher)(requete, domaine=domaine)
            step.name = f"Base documentaire : {len(resultats)} source(s) pour {_citer(requete)}"
            step.output = formater_sources(resultats)
        return formater_contexte(resultats)

    if nom == "rechercher_mes_cours":
        requete = arguments.get("requete", "")
        user = cl.user_session.get("user")
        user_id = user.identifier if user else "anonymous"
        async with cl.Step(
            name=f"Recherche dans vos documents : {_citer(requete)}",
            type="tool", icon="file-text", show_input=False,
        ) as step:
            resultats = await cl.make_async(rechercher_docs_utilisateur)(requete, user_id)
            step.name = f"Vos documents : {len(resultats)} passage(s) pour {_citer(requete)}"
            step.output = formater_sources(resultats)
        return formater_contexte(resultats)

    if nom == "search_legifrance":
        mots_cles = arguments.get("mots_cles", "")
        nom_code = arguments.get("nom_code")
        cible = f" ({nom_code})" if nom_code else ""
        async with cl.Step(
            name=f"Recherche Légifrance{cible} : {_citer(mots_cles)}",
            type="tool", icon="scale", show_input=False,
        ) as step:
            client = get_legifrance_client()
            resultats = await client.search(mots_cles, nom_code=nom_code)
            step.name = f"Légifrance : {len(resultats)} article(s) pour {_citer(mots_cles)}"
            step.output = "\n".join(
                f"- [{r.get('code', '')} — art. {r.get('num', '')}]"
                f"(https://www.legifrance.gouv.fr/codes/article_lc/{r['id']})"
                f" : {r.get('extrait', '')[:160]}"
                for r in resultats
            ) or "Aucun article trouvé."

        if resultats:
            lignes = []
            for r in resultats:
                lignes.append(
                    f"- ID: {r['id']} | {r.get('code', '')} Art. {r.get('num', '')} — {r.get('extrait', '')[:120]}"
                )
            return "\n".join(lignes)
        return "Aucun article trouve sur Legifrance pour ces mots-cles."

    if nom == "get_article_legifrance":
        article_id = arguments.get("article_id", "")
        nom_code = arguments.get("nom_code", "")
        async with cl.Step(
            name=f"Lecture de l'article sur Légifrance : {article_id}",
            type="tool", icon="book-open", show_input=False,
        ) as step:
            client = get_legifrance_client()
            article = await client.get_article(article_id)

            # Erreur API (500, timeout...)
            if article.get("erreur"):
                step.name = f"Article {article_id} indisponible sur Légifrance"
                step.output = f"Erreur API : {article['erreur']}"
                return f"Erreur lors de la recuperation de l'article {article_id} : {article['erreur']}"

            texte = article.get("texte", "")
            etat = article.get("etat", "")
            num = article.get("num", "")
            url = article.get("url", "")

            # Synchroniser dans ChromaDB
            statut_sync = await cl.make_async(synchroniser_article)(
                article_id, texte, etat,
                meta={"code": nom_code, "num": num, "url": url},
            )

            libelle_etat = "en vigueur" if etat == "VIGUEUR" else etat.lower().replace("_", " ")
            step.name = f"Article {num}" + (f" du {nom_code}" if nom_code else "") + f" ({libelle_etat})"
            step.output = f"[Voir sur Légifrance]({url}) — synchronisation : {statut_sync}\n\n> {texte}"

        parties = [
            f"Article {num}" + (f" ({nom_code})" if nom_code else ""),
            f"Etat: {etat}",
            f"Synchronisation: {statut_sync}",
            f"URL: {url}",
            "",
            texte,
        ]
        return "\n".join(parties)

    return json.dumps({"erreur": f"Outil inconnu : {nom}"})


# ---------------------------------------------------------------------------
# Anthropic streaming with tool calling
# ---------------------------------------------------------------------------

async def _stream_anthropic(history: list[dict], msg: cl.Message) -> str:
    """Boucle de tool calling avec l'API Anthropic.

    1. Envoie le message avec les outils disponibles
    2. Si le LLM demande un outil, l'execute et renvoie le resultat
    3. Repete jusqu'a obtenir une reponse finale
    4. Streame la reponse finale
    """
    messages = list(history)

    while True:
        # Appel non-streaming pour detecter les tool calls
        response = await _anthropic_client.messages.create(
            model=_anthropic_model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=[
                TOOL_RECHERCHE, TOOL_RECHERCHE_COURS,
                TOOL_SEARCH_LEGIFRANCE, TOOL_GET_ARTICLE_LEGIFRANCE,
            ],
        )

        # Verifier si le modele veut utiliser un outil
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        if not tool_use_blocks:
            # Pas de tool call -> extraire la reponse texte et la streamer
            full_response = ""
            for block in response.content:
                if block.type == "text":
                    full_response += block.text

            await msg.stream_token(full_response)
            await msg.send()
            return full_response

        # Construire le message assistant avec tous les blocs
        assistant_content = []
        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        messages.append({"role": "assistant", "content": assistant_content})

        # Executer chaque outil et collecter les resultats
        tool_results = []
        for tool_block in tool_use_blocks:
            resultat = await _executer_outil(tool_block.name, tool_block.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_block.id,
                "content": resultat,
            })

        messages.append({"role": "user", "content": tool_results})


# ---------------------------------------------------------------------------
# Ollama/OpenAI streaming with tool calling
# ---------------------------------------------------------------------------

async def _stream_ollama(history: list[dict], msg: cl.Message) -> str:
    """Streaming Ollama avec support du tool calling (si le modele le supporte).

    Les modeles qui ne supportent pas le tool calling ignorent le parametre
    `tools` et repondent directement (degradation gracieuse).
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + list(history)

    while True:
        # Appel non-streaming pour detecter les tool calls
        response = await _ollama_client.chat.completions.create(
            model=_ollama_model,
            messages=messages,
            max_tokens=2048,
            tools=[
                TOOL_RECHERCHE_OPENAI, TOOL_RECHERCHE_COURS_OPENAI,
                TOOL_SEARCH_LEGIFRANCE_OPENAI, TOOL_GET_ARTICLE_LEGIFRANCE_OPENAI,
            ],
        )

        choice = response.choices[0]

        # Verifier si le modele veut utiliser un outil
        if choice.message.tool_calls:
            # Ajouter le message assistant
            messages.append(choice.message)

            for tool_call in choice.message.tool_calls:
                arguments = json.loads(tool_call.function.arguments)
                resultat = await _executer_outil(tool_call.function.name, arguments)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": resultat,
                })
            continue

        # Pas de tool call -> reponse finale
        full_response = choice.message.content or ""
        await msg.stream_token(full_response)
        await msg.send()
        return full_response


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def stream_response(history: list[dict], msg: cl.Message) -> str:
    """Call the LLM with streaming, updating the Chainlit message in real time."""
    if _use_anthropic:
        return await _stream_anthropic(history, msg)
    return await _stream_ollama(history, msg)
