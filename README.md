# jurIA

Assistant RAG juridique — projet personnel destiné à un proche en études de droit, pour l'aider à retrouver des articles de loi pertinents dans le cadre de ses dissertations.

## Objectif

À partir d'un corpus juridique structuré (Légifrance), l'application permet d'interroger en langage naturel une base d'articles de loi et de retourner les sources brutes correspondantes — pas un résumé généré, mais les articles eux-mêmes, pour permettre une vérification humaine systématique. Le droit est un domaine sensible aux hallucinations : la fiabilité de la source prime sur la fluidité de la réponse.

## Stack technique

| Composant | Choix | Pourquoi |
|---|---|---|
| Interface chat | [Chainlit](https://chainlit.io) | Persistance native des conversations (historique, reprise de thread), absente de Streamlit |
| Orchestration RAG | [LlamaIndex](https://www.llamaindex.ai) | Librairie Python open-source et gratuite ; seul coût réel = l'API du LLM |
| LLM | Claude (Anthropic) | Via `llama-index-llms-anthropic` |
| Stockage vectoriel | DuckDB + extension VSS | Un seul fichier `.duckdb`, portable, versionnable, sans service tiers — même philosophie que `ragnar` en R |
| Corpus | Légifrance (API PISTE ou open data) | Périmètre de droit ciblé à définir, pas tout Légifrance |
| Déploiement | Railway / Render | PaaS simple, coût faible, volume persistant à configurer explicitement |
| CI/CD | GitHub Actions | Lint + tests sur chaque push/PR, déploiement conditionné à la réussite de la CI |

## Points d'attention

- **Chunking hiérarchique** : le découpage du corpus doit respecter la structure Livre > Titre > Chapitre > Article plutôt qu'un découpage naïf par taille de texte.
- **Sources brutes affichées** : chaque réponse doit pointer vers l'article de loi original, pas seulement une synthèse.
- **Base DuckDB non versionnée** : régénérée via `juria/ingestion/build_index.py`, pas commitée dans Git (fichier binaire volumineux et reconstructible).

## Arborescence

```
jurIA/
├── .env                        # clé API Anthropic, gitignored
├── .env.example                # template sans les valeurs, versionné
├── .gitignore
├── requirements.txt
├── pyproject.toml              # config ruff/black/pytest
├── README.md
├── chainlit.md                 # message d'accueil affiché dans l'UI Chainlit
├── .chainlit/
│   └── config.toml             # généré par `chainlit init`, versionné
│
├── app.py                      # point d'entrée Chainlit (@cl.on_chat_start, @cl.on_message)
│
├── juria/                      # package métier — logique testable hors Chainlit
│   ├── __init__.py
│   ├── config.py                # lecture des env vars, constantes (modèle, chemins, top_k...)
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── legifrance_client.py # appels API PISTE (OAuth2 + requêtes)
│   │   ├── chunking.py           # découpage hiérarchique Livre > Titre > Chapitre > Article
│   │   └── build_index.py        # script d'indexation, lancé à part (pas au runtime Chainlit)
│   └── rag/
│       ├── __init__.py
│       ├── vector_store.py       # setup DuckDBVectorStore + extension VSS
│       ├── query_engine.py       # retriever + query engine LlamaIndex
│       └── callbacks.py          # LlamaIndexCallbackHandler pour l'intégration Chainlit
│
├── data/
│   ├── raw/                     # corpus brut téléchargé (gitignored)
│   └── legal_index.duckdb       # base vectorielle, régénérée, non versionnée
│
├── tests/
│   ├── __init__.py
│   ├── test_chunking.py
│   └── test_query_engine.py
│
└── .github/
    └── workflows/
        ├── ci.yml                # lint + tests sur push/PR
        └── deploy.yml            # déploiement conditionné à la réussite de ci.yml
```

## Installation

```bash
pip install chainlit llama-index llama-index-llms-anthropic \
    llama-index-vector-stores-duckdb duckdb python-dotenv \
    llama-index-embeddings-huggingface requests
```

## Lancement (mode dev)

```bash
chainlit run app.py -w
```

## Statut

Premiers pas en cours avec Chainlit seul (chat basique via l'API Anthropic, sans RAG). Le pipeline d'ingestion Légifrance et l'indexation DuckDB restent à construire.
