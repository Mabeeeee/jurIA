# jurIA

Assistant juridique conversationnel specialise en droit francais, concu pour aider un proche en etudes de droit a comprendre des concepts juridiques, retrouver des articles de loi et preparer ses travaux universitaires.

## Fonctionnalites

- **Chat juridique en streaming** : reponses generees en temps reel avec citation d'articles de loi et de jurisprudence.
- **Double backend LLM** : Claude (Anthropic) en production, Ollama (modele local) en developpement — bascule automatique via variable d'environnement.
- **Historique des conversations** : persistance SQLite des threads et messages, reprise de conversation depuis la barre laterale.
- **Upload de documents** : envoi de fichiers PDF, TXT ou Markdown qui sont stockes par utilisateur pour une future indexation.
- **Authentification** : login par mot de passe (bcrypt) en production ; profil developpeur automatique en mode dev.
- **Starters pre-configures** : questions d'exemple cliquables pour guider l'utilisateur (responsabilite contractuelle, dol/erreur, prescription penale).

## Stack technique

| Composant | Choix | Detail |
|---|---|---|
| Interface chat | [Chainlit](https://chainlit.io) | UI conversationnelle avec historique, reprise de thread, upload de fichiers |
| LLM production | [Claude](https://anthropic.com) (claude-sonnet-4-6) | Via le SDK `anthropic` (AsyncAnthropic) |
| LLM developpement | [Ollama](https://ollama.com) (Mistral par defaut) | Via le SDK `openai` pointant sur l'API locale Ollama |
| Persistance | SQLite + aiosqlite | Base unique `data/juria_app.db` pour threads, steps, users, documents |
| Authentification | bcrypt | Hachage des mots de passe, stockage en SQLite |
| Corpus (a venir) | Legifrance (API PISTE / open data) | Pipeline d'ingestion et indexation RAG prevu |

## Arborescence

```
jurIA/
├── app.py                          # Point d'entree Chainlit : data layer, auth, starters, handlers
│
├── juria/                          # Package metier
│   ├── chat.py                     # Selection du backend LLM et streaming des reponses
│   ├── prompts.py                  # System prompt du personnage jurIA
│   ├── auth.py                     # Authentification : bcrypt, gestion users SQLite, mode dev
│   ├── user_docs.py                # Upload et stockage de documents utilisateur
│   ├── config.py                   # (reserve) lecture des env vars, constantes
│   ├── ingestion/                  # (a venir) pipeline d'ingestion Legifrance
│   │   ├── legifrance_client.py    # Appels API PISTE (OAuth2 + requetes)
│   │   ├── chunking.py            # Decoupage hierarchique des textes de loi
│   │   └── build_index.py         # Script d'indexation (hors runtime Chainlit)
│   └── rag/                        # (a venir) retrieval-augmented generation
│       ├── vector_store.py         # Store vectoriel
│       ├── query_engine.py         # Retriever + query engine
│       └── callbacks.py            # Callbacks d'integration Chainlit
│
├── scripts/
│   └── create_user.py              # CLI pour creer un compte utilisateur
│
├── data/
│   ├── juria_app.db                # Base SQLite (threads, steps, users, documents)
│   ├── raw/                        # Corpus brut telecharge (gitignored)
│   └── user_docs/                  # Documents uploades par utilisateur
│
├── tests/
│   ├── test_chunking.py
│   └── test_query_engine.py
│
├── .chainlit/
│   └── config.toml                 # Configuration Chainlit (UI, upload, session)
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

### Dependances

```
chainlit>=2.0
anthropic
openai
python-dotenv
aiosqlite
sqlalchemy[asyncio]
bcrypt
```

## Configuration

Copier `.env.example` en `.env` et renseigner les valeurs :

```bash
cp .env.example .env
```

| Variable | Description | Requis |
|---|---|---|
| `JURIA_ENV` | `dev` (Ollama local) ou `prod` (Claude API) | Non (defaut : `dev`) |
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

### Chat (`juria/chat.py`)

Le module selectionne le backend LLM selon `JURIA_ENV` :
- **Dev** : `AsyncOpenAI` pointe sur Ollama (`http://localhost:11434/v1`), modele configurable.
- **Prod** : `AsyncAnthropic` avec Claude claude-sonnet-4-6.

Les reponses sont streamees token par token vers l'interface Chainlit.

### Authentification (`juria/auth.py`)

- **Mode dev** (`JURIA_ENV=dev`) : un `header_auth_callback` retourne automatiquement un utilisateur `dev`, sans ecran de login. Les conversations sont persistees et visibles dans l'historique.
- **Mode prod** : `password_auth_callback` avec verification bcrypt contre la table `users` en SQLite.

### Persistance (`app.py`)

Le `SQLAlchemyDataLayer` de Chainlit est configure avec SQLite (`data/juria_app.db`). Les tables (`users`, `threads`, `steps`, `elements`, `feedbacks`) sont creees automatiquement au demarrage si elles n'existent pas.

### Upload de documents (`juria/user_docs.py`)

Les fichiers PDF, TXT et Markdown envoyes dans le chat sont :
1. Copies dans `data/user_docs/<user_id>/`
2. Enregistres dans la table `user_documents` (metadonnees)

L'indexation pour la recherche RAG n'est pas encore implementee.

### System prompt (`juria/prompts.py`)

jurIA se presente comme un assistant juridique pedagogique : il cite les articles de loi, signale ses incertitudes, et rappelle qu'il ne remplace pas un avocat.

## Statut du projet

- [x] Interface conversationnelle Chainlit
- [x] Streaming des reponses (Claude + Ollama)
- [x] Authentification par mot de passe (prod) / auto-login (dev)
- [x] Persistance de l'historique des conversations (SQLite)
- [x] Reprise de conversation depuis la sidebar
- [x] Upload et stockage de documents utilisateur
- [x] Starters pre-configures
- [ ] Pipeline d'ingestion Legifrance (API PISTE)
- [ ] Chunking hierarchique des textes de loi
- [ ] Indexation vectorielle et recherche RAG
- [ ] Deploiement (Railway / Render)
- [ ] CI/CD (GitHub Actions)
