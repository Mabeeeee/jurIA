"""Script d'ingestion : decoupe un PDF et l'indexe dans ChromaDB.

Usage :
    python -m juria.ingestion.build_index --pdf <chemin> --domaine <domaine>
"""

import argparse
import hashlib
import os
import sys

from juria.config import get_embedding_model
from juria.ingestion.chunking import chunker_document
from juria.rag.vector_store import get_vector_store


def _generer_id(source: str, index: int) -> str:
    """Genere un ID deterministe pour un chunk."""
    h = hashlib.md5(f"{source}:{index}".encode()).hexdigest()[:12]
    return f"{source}_{index}_{h}"


def ingerer_pdf(chemin_pdf: str, domaine: str):
    """Pipeline complet d'ingestion d'un PDF."""
    source = os.path.basename(chemin_pdf)

    print(f"[1/4] Decoupage de {source}...")
    chunks = chunker_document(chemin_pdf, source=source, domaine=domaine)
    if not chunks:
        print("Aucun chunk extrait. Verifiez le PDF.")
        sys.exit(1)
    print(f"       {len(chunks)} chunks crees.")

    print("[2/4] Chargement du modele d'embeddings...")
    modele = get_embedding_model()

    print("[3/4] Encodage des chunks par batch...")
    textes = [c.texte for c in chunks]
    embeddings = modele.encode(textes, show_progress_bar=True, batch_size=32)
    embeddings = [e.tolist() for e in embeddings]

    print("[4/4] Insertion dans ChromaDB...")
    store = get_vector_store()

    # Supprimer les anciens chunks de la meme source (idempotence)
    try:
        store.supprimer_par_source(source)
        print(f"       Anciens chunks de '{source}' supprimes.")
    except Exception:
        pass  # Pas d'anciens chunks

    ids = [_generer_id(source, i) for i in range(len(chunks))]
    metadatas = [c.metadata for c in chunks]
    documents = textes

    # Insertion par batch de 500 (limite ChromaDB)
    batch_size = 500
    for i in range(0, len(ids), batch_size):
        store.ajouter(
            ids=ids[i:i + batch_size],
            embeddings=embeddings[i:i + batch_size],
            documents=documents[i:i + batch_size],
            metadatas=metadatas[i:i + batch_size],
        )

    print(f"Ingestion terminee. {store.compter()} chunks dans la base.")


def main():
    parser = argparse.ArgumentParser(description="Ingestion de documents PDF pour jurIA")
    parser.add_argument("--pdf", required=True, help="Chemin vers le fichier PDF")
    parser.add_argument("--domaine", required=True, help="Domaine juridique (ex: procedure_fiscale)")
    args = parser.parse_args()

    if not os.path.isfile(args.pdf):
        print(f"Fichier introuvable : {args.pdf}")
        sys.exit(1)

    ingerer_pdf(args.pdf, args.domaine)


if __name__ == "__main__":
    main()
