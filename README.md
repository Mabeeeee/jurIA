# jurIA

Assistant juridique conversationnel specialise en droit francais, concu pour aider un proche en etudes de droit a comprendre des concepts juridiques, retrouver des articles de loi et preparer ses travaux universitaires.

## Fonctionnalites

- **Chat juridique en streaming** : reponses generees en temps reel avec citation d'articles de loi et de jurisprudence.
- **RAG (Retrieval-Augmented Generation)** : recherche automatique dans une base documentaire vectorielle (ChromaDB) avant de repondre, avec affichage des sources consultees.
- **Tool calling** : le LLM decide quand interroger la base documentaire via des outils declares (format Anthropic et OpenAI). Les etapes de recherche apparaissent comme encarts collapsables rattaches a la reponse.
- **Double backend LLM** : Claude (Anthropic) en production ou petite config, Ollama (modele local) en developpement — bascule automatique via variable d'environnement.
- **Historique des conversations** : persistance SQLite des threads et messages, reprise de conversation depuis la barre laterale.
- **Authentification** : login par mot de passe (bcrypt) en production ; profil developpeur automatique en mode dev.
- **Starters pre-configures** : questions d'exemple cliquables pour guider l'utilisateur (responsabilite contractuelle, dol/erreur, prescription penale).

## Stack technique

