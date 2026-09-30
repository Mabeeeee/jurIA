"""Prompt systeme et definitions d'outils pour jurIA."""

SYSTEM_PROMPT = """\
Tu es jurIA, un assistant juridique specialise en droit francais. Tu aides un \
etudiant en droit a comprendre des concepts juridiques, analyser des textes de \
loi, et preparer ses travaux universitaires.

Tu as acces a quatre outils de recherche :
1. "rechercher_base_documentaire" : interroge la base documentaire juridique \
de jurIA (procedure fiscale, etc.). Utilise-le EN PREMIER quand la question \
porte sur un sujet couvert par la base ou quand tu as besoin de references \
precises.
2. "rechercher_mes_cours" : recherche dans les documents (PDF) que l'etudiant \
a uploades. Utilise-le quand la question porte sur le contenu de ses cours ou \
documents personnels.
3. "search_legifrance" : recherche lexicale dans les codes en vigueur sur \
Legifrance (API PISTE). Utilise-le quand la base locale ne donne pas de \
resultats suffisants (AUCUN_RESULTAT_PERTINENT) ou quand la question porte \
sur un article de loi precis absent de la base.
4. "get_article_legifrance" : recupere le texte integral et l'etat actuel \
d'un article identifie par son ID LEGIARTI. Appelle-le AVANT de citer un \
article obtenu via search_legifrance, et pour re-verifier tout article \
marque [A_REVERIFIER] dans les resultats de la base.

Strategie de recherche :
- Commence TOUJOURS par "rechercher_base_documentaire".
- Evalue si les resultats repondent a la question.
- Si un article est marque [A_REVERIFIER], appelle "get_article_legifrance" \
avec son legi_id avant de le citer.
- Si la base est insuffisante (AUCUN_RESULTAT_PERTINENT ou resultats hors \
sujet), utilise "search_legifrance" avec 2 a 4 mots-cles juridiques precis \
(3 tentatives max avec des mots-cles differents).
- Avant de citer un article Legifrance, appelle "get_article_legifrance" \
pour obtenir le texte complet et verifier son etat.
- Ne cite JAMAIS un article que tu n'as pas obtenu via un outil.
- Si un article n'est plus en vigueur (etat != VIGUEUR), signale-le \
explicitement a l'etudiant.

Regles :
- Reponds de maniere precise, structuree et pedagogique.
- Cite les articles de loi, la jurisprudence ou la doctrine pertinents quand \
c'est possible (ex: "Article 1240 du Code civil").
- Si tu n'es pas certain d'une information, dis-le clairement plutot que \
d'inventer.
- Tu n'es PAS un avocat et tu ne fournis PAS de conseil juridique \
professionnel. Rappelle-le si l'utilisateur te pose une question qui semble \
concerner une situation reelle necessitant un avocat.
- Tu peux expliquer des concepts complexes avec des exemples concrets.
- Quand tu mobilises la base documentaire, mentionne que tu as effectue une \
recherche et cite les sources trouvees.
- Reponds en francais sauf si l'utilisateur te parle dans une autre langue.
"""

# ---------------------------------------------------------------------------
# Outil : rechercher_base_documentaire
# ---------------------------------------------------------------------------

TOOL_RECHERCHE = {
    "name": "rechercher_base_documentaire",
    "description": (
        "Recherche dans la base documentaire juridique de jurIA. "
        "Utilise cet outil pour trouver des informations dans les documents "
        "indexes (livres, codes, articles de doctrine). "
        "Formule une requete precise en francais."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "requete": {
                "type": "string",
                "description": "La requete de recherche en francais. Sois precis et utilise des termes juridiques.",
            },
            "domaine": {
                "type": "string",
                "description": "Domaine juridique pour filtrer les resultats (optionnel).",
                "enum": ["procedure_fiscale"],
            },
        },
        "required": ["requete"],
    },
}

TOOL_RECHERCHE_OPENAI = {
    "type": "function",
    "function": {
        "name": "rechercher_base_documentaire",
        "description": TOOL_RECHERCHE["description"],
        "parameters": {
            "type": "object",
            "properties": {
                "requete": {
                    "type": "string",
                    "description": "La requete de recherche en francais. Sois precis et utilise des termes juridiques.",
                },
                "domaine": {
                    "type": "string",
                    "description": "Domaine juridique pour filtrer les resultats (optionnel).",
                    "enum": ["procedure_fiscale"],
                },
            },
            "required": ["requete"],
        },
    },
}

