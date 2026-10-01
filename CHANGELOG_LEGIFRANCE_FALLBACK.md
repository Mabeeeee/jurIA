# Fallback Legifrance avec enrichissement automatique de la base

## Vue d'ensemble

Pipeline complet : base locale d'abord, fallback Legifrance par mots-cles, recuperation du texte integral, synchronisation automatique dans ChromaDB, controle de fraicheur des articles.

---

## Fichiers modifies

### `juria/config.py`

- Ajout de la constante `FRAICHEUR_JOURS = 180` : nombre de jours apres lequel un article Legifrance synchronise est marque `[A_REVERIFIER]` dans le contexte injecte au LLM.

### `juria/ingestion/legifrance_client.py`

Reecrit complet. L'ancien module (fonctions libres, `httpx.AsyncClient` ephemere, recherche `EXACTE` uniquement) est remplace par une classe `LegifranceClient` :

- **Token OAuth2** : cache en memoire, renouvellement automatique 60s avant expiration.
- **httpx.AsyncClient** : singleton lazy, recree si ferme (`is_closed`).
- **Retry 401** : un seul retry (invalidation du token puis nouvel appel).
- **`search(mots_cles, nom_code=None)`** :
  - Fond `CODE_DATE`, filtres `DATE_VERSION` (`singleDate` = aujourd'hui) + `NOM_CODE` optionnel.
  - Essaie `TOUS_LES_MOTS_DANS_UN_CHAMP`, puis fallback `UN_DES_MOTS` si zero resultats.
  - `pageSize=8`, retourne `list[dict]` avec cles `{id, code, num, extrait}`.
- **`get_article(article_id)`** :
  - POST `/consult/getArticle`.
  - Parse HTML vers texte brut via `re.sub(r'<[^>]+>', '', html)`.
  - Retourne `{texte, etat, num, url}`.
- **URLs** : lues via `PISTE_OAUTH_URL` et `PISTE_API_BASE` (defaut : sandbox PISTE).
- **Credentials** : noms inchanges (`LEGIFRANCE_CLIENT_ID`, `LEGIFRANCE_CLIENT_SECRET`).
- **Singleton** : `get_legifrance_client()` au niveau module.
- `ResultatLegifrance` et `formater_contexte_legifrance()` conserves pour retrocompat (inutilises par le nouveau code, supprimables a terme).

### `juria/rag/vector_store.py`

- Ajout de la methode `upsert(ids, embeddings, documents, metadatas)` sur `VectorStore`. Delegue a `collection.upsert()` de ChromaDB (atomique, pas de race condition delete+add).

### `juria/rag/query_engine.py`

`formater_contexte()` enrichi :

- **Liste vide** : retourne la chaine `AUCUN_RESULTAT_PERTINENT` (signal explicite pour le system prompt, declencheur du fallback Legifrance).
- **Articles Legifrance** (`source_type == "legifrance"`) : affiche `legi_id`, code, numero, source, `date_verification`. Ajoute le tag `[A_REVERIFIER]` si `date_verification` depasse `FRAICHEUR_JOURS`.
- **Articles PDF** (pas de `source_type`) : formatage inchange.

### `juria/prompts.py`

**Outils supprimes** : `TOOL_LEGIFRANCE`, `TOOL_LEGIFRANCE_OPENAI`.

**Nouveaux outils** (formats Anthropic + OpenAI) :

| Outil | Params | Description |
|-------|--------|-------------|
| `search_legifrance` | `mots_cles` (required), `nom_code` (optional) | Recherche lexicale dans les codes en vigueur. Le LLM doit formuler 2-4 termes juridiques, pas la question brute. |
| `get_article_legifrance` | `article_id` (required), `nom_code` (optional) | Texte integral + etat actuel. A appeler avant de citer un article ET pour re-verifier les `[A_REVERIFIER]`. |

**System prompt** : strategie de fallback declarative :

1. Toujours `rechercher_base_documentaire` en premier.
2. Evaluer les resultats.
3. Articles `[A_REVERIFIER]` → `get_article_legifrance` avant de citer.
4. Base insuffisante → `search_legifrance` (3 tentatives max, mots-cles differents).
5. Avant de citer → `get_article_legifrance` pour le texte complet.
6. Ne jamais citer un article non obtenu via un outil.
7. Articles non-VIGUEUR signales explicitement.

### `juria/chat.py`

`_executer_outil()` mis a jour :

| Outil | Logique |
|-------|---------|
| `rechercher_base_documentaire` | Inchange (utilise `formater_contexte()` enrichi). |
| `rechercher_mes_cours` | Inchange. |
| `search_legifrance` | Appelle `LegifranceClient.search()`, formate les resultats (id, code, num, extrait). Step Chainlit "Recherche Legifrance". |
| `get_article_legifrance` | Appelle `LegifranceClient.get_article()`, puis `synchroniser_article()` pour enrichir ChromaDB. Retourne texte, etat, statut sync, URL. Step Chainlit "Article Legifrance". |
| `rechercher_legifrance` (ancien) | Supprime. |

Listes d'outils mises a jour dans `_stream_anthropic` et `_stream_ollama`.

### `juria/rag/callbacks.py`

`afficher_sources()` : quand `source_type == "legifrance"`, affiche le numero d'article, le `legi_id`, la `date_verification`, et un lien cliquable vers Legifrance.

### `.env.example`

Ajout de :

```
PISTE_OAUTH_URL=https://sandbox-oauth.piste.gouv.fr/api/oauth/token
PISTE_API_BASE=https://sandbox-api.piste.gouv.fr/dila/legifrance/lf-engine-app
```

`LEGIFRANCE_CLIENT_ID` et `LEGIFRANCE_CLIENT_SECRET` conserves (noms inchanges).

---

## Fichier cree

### `juria/ingestion/legifrance_sync.py`

Fonction `synchroniser_article(article_id, texte, etat, meta)` :

| Cas | Action | Retour |
|-----|--------|--------|
| `etat != "VIGUEUR"` et present dans ChromaDB | `collection.delete()` | `"retire"` |
| `etat != "VIGUEUR"` et absent | Rien | `"ignore"` |
| `etat == "VIGUEUR"`, absent de ChromaDB | Embedding + `upsert()` | `"ajoute"` |
| `etat == "VIGUEUR"`, texte identique | `upsert()` (met a jour `date_verification`) | `"verifie"` |
| `etat == "VIGUEUR"`, texte different | Embedding + `upsert()` | `"mis_a_jour"` |

Metadonnees stockees : `legi_id`, `code`, `num`, `url`, `etat`, `source_type="legifrance"`, `source="legifrance_fallback"`, `date_ajout`, `date_verification`.

---

## Fichiers non modifies

- `app.py`
- `juria/ingestion/build_index.py`
- `juria/ingestion/chunking.py`
- `juria/auth.py`
- `juria/user_docs.py`
- `requirements.txt` (httpx deja present)

---

## Flux type

```
Etudiant: "Quel est le delai de restitution du depot de garantie ?"

1. LLM appelle rechercher_base_documentaire("depot de garantie restitution")
2. Base locale → AUCUN_RESULTAT_PERTINENT
3. LLM appelle search_legifrance("depot garantie restitution", nom_code="Code civil")
4. API retourne LEGIARTI000006442847 (art. 22), LEGIARTI000006442853 (art. 22-1)...
5. LLM appelle get_article_legifrance("LEGIARTI000006442847", "Loi n° 89-462")
6. → texte integral recupere, etat=VIGUEUR, synchronise dans ChromaDB (statut: ajoute)
7. LLM repond avec le texte de l'article et la reference
8. Question identique plus tard → servie directement par la base locale
```

---

## Verification

1. Demarrer l'app avec credentials PISTE sandbox.
2. Question couverte par la base → `rechercher_base_documentaire` uniquement.
3. Question hors base → `search_legifrance` → `get_article_legifrance` → article dans ChromaDB.
4. Meme question une 2e fois → servie par la base locale.
5. Steps Chainlit visibles pour chaque outil.
6. Article avec `date_verification` > 180j → marqueur `[A_REVERIFIER]` dans le contexte.

---

## Tests effectues (2026-10-01 — sandbox PISTE)

### Endpoint `/search` — KO puis corrige

Premier constat : `/search` renvoyait systematiquement **500 Internal Server Error**, attribue a tort a une instabilite de la sandbox.

**Cause reelle (corrigee le 2026-10-01)** : le corps de la requete etait invalide. Le filtre `{"facette": "DATE_VERSION", "valeur": "VIGUEUR"}` attend un timestamp ; l'API PISTE repond 500 (et non 400) sur un body mal forme. Correctifs dans `legifrance_client.py` :
- `DATE_VERSION` envoye avec `singleDate` (timestamp ms du jour) ; `NOM_CODE` avec `valeurs: [...]`.
- `_parse_search_results()` reecrit : chaque resultat est un code, les articles sont dans `sections[].extracts[]` (id `LEGIARTI...`, `num`, `values`). Balises `<mark>` retirees, 10 articles max.

Verifie sur la sandbox : « responsabilite fait des choses » (Code civil) → art. 1242 ; « contrat de travail » → 10 articles du Code du travail ; recherche sans resultat → liste vide sans erreur. La gestion d'erreur (warning logue, le LLM continue sans crash) reste en place.

### Endpoint `/consult/getArticle` — OK

Test avec l'article 1240 du Code civil (`LEGIARTI000032041571`) :

| Etape | Resultat |
|-------|----------|
| `getArticle` | Texte integral recupere, etat `VIGUEUR`, num `1240` |
| `synchroniser_article()` 1er appel | Statut `"ajoute"` — embedding calcule, upsert ChromaDB |
| Verification ChromaDB | `source_type: legifrance`, `date_verification: 2026-10-01`, `legi_id` present |
| `synchroniser_article()` 2e appel | Statut `"verifie"` — texte identique, pas de recalcul inutile |

Le pipeline `getArticle` → sync ChromaDB → re-verification est **fonctionnel**.

### Passage en production PISTE

Le pipeline complet fonctionne sur la sandbox. Pour passer en prod, il suffit de mettre a jour les URLs dans `.env` :

```
PISTE_OAUTH_URL=https://oauth.piste.gouv.fr/api/oauth/token
PISTE_API_BASE=https://api.piste.gouv.fr/dila/legifrance/lf-engine-app
```