| Composant | Choix | Detail |
|---|---|---|
| Interface chat | [Chainlit](https://chainlit.io) | UI conversationnelle avec historique, reprise de thread |
| LLM production | [Claude](https://anthropic.com) (claude-sonnet-4-6) | Via le SDK `anthropic` (AsyncAnthropic) |
| LLM developpement | [Ollama](https://ollama.com) (Mistral par defaut) | Via le SDK `openai` pointant sur l'API locale Ollama |
| Embeddings | [Solon](https://huggingface.co/OrdalieTech/Solon-embeddings-large-0.1) | Modele francais 1024 dimensions |
| Base vectorielle | [ChromaDB](https://www.trychroma.com/) | Stockage et recherche par similarite cosinus |
| Persistance | SQLite + aiosqlite | Base `data/juria_app.db` pour threads, steps, users |
| Authentification | bcrypt | Hachage des mots de passe, stockage en SQLite |

## Arborescence

```
jurIA/
├── app.py                          # Point d'entree Chainlit : data layer, auth, starters, handlers
│
├── juria/                          # Package metier
│   ├── chat.py                     # Selection du backend LLM, streaming, tool calling
│   ├── prompts.py                  # System prompt et definitions d'outils (Anthropic + OpenAI)
│   ├── auth.py                     # Authentification : bcrypt, gestion users SQLite, mode dev
│   ├── user_docs.py                # Upload et stockage de documents utilisateur
│   ├── config.py                   # Embeddings, parametres RAG (top_k, seuil, chunking)
│   ├── ingestion/                  # Pipeline d'ingestion de corpus
│   │   ├── legifrance_client.py    # (a venir) Appels API PISTE (OAuth2 + requetes)
│   │   ├── chunking.py             # Decoupage hierarchique des textes de loi
│   │   └── build_index.py          # Script d'indexation dans ChromaDB
│   └── rag/                        # Retrieval-augmented generation
│       ├── vector_store.py         # Interface ChromaDB (collections principale + par utilisateur)
│       ├── query_engine.py         # Encodage requete, recherche, formatage du contexte
│       └── callbacks.py            # Affichage des sources dans Chainlit (Steps)
│
├── scripts/
│   └── create_user.py              # CLI pour creer un compte utilisateur
│
├── data/
│   ├── juria_app.db                # Base SQLite (threads, steps, users)
│   ├── vectorstore/                # Collections ChromaDB (gitignored)
│   ├── raw/                        # Corpus brut telecharge (gitignored)
│   └── user_docs/                  # Documents uploades par utilisateur
│
├── tests/
│   ├── test_chunking.py
│   └── test_query_engine.py
│
├── .chainlit/
│   └── config.toml                 # Configuration Chainlit (UI, session)
├── .env.example                    # Template des variables d'environnement
├── requirements.txt                # Dependances Python
└── chainlit.md                     # Message d'accueil affiche dans l'UI
```

## Installation

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

pip install -r requirements.txt
```

## Configuration

Copier `.env.example` en `.env` et renseigner les valeurs :

```bash
cp .env.example .env
```

| Variable | Description | Requis |
|---|---|---|
| `JURIA_ENV` | `dev` (Ollama local) ou `prod` (Claude API) | Non (defaut : `dev`) |
| `JURIA_PETITE_CONFIG` | `true` pour forcer Claude meme en dev (si API key presente) | Non (defaut : `false`) |
| `ANTHROPIC_API_KEY` | Cle API Anthropic | Oui en prod |
| `CHAINLIT_AUTH_SECRET` | Secret pour les sessions Chainlit | Oui en prod |
| `OLLAMA_MODEL` | Modele Ollama a utiliser | Non (defaut : `mistral`) |
| `OLLAMA_BASE_URL` | URL de l'API Ollama | Non (defaut : `http://localhost:11434/v1`) |

## Lancement

### Mode developpement (Ollama)

Prerequis : [Ollama](https://ollama.com) installe et lance avec un modele disponible (`ollama pull mistral`).

```bash
chainlit run app.py -w
```

L'application demarre sur `http://localhost:8000` avec un profil developpeur automatique (pas de login requis).

### Mode production (Claude)

```bash
JURIA_ENV=prod chainlit run app.py
```

Un ecran de login s'affiche. Creer un utilisateur au prealable :

```bash
python scripts/create_user.py --username alice --password motdepasse --display-name "Alice D."
```

## Architecture

### Chat et tool calling (`juria/chat.py`)

Le module selectionne le backend LLM selon `JURIA_ENV` :
- **Dev** : `AsyncOpenAI` pointe sur Ollama (`http://localhost:11434/v1`), modele configurable.
- **Prod / petite config** : `AsyncAnthropic` avec Claude claude-sonnet-4-6.

Le LLM dispose d'outils de recherche declares en tool calling. Quand il decide d'interroger la base, un `cl.Step` s'affiche comme encart collapsable rattache au message de reponse, montrant la requete et les sources trouvees.

### RAG (`juria/rag/`)

- **vector_store.py** : interface ChromaDB avec une collection principale (corpus juridique) et des collections par utilisateur (documents uploades).
- **query_engine.py** : encode la requete avec Solon, interroge ChromaDB, filtre par seuil de distance cosinus (0.3), formate le contexte pour le prompt LLM.
- **callbacks.py** : affiche les sources consultees dans un Step Chainlit collapsable.

### Ingestion (`juria/ingestion/`)

- **chunking.py** : decoupage hierarchique des textes de loi en chunks avec metadonnees (source, chapitre, section, article).
- **build_index.py** : script d'indexation qui encode les chunks et les insere dans ChromaDB.

### Authentification (`juria/auth.py`)

- **Mode dev** (`JURIA_ENV=dev`) : un `header_auth_callback` retourne automatiquement un utilisateur `dev`, sans ecran de login.
- **Mode prod** : `password_auth_callback` avec verification bcrypt contre la table `users` en SQLite.

### Persistance (`app.py`)

Le `SQLAlchemyDataLayer` de Chainlit est configure avec SQLite (`data/juria_app.db`). Les tables (`users`, `threads`, `steps`, `elements`, `feedbacks`) sont creees automatiquement au demarrage.

## Statut du projet

- [x] Interface conversationnelle Chainlit
- [x] Streaming des reponses (Claude + Ollama)
- [x] Tool calling (Anthropic + OpenAI/Ollama)
- [x] RAG : base vectorielle ChromaDB + embeddings Solon
- [x] Recherche dans la base documentaire avec affichage des sources
- [x] Authentification par mot de passe (prod) / auto-login (dev)
- [x] Persistance de l'historique des conversations (SQLite)
- [x] Reprise de conversation depuis la sidebar
- [x] Pipeline d'ingestion et chunking hierarchique
- [x] Starters pre-configures
- [ ] Interrogation temps reel de l'API Legifrance (fallback quand la base locale ne suffit pas)
- [ ] Deploiement (Railway / Render)
- [ ] CI/CD (GitHub Actions)
