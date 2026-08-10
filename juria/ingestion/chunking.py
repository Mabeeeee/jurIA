"""Decoupage structurel des PDFs juridiques."""

import re
from dataclasses import dataclass, field

import fitz  # PyMuPDF

from juria.config import CHUNK_SIZE, CHUNK_OVERLAP


@dataclass
class Chunk:
    """Un morceau de texte avec ses metadonnees hierarchiques."""
    texte: str
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Extraction du texte avec infos de formatage
# ---------------------------------------------------------------------------

def extraire_texte_pdf(chemin_pdf: str) -> list[dict]:
    """Extrait le texte page par page avec la taille de police dominante.

    Retourne une liste de dicts : {page, blocs}
    ou chaque bloc = {texte, taille_police}
    """
    doc = fitz.open(chemin_pdf)
    pages = []

    for num_page, page in enumerate(doc, start=1):
        blocs = []
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

        for block in blocks:
            if block["type"] != 0:  # texte seulement
                continue
            for line in block.get("lines", []):
                texte_ligne = ""
                taille_max = 0
                for span in line.get("spans", []):
                    texte_ligne += span["text"]
                    if span["size"] > taille_max:
                        taille_max = span["size"]
                texte_ligne = texte_ligne.strip()
                if texte_ligne:
                    blocs.append({"texte": texte_ligne, "taille_police": round(taille_max, 1)})

        if blocs:
            pages.append({"page": num_page, "blocs": blocs})

    doc.close()
    return pages


# ---------------------------------------------------------------------------
# Detection de la structure hierarchique
# ---------------------------------------------------------------------------

# Patterns pour les niveaux hierarchiques du droit francais
_PATTERNS = [
    ("partie",   re.compile(r"^(premi[eè]re|deuxi[eè]me|troisi[eè]me|quatri[eè]me|partie)\b", re.IGNORECASE)),
    ("titre",    re.compile(r"^titre\s+", re.IGNORECASE)),
    ("chapitre", re.compile(r"^chapitre\s+", re.IGNORECASE)),
    ("section",  re.compile(r"^section\s+", re.IGNORECASE)),
    ("article",  re.compile(r"^article\s+\w+", re.IGNORECASE)),
]


