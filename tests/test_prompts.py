"""Tests de coherence du prompt systeme et des outils (juria/prompts.py).

Chaque outil est declare deux fois : format Anthropic et format OpenAI/Ollama.
Ces tests garantissent que les deux versions ne divergent pas.
"""

import pytest

from juria import prompts

PAIRES = [
    (prompts.TOOL_RECHERCHE, prompts.TOOL_RECHERCHE_OPENAI),
    (prompts.TOOL_RECHERCHE_COURS, prompts.TOOL_RECHERCHE_COURS_OPENAI),
    (prompts.TOOL_SEARCH_LEGIFRANCE, prompts.TOOL_SEARCH_LEGIFRANCE_OPENAI),
    (prompts.TOOL_GET_ARTICLE_LEGIFRANCE, prompts.TOOL_GET_ARTICLE_LEGIFRANCE_OPENAI),
]
NOMS = [anthropic["name"] for anthropic, _ in PAIRES]


@pytest.mark.parametrize("anthropic, openai", PAIRES, ids=NOMS)
def test_formats_anthropic_et_openai_equivalents(anthropic, openai):
    assert openai["type"] == "function"
    fonction = openai["function"]
    assert fonction["name"] == anthropic["name"]
    assert fonction["description"] == anthropic["description"]
    assert fonction["parameters"] == anthropic["input_schema"]


@pytest.mark.parametrize("anthropic, _", PAIRES, ids=NOMS)
def test_schema_valide(anthropic, _):
    schema = anthropic["input_schema"]
    assert schema["type"] == "object"
    assert anthropic["description"]
    assert set(schema["required"]) <= set(schema["properties"])


def test_noms_des_outils():
    assert NOMS == [
        "rechercher_base_documentaire",
        "rechercher_mes_cours",
        "search_legifrance",
        "get_article_legifrance",
    ]


@pytest.mark.parametrize("nom", NOMS)
def test_chaque_outil_est_mentionne_dans_le_prompt_systeme(nom):
    assert nom in prompts.SYSTEM_PROMPT


@pytest.mark.parametrize("marqueur", ["AUCUN_RESULTAT_PERTINENT", "[A_REVERIFIER]", "VIGUEUR"])
def test_marqueurs_produits_par_le_code_connus_du_prompt(marqueur):
    # formater_contexte et synchroniser_article produisent ces marqueurs :
    # le prompt doit expliquer au LLM comment reagir
    assert marqueur in prompts.SYSTEM_PROMPT
