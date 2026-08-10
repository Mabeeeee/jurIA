"""LLM backend selection, streaming, and tool calling for jurIA."""

import json
import os

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
import chainlit as cl

from juria.auth import is_dev_mode
from juria.prompts import SYSTEM_PROMPT, TOOL_RECHERCHE, TOOL_RECHERCHE_OPENAI

# ---------------------------------------------------------------------------
# Client & model selection based on environment
# ---------------------------------------------------------------------------

if is_dev_mode():
    _ollama_client = AsyncOpenAI(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        api_key="ollama",
    )
    _ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
else:
    _anthropic_client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    _anthropic_model = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

async def _executer_outil(nom: str, arguments: dict) -> str:
    """Execute un outil RAG et affiche un Step Chainlit."""
    if nom != "rechercher_base_documentaire":
        return json.dumps({"erreur": f"Outil inconnu : {nom}"})

    requete = arguments.get("requete", "")
    domaine = arguments.get("domaine")

    from juria.rag.query_engine import rechercher, formater_contexte
    from juria.rag.callbacks import afficher_sources

    async with cl.Step(name="Recherche documentaire", type="tool") as step:
        step.input = requete
        resultats = rechercher(requete, domaine=domaine)
        contexte = formater_contexte(resultats)
        step.output = f"{len(resultats)} resultat(s) trouve(s)"

    await afficher_sources(resultats)

    return contexte


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
            tools=[TOOL_RECHERCHE],
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
            tools=[TOOL_RECHERCHE_OPENAI],
        )

        choice = response.choices[0]

        # Verifier si le modele veut utiliser un outil
        if choice.message.tool_calls:
            # Ajouter le message assistant
            messages.append(choice.message)

            for tool_call in choice.message.tool_calls:
                arguments = json.loads(tool_call.function.arguments)
                resultat = await _executer_outil(
                    tool_call.function.name, arguments
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
    if is_dev_mode():
        return await _stream_ollama(history, msg)
    return await _stream_anthropic(history, msg)
