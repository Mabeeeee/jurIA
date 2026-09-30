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
    _anthropic_model = "claude-sonnet-4-6" if is_dev_mode() else "claude-sonnet-4-6" #claude-haiku-4-5-20251001
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

async def _executer_outil(nom: str, arguments: dict, parent_msg: cl.Message) -> str:
    """Execute un outil RAG et affiche un Step Chainlit rattache au message reponse."""
    from juria.rag.query_engine import rechercher, rechercher_docs_utilisateur, formater_contexte
    from juria.rag.callbacks import afficher_sources
    from juria.ingestion.legifrance_client import get_legifrance_client
    from juria.ingestion.legifrance_sync import synchroniser_article

    if nom == "rechercher_base_documentaire":
        requete = arguments.get("requete", "")
        domaine = arguments.get("domaine")
        async with cl.Step(name="Recherche documentaire", type="tool") as step:
            step.input = requete
            step.parent_id = parent_msg.id
            resultats = rechercher(requete, domaine=domaine)
            contexte = formater_contexte(resultats)
            step.output = f"{len(resultats)} resultat(s) trouve(s)"
        await afficher_sources(resultats, parent_msg)
        return contexte

    if nom == "rechercher_mes_cours":
        requete = arguments.get("requete", "")
        user = cl.user_session.get("user")
        user_id = user.identifier if user else "anonymous"
        async with cl.Step(name="Recherche dans vos documents", type="tool") as step:
            step.input = requete
            step.parent_id = parent_msg.id
            resultats = rechercher_docs_utilisateur(requete, user_id)
            contexte = formater_contexte(resultats)
            step.output = f"{len(resultats)} resultat(s) trouve(s)"
        await afficher_sources(resultats, parent_msg)
        return contexte

    if nom == "search_legifrance":
        mots_cles = arguments.get("mots_cles", "")
        nom_code = arguments.get("nom_code")
        async with cl.Step(name="Recherche Legifrance", type="tool") as step:
            step.input = mots_cles
            step.parent_id = parent_msg.id
            client = get_legifrance_client()
            resultats = await client.search(mots_cles, nom_code=nom_code)
            step.output = f"{len(resultats)} article(s) trouve(s)"

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
        async with cl.Step(name="Article Legifrance", type="tool") as step:
            step.input = article_id
            step.parent_id = parent_msg.id

            client = get_legifrance_client()
            article = await client.get_article(article_id)

            texte = article.get("texte", "")
            etat = article.get("etat", "")
            num = article.get("num", "")
            url = article.get("url", "")

            # Synchroniser dans ChromaDB
            statut_sync = synchroniser_article(
                article_id, texte, etat,
                meta={"code": nom_code, "num": num, "url": url},
            )

            step.output = f"Art. {num} — etat: {etat} — sync: {statut_sync}"

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
            await msg.update()
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
            resultat = await _executer_outil(tool_block.name, tool_block.input, msg)
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
                resultat = await _executer_outil(
                    tool_call.function.name, arguments, msg
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": resultat,
                })
            continue

        # Pas de tool call -> reponse finale
        full_response = choice.message.content or ""
        await msg.stream_token(full_response)
        await msg.update()
        return full_response


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def stream_response(history: list[dict], msg: cl.Message) -> str:
    """Call the LLM with streaming, updating the Chainlit message in real time."""
    if _use_anthropic:
        return await _stream_anthropic(history, msg)
    return await _stream_ollama(history, msg)
