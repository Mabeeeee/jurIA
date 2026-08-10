"""Affichage des sources dans Chainlit."""

import chainlit as cl

from juria.rag.query_engine import ResultatRecherche


async def afficher_sources(resultats: list[ResultatRecherche]):
    """Cree un Step Chainlit collapsable listant les sources consultees."""
    if not resultats:
        return

    lignes = []
    for i, r in enumerate(resultats, 1):
        ref_parts = []
        if r.metadata.get("source"):
            ref_parts.append(r.metadata["source"])
        if r.metadata.get("chapitre"):
            ref_parts.append(r.metadata["chapitre"])
        if r.metadata.get("section"):
            ref_parts.append(r.metadata["section"])
        if r.metadata.get("article_num"):
            ref_parts.append(r.metadata["article_num"])
        if r.metadata.get("pages"):
            ref_parts.append(f"p. {r.metadata['pages']}")

        reference = " - ".join(ref_parts) if ref_parts else "Source inconnue"
        score_pct = round((1 - r.score) * 100)
        lignes.append(f"- **[{i}]** {reference} (pertinence: {score_pct}%)")

    contenu = "\n".join(lignes)

    async with cl.Step(name="Sources consultees", type="tool") as step:
        step.output = contenu
