"""Affichage des sources dans Chainlit."""

from juria.rag.query_engine import ResultatRecherche


def formater_sources(resultats: list[ResultatRecherche]) -> str:
    """Liste markdown des sources consultees, affichee dans le Step repliable
    de la recherche."""
    if not resultats:
        return "Aucune source trouvee."

    lignes = []
    for i, r in enumerate(resultats, 1):
        score_pct = round((1 - r.score) * 100)

        if r.metadata.get("source_type") == "legifrance":
            legi_id = r.metadata.get("legi_id", "")
            date_verif = r.metadata.get("date_verification", "")
            url = r.metadata.get("url", "")
            label = f"Legifrance {legi_id}"
            if r.metadata.get("num"):
                label = f"Art. {r.metadata['num']} ({legi_id})"
            if date_verif:
                label += f" — verifie le {date_verif}"
            if url:
                lignes.append(f"- **[{i}]** [{label}]({url}) (pertinence: {score_pct}%)")
            else:
                lignes.append(f"- **[{i}]** {label} (pertinence: {score_pct}%)")
        else:
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
            lignes.append(f"- **[{i}]** {reference} (pertinence: {score_pct}%)")

    return "\n".join(lignes)