def detecter_structure(pages: list[dict]) -> list[dict]:
    """Detecte les niveaux hierarchiques dans les blocs extraits.

    Ajoute un champ 'niveau' aux blocs quand un pattern est detecte.
    Utilise aussi la taille de police : les titres sont generalement plus grands.
    """
    if not pages:
        return pages

    # Calculer la taille de police mediane pour reference
    toutes_tailles = [b["taille_police"] for p in pages for b in p["blocs"]]
    if not toutes_tailles:
        return pages
    toutes_tailles.sort()
    taille_mediane = toutes_tailles[len(toutes_tailles) // 2]

    for page_info in pages:
        for bloc in page_info["blocs"]:
            texte = bloc["texte"]
            taille = bloc["taille_police"]

            # Un titre doit etre plus grand que le texte courant
            if taille > taille_mediane * 1.15:
                for niveau, pattern in _PATTERNS:
                    if pattern.search(texte):
                        bloc["niveau"] = niveau
                        bloc["valeur"] = texte
                        break
                else:
                    # Gros texte sans pattern reconnu = titre generique
                    if taille > taille_mediane * 1.4:
                        bloc["niveau"] = "titre_generique"
                        bloc["valeur"] = texte
            else:
                # Meme en taille normale, detecter les articles
                for niveau, pattern in [("article", _PATTERNS[-1][1])]:
                    if pattern.search(texte):
                        bloc["niveau"] = niveau
                        bloc["valeur"] = texte
                        break

    return pages


# ---------------------------------------------------------------------------
# Chunking structurel
# ---------------------------------------------------------------------------

def chunker_document(chemin_pdf: str, source: str, domaine: str = "") -> list[Chunk]:
    """Pipeline complet : extraction -> detection structure -> decoupage en chunks.

    Tente d'abord un decoupage structurel (par sections/articles).
    Si la detection structurelle echoue, applique un fallback par taille.
    """
    pages = extraire_texte_pdf(chemin_pdf)
    if not pages:
        return []

    pages = detecter_structure(pages)

    # Verifier si la detection structurelle a trouve des niveaux
    nb_niveaux = sum(
        1 for p in pages for b in p["blocs"] if "niveau" in b
    )

    if nb_niveaux >= 5:
        return _chunker_structurel(pages, source, domaine)
    else:
        return _chunker_par_taille(pages, source, domaine)


def _chunker_structurel(pages: list[dict], source: str, domaine: str) -> list[Chunk]:
    """Decoupage en chunks bases sur la structure hierarchique detectee."""
    chunks = []
    # Etat courant de la hierarchie
    hierarchie = {
        "partie": "",
        "titre": "",
        "chapitre": "",
        "section": "",
        "article": "",
    }

    texte_courant = ""
    pages_courant = set()
    chunk_index = 0

    for page_info in pages:
        num_page = page_info["page"]
        for bloc in page_info["blocs"]:
            niveau = bloc.get("niveau")

            if niveau and niveau in hierarchie:
                # Sauvegarder le chunk en cours avant de changer de section
                if texte_courant.strip():
                    chunks.append(_creer_chunk(
                        texte_courant.strip(), source, domaine,
                        hierarchie, pages_courant, chunk_index
                    ))
                    chunk_index += 1
                    texte_courant = ""
                    pages_courant = set()

                # Mettre a jour la hierarchie
                hierarchie[niveau] = bloc["valeur"]
                # Reinitialiser les niveaux inferieurs
                niveaux = list(hierarchie.keys())
                idx = niveaux.index(niveau)
                for n in niveaux[idx + 1:]:
                    hierarchie[n] = ""

            texte_courant += bloc["texte"] + "\n"
            pages_courant.add(num_page)

            # Si le chunk courant est trop gros, le decouper
            if len(texte_courant) > CHUNK_SIZE * 2:
                chunks.append(_creer_chunk(
                    texte_courant.strip(), source, domaine,
                    hierarchie, pages_courant, chunk_index
                ))
                chunk_index += 1
                texte_courant = ""
                pages_courant = set()

    # Dernier chunk
    if texte_courant.strip():
        chunks.append(_creer_chunk(
            texte_courant.strip(), source, domaine,
            hierarchie, pages_courant, chunk_index
        ))

    return chunks


def _chunker_par_taille(pages: list[dict], source: str, domaine: str) -> list[Chunk]:
    """Fallback : decoupage par taille fixe avec overlap."""
    # Concatener tout le texte avec marqueurs de page
    texte_complet = ""
    positions_pages = []  # (position_debut, num_page)

    for page_info in pages:
        pos = len(texte_complet)
        positions_pages.append((pos, page_info["page"]))
        for bloc in page_info["blocs"]:
            texte_complet += bloc["texte"] + "\n"

    chunks = []
    debut = 0
    chunk_index = 0

    while debut < len(texte_complet):
        fin = debut + CHUNK_SIZE
        texte_chunk = texte_complet[debut:fin]

        if not texte_chunk.strip():
            debut = fin - CHUNK_OVERLAP
            continue

        # Trouver les pages couvertes par ce chunk
        pages_chunk = set()
        for pos, num_page in positions_pages:
            if pos < fin and (pos + CHUNK_SIZE > debut or pos >= debut):
                pages_chunk.add(num_page)

        if not pages_chunk:
            pages_chunk = {1}

        chunks.append(Chunk(
            texte=texte_chunk.strip(),
            metadata={
                "source": source,
                "domaine": domaine,
                "pages": ",".join(str(p) for p in sorted(pages_chunk)),
                "chunk_index": chunk_index,
            }
        ))
        chunk_index += 1
        debut = fin - CHUNK_OVERLAP

    return chunks


def _creer_chunk(texte: str, source: str, domaine: str,
                 hierarchie: dict, pages: set, index: int) -> Chunk:
    """Cree un Chunk avec les metadonnees hierarchiques."""
    return Chunk(
        texte=texte,
        metadata={
            "source": source,
            "domaine": domaine,
            "partie": hierarchie.get("partie", ""),
            "chapitre": hierarchie.get("chapitre", ""),
            "section": hierarchie.get("section", ""),
            "article_num": hierarchie.get("article", ""),
            "pages": ",".join(str(p) for p in sorted(pages)) if pages else "",
            "chunk_index": index,
        }
    )
