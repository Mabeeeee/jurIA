"""Moteur de recherche RAG : encode la requete et interroge ChromaDB."""

from dataclasses import dataclass
from datetime import date, timedelta

from juria.config import get_embedding_model, DEFAULT_TOP_K, SCORE_THRESHOLD, FRAICHEUR_JOURS
from juria.rag.vector_store import get_vector_store, get_user_vector_store


@dataclass
class ResultatRecherche:
    """Un resultat de recherche avec son score et ses metadonnees."""
    texte: str
    score: float  # distance cosinus (0 = identique, 2 = oppose)
    metadata: dict


def rechercher(requete: str, domaine: str | None = None,
               top_k: int = DEFAULT_TOP_K) -> list[ResultatRecherche]:
    """Encode la requete, interroge ChromaDB, filtre par score."""
    modele = get_embedding_model()
    query_embedding = modele.encode(requete).tolist()

    filtre = None
    if domaine:
        filtre = {"domaine": domaine}

    store = get_vector_store()
    resultats_bruts = store.rechercher(query_embedding, top_k=top_k, filtre=filtre)

    resultats = []
    documents = resultats_bruts.get("documents", [[]])[0]
    distances = resultats_bruts.get("distances", [[]])[0]
    metadatas = resultats_bruts.get("metadatas", [[]])[0]

    for doc, dist, meta in zip(documents, distances, metadatas):
        if dist <= SCORE_THRESHOLD:
            resultats.append(ResultatRecherche(
                texte=doc,
                score=dist,
                metadata=meta,
            ))

    return resultats


def rechercher_docs_utilisateur(requete: str, username: str,
                                top_k: int = DEFAULT_TOP_K) -> list[ResultatRecherche]:
    """Recherche dans les documents uploades par l'utilisateur."""
    modele = get_embedding_model()
    query_embedding = modele.encode(requete).tolist()

    store = get_user_vector_store(username)
    resultats_bruts = store.rechercher(query_embedding, top_k=top_k)

    resultats = []
    documents = resultats_bruts.get("documents", [[]])[0]
    distances = resultats_bruts.get("distances", [[]])[0]
    metadatas = resultats_bruts.get("metadatas", [[]])[0]

    for doc, dist, meta in zip(documents, distances, metadatas):
        if dist <= SCORE_THRESHOLD:
            resultats.append(ResultatRecherche(
                texte=doc,
                score=dist,
                metadata=meta,
            ))

    return resultats


def formater_contexte(resultats: list[ResultatRecherche]) -> str:
    """Formate les resultats en texte pour injection dans le prompt LLM."""
    if not resultats:
        return "AUCUN_RESULTAT_PERTINENT"

    seuil_fraicheur = (date.today() - timedelta(days=FRAICHEUR_JOURS)).isoformat()

    parties = []
    for i, r in enumerate(resultats, 1):
        if r.metadata.get("source_type") == "legifrance":
            ref_parts = []
            legi_id = r.metadata.get("legi_id", "")
            if legi_id:
                ref_parts.append(f"Legifrance: {legi_id}")
            if r.metadata.get("code"):
                ref_parts.append(f"Code: {r.metadata['code']}")
            if r.metadata.get("num"):
                ref_parts.append(f"Art. {r.metadata['num']}")
            ref_parts.append(f"Source: {r.metadata.get('source', 'legifrance')}")
            date_verif = r.metadata.get("date_verification", "")
            if date_verif:
                ref_parts.append(f"Verifie: {date_verif}")

            reference = " | ".join(ref_parts)

            tag = ""
            if date_verif and date_verif < seuil_fraicheur:
                tag = " [A_REVERIFIER]"

            parties.append(f"[{i}] ({reference}){tag}\n{r.texte}")
        else:
            ref_parts = []
            if r.metadata.get("source"):
                ref_parts.append(f"Source: {r.metadata['source']}")
            if r.metadata.get("chapitre"):
                ref_parts.append(f"Chapitre: {r.metadata['chapitre']}")
            if r.metadata.get("section"):
                ref_parts.append(f"Section: {r.metadata['section']}")
            if r.metadata.get("article_num"):
                ref_parts.append(f"Article: {r.metadata['article_num']}")
            if r.metadata.get("pages"):
                ref_parts.append(f"Pages: {r.metadata['pages']}")

            reference = " | ".join(ref_parts) if ref_parts else "Source inconnue"
            parties.append(f"[{i}] ({reference})\n{r.texte}")

    return "\n\n---\n\n".join(parties)