# ---------------------------------------------------------------------------
# Outil : rechercher_mes_cours
# ---------------------------------------------------------------------------

TOOL_RECHERCHE_COURS = {
    "name": "rechercher_mes_cours",
    "description": (
        "Recherche dans les cours et documents PDF uploades par l'etudiant. "
        "Utilise cet outil quand la question porte sur le contenu des documents "
        "personnels de l'utilisateur."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "requete": {
                "type": "string",
                "description": "La requete de recherche en francais.",
            },
        },
        "required": ["requete"],
    },
}

TOOL_RECHERCHE_COURS_OPENAI = {
    "type": "function",
    "function": {
        "name": "rechercher_mes_cours",
        "description": TOOL_RECHERCHE_COURS["description"],
        "parameters": {
            "type": "object",
            "properties": {
                "requete": {
                    "type": "string",
                    "description": "La requete de recherche en francais.",
                },
            },
            "required": ["requete"],
        },
    },
}

# ---------------------------------------------------------------------------
# Outil : search_legifrance
# ---------------------------------------------------------------------------

TOOL_SEARCH_LEGIFRANCE = {
    "name": "search_legifrance",
    "description": (
        "Recherche lexicale dans les codes en vigueur sur Legifrance (API PISTE). "
        "C'est une recherche par mots-cles, pas semantique. Utilise des termes "
        "juridiques precis (2 a 4 mots). A utiliser quand la base documentaire "
        "locale ne donne pas de resultats suffisants."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "mots_cles": {
                "type": "string",
                "description": (
                    "2 a 4 termes du vocabulaire juridique "
                    "(ex: 'depot de garantie restitution'), PAS la question brute de l'etudiant."
                ),
            },
            "nom_code": {
                "type": "string",
                "description": "Nom du code a cibler (ex: 'Code civil'). Optionnel.",
            },
        },
        "required": ["mots_cles"],
    },
}

TOOL_SEARCH_LEGIFRANCE_OPENAI = {
    "type": "function",
    "function": {
        "name": "search_legifrance",
        "description": TOOL_SEARCH_LEGIFRANCE["description"],
        "parameters": {
            "type": "object",
            "properties": {
                "mots_cles": {
                    "type": "string",
                    "description": (
                        "2 a 4 termes du vocabulaire juridique "
                        "(ex: 'depot de garantie restitution'), PAS la question brute de l'etudiant."
                    ),
                },
                "nom_code": {
                    "type": "string",
                    "description": "Nom du code a cibler (ex: 'Code civil'). Optionnel.",
                },
            },
            "required": ["mots_cles"],
        },
    },
}

# ---------------------------------------------------------------------------
# Outil : get_article_legifrance
# ---------------------------------------------------------------------------

TOOL_GET_ARTICLE_LEGIFRANCE = {
    "name": "get_article_legifrance",
    "description": (
        "Recupere le texte integral et l'etat actuel d'un article Legifrance. "
        "A appeler avant de citer un article obtenu via search_legifrance "
        "ET pour re-verifier un article marque [A_REVERIFIER] dans la base locale."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "article_id": {
                "type": "string",
                "description": "Identifiant LEGIARTI... obtenu via search_legifrance ou la base locale.",
            },
            "nom_code": {
                "type": "string",
                "description": "Le nom du code tel qu'affiche dans les resultats. Optionnel.",
            },
        },
        "required": ["article_id"],
    },
}

TOOL_GET_ARTICLE_LEGIFRANCE_OPENAI = {
    "type": "function",
    "function": {
        "name": "get_article_legifrance",
        "description": TOOL_GET_ARTICLE_LEGIFRANCE["description"],
        "parameters": {
            "type": "object",
            "properties": {
                "article_id": {
                    "type": "string",
                    "description": "Identifiant LEGIARTI... obtenu via search_legifrance ou la base locale.",
                },
                "nom_code": {
                    "type": "string",
                    "description": "Le nom du code tel qu'affiche dans les resultats. Optionnel.",
                },
            },
            "required": ["article_id"],
        },
    },
}
