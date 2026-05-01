# SBT Marketing Agents Pipeline

Un système multi-agents intelligent pour la prospection commerciale B2B dans le secteur de l'électrotechnique industrielle (coffrets électriques, compteurs, armoires de chantier). Le pipeline identifie automatiquement des entreprises cibles (Tier 1 / Tier 2), scrape leurs sites web, génère des embeddings sémantiques, construit un graphe de relations dans Neo4j, et produit des pitchs commerciaux personnalisés via LLM.

---

## Table des matières

- [Architecture globale](#architecture-globale)
- [Stack technique](#stack-technique)
- [Structure du projet](#structure-du-projet)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Configuration](#configuration)
- [Lancement](#lancement)
- [Les Agents](#les-agents)
  - [Target Searcher](#1-target-searcher)
  - [Scrapper Agent](#2-scrapper-agent)
  - [Marketing Agent](#3-marketing-agent)
- [Protocole Agent-to-Agent (A2A)](#protocole-agent-to-agent-a2a)
- [Orchestrateur LangGraph](#orchestrateur-langgraph)
- [Stockage des données](#stockage-des-données)
  - [SQLite](#sqlite)
  - [Neo4j](#neo4j)
- [Interface Web Flask](#interface-web-flask)
- [Flux de données complet](#flux-de-données-complet)

---

## Architecture globale

```
┌─────────────────────────────────────────────────────────┐
│                   Interface Flask (UI)                    │
│              http://localhost:5000                        │
└──────────────────────┬──────────────────────────────────┘
                       │  Lance via /api/run/orchestrator
                       ▼
┌─────────────────────────────────────────────────────────┐
│              Orchestrateur LangGraph                      │
│   (GraphState : target → scrapper → marketing → END)     │
└────────┬──────────────────┬──────────────────┬──────────┘
         │ A2A HTTP         │ A2A HTTP          │ A2A HTTP
         ▼                  ▼                   ▼
  ┌────────────┐    ┌──────────────┐    ┌──────────────────┐
  │  Target    │    │   Scrapper   │    │    Marketing     │
  │  Searcher  │    │    Agent     │    │     Agent        │
  │ :8001      │    │   :8002      │    │    :8003         │
  └─────┬──────┘    └──────┬───────┘    └────────┬─────────┘
        │                  │                      │
        ▼                  ▼                      ▼
  DuckDuckGo        crawl4ai / MCP          Ollama LLM
  + Ollama LLM      + Ollama LLM            (mistral)
  + Embeddings      + Embeddings
        │                  │
        ▼                  ▼
  ┌─────────────────────────────────┐
  │   SQLite  (data/raw/staging.db) │
  │   Neo4j   (graphe de relations) │
  └─────────────────────────────────┘
```

---

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| Orchestration agents | [LangGraph](https://github.com/langchain-ai/langgraph) |
| Communication inter-agents | Protocole A2A (Agent-to-Agent) via FastAPI + httpx |
| Serveurs agents | [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) |
| Web scraping | [crawl4ai](https://github.com/unclecode/crawl4ai) via MCP |
| Recherche web | DuckDuckGo Search (`ddgs`) |
| LLM local | [Ollama](https://ollama.com/) (`mistral` par défaut) |
| Embeddings | `nomic-embed-text` via Ollama |
| Base de données | SQLite (staging) + [Neo4j](https://neo4j.com/) (graphe) |
| Interface web | Flask + Jinja2 + Bootstrap 5 + vis.js |
| Validation données | Pydantic v2 |
| Logs | Loguru |

---

## Structure du projet

```
obj3/
├── start_agents.py              # Lance les 3 agents A2A en parallèle
├── requirements.txt
├── .env                         # Variables d'environnement (non versionné)
├── .gitignore
│
├── data/
│   └── raw/
│       └── staging.db           # Base SQLite
│
└── src/
    ├── config.py                # Paramètres globaux (Pydantic Settings)
    ├── state.py                 # État partagé LangGraph (AgentState)
    │
    ├── models/
    │   └── company.py           # Modèle Pydantic Company
    │
    ├── a2a/                     # Protocole Agent-to-Agent
    │   ├── models.py            # TaskState, Task, AgentCard, Message, Artifact
    │   ├── server.py            # Fabrique de serveur A2A (create_a2a_app)
    │   └── client.py            # Client HTTP A2A (A2AClient)
    │
    ├── agents/
    │   ├── target_searcher.py   # Agent de recherche et classification
    │   ├── scrapper_agent.py    # Agent de scraping et extraction
    │   ├── marketing_agent.py   # Agent d'analyse et génération de pitchs
    │   └── api/
    │       ├── target_api.py    # Serveur A2A :8001
    │       ├── scrapper_api.py  # Serveur A2A :8002
    │       └── marketing_api.py # Serveur A2A :8003
    │
    ├── graph/
    │   └── orchestrator.py      # Pipeline LangGraph (noeuds A2A)
    │
    ├── mcp/
    │   ├── tool_server.py       # Serveur MCP (outil scrape_url via crawl4ai)
    │   └── search_client.py     # Client MCP (appel scrape_url)
    │
    ├── storage/
    │   ├── database.py          # CRUD SQLite
    │   ├── graph_store.py       # CRUD Neo4j (noeuds + relations)
    │   └── embeddings.py        # Génération embeddings via Ollama
    │
    └── web/
        ├── app.py               # Application Flask
        └── templates/
            ├── base.html        # Layout sidebar + CSS variables
            ├── index.html       # Accueil + bouton orchestrateur
            ├── dashboard.html   # Tableau des entreprises avec pagination
            ├── graph.html       # Visualisation graphe Neo4j (vis.js)
            └── marketing.html   # Résultats analyse + pitchs
```

---

## Prérequis

- **Python 3.10+**
- **Ollama** installé et démarré localement (`http://localhost:11434`)
  ```bash
  ollama pull mistral
  ollama pull nomic-embed-text
  ```
- **Neo4j** Community Edition (local ou Docker)
  ```bash
  docker run -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/votre_mot_de_passe neo4j
  ```
- **Playwright** (pour crawl4ai)
  ```bash
  playwright install chromium
  ```

---

## Installation

```bash
# Cloner le dépôt
git clone https://github.com/hechmi06/hechmi_marketingAgents.git
cd hechmi_marketingAgents

# Créer l'environnement virtuel
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

# Installer les dépendances
pip install -r requirements.txt
```

---

## Configuration

Créer un fichier `.env` à la racine du projet :

```env
# Neo4j
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=votre_mot_de_passe

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=mistral
OLLAMA_EMBED_MODEL=nomic-embed-text

# Seuils de classification
EMBEDDING_CONFIDENCE_THRESHOLD=0.65
LLM_CONFIDENCE_THRESHOLD=0.50

# Délai entre requêtes (secondes)
REQUEST_DELAY_SECONDS=2
```

---

## Lancement

Le système nécessite **deux terminaux** :

### Terminal 1 — Agents A2A

```bash
python start_agents.py
```

Ce script démarre les 3 agents FastAPI en parallèle via `multiprocessing` :

| Agent | Port | URL de découverte |
|-------|------|-------------------|
| target_searcher | 8001 | http://localhost:8001/.well-known/agent.json |
| scrapper_agent | 8002 | http://localhost:8002/.well-known/agent.json |
| marketing_agent | 8003 | http://localhost:8003/.well-known/agent.json |

### Terminal 2 — Interface Flask

```bash
python -m src.web.app
```

Ouvrir dans le navigateur : **http://localhost:5000**

---

## Les Agents

### 1. Target Searcher

**Fichier** : `src/agents/target_searcher.py`  
**API** : `src/agents/api/target_api.py` (port 8001)

**Rôle** : Rechercher des entreprises cibles via DuckDuckGo, les classifier en Tier 1 ou Tier 2, et les enregistrer dans SQLite.

**Fonctionnement détaillé** :

1. **Génération dynamique des requêtes** via LLM (Ollama) — génère 6 à 8 requêtes de recherche contextualisées autour des coffrets électriques, compteurs EDF, armoires de chantier, etc.

2. **Recherche DuckDuckGo** — exécute chaque requête et collecte les URLs résultantes.

3. **Déduplication** :
   - Vérifie si le domaine est déjà présent dans **SQLite** (`get_known_domains()`)
   - Vérifie si la société est déjà dans **Neo4j** (`get_known_domains()`)
   - Si déjà connu → ignoré, pas de traitement redondant

4. **Classification hybride** — deux étapes :
   - **Embedding** : cosine similarity entre l'embedding de l'URL/titre et un vecteur de référence sectoriel (seuil : 0.65)
   - **LLM** : prompt Ollama pour décider Tier 1 / Tier 2 / rejet (seuil : 0.55)
   - Les domaines sans rapport (Wikipedia, LinkedIn, Amazon, etc.) sont filtrés via `EXCLUDED_DOMAINS`

5. **Persistance SQLite** — les entreprises validées sont insérées avec statut `pending`.

**Données produites** :
```json
{
  "saved": 12,
  "skipped_duplicates": 5,
  "message": "12 nouvelles entreprises trouvées"
}
```

---

### 2. Scrapper Agent

**Fichier** : `src/agents/scrapper_agent.py`  
**API** : `src/agents/api/scrapper_api.py` (port 8002)

**Rôle** : Lire les entreprises en statut `pending` dans SQLite, scraper leurs sites web sur plusieurs pages, extraire les données de contact via LLM + regex, et les persister dans SQLite et Neo4j avec création des relations.

**Fonctionnement détaillé** :

1. **Lecture SQLite** — récupère toutes les entreprises au statut `pending`.

2. **Scraping multi-pages** via crawl4ai (via serveur MCP) :
   - Page principale
   - `/contact`, `/contacts`, `/nous-contacter`
   - `/about`, `/qui-sommes-nous`, `/a-propos`
   - `/mentions-legales`, `/legal`, `/cgv`

3. **Extraction LLM** (Ollama `mistral`) — prompt structuré pour extraire :
   - `name` : nom officiel de l'entreprise
   - `address` : adresse physique complète
   - `linkedin` : URL du profil LinkedIn
   - `description` : description de l'activité

4. **Extraction regex** (plus fiable que le LLM pour les contacts) :
   - **Email** : regex internationale, filtre les faux positifs (images, PDF, etc.)
   - **Téléphone** : formats français (+33, 06, 07, 04...) et internationaux
   - **Pays** : détection via indicatifs téléphoniques, TLDs (`.fr`, `.de`, `.es`), mentions textuelles

5. **Persistance** :
   - SQLite : mise à jour de l'entreprise avec statut `scraped`
   - Neo4j : création/mise à jour du nœud `Company` avec toutes les propriétés
   - Neo4j : génération et stockage de l'embedding vectoriel (`nomic-embed-text`)

6. **Création des relations Neo4j** :
   - `(Company)-[:BELONGS_TO]->(Tier)` : rattachement au tier
   - `(Company)-[:MENTIONS]->(OtherCompany)` : si une page mentionne une autre société connue
   - `(Tier2Company)-[:POTENTIAL_SUPPLIER]->(Tier1Company)` : si les critères de compatibilité sont remplis
   - `(Tier2Company)-[:SUPPLIES]->(Tier1Company)` : relation confirmée si détectée

---

### 3. Marketing Agent

**Fichier** : `src/agents/marketing_agent.py`  
**API** : `src/agents/api/marketing_api.py` (port 8003)

**Rôle** : Analyser les prospects Tier 1 et Tier 2 stockés dans Neo4j, générer un plan de ciblage structuré par priorité, et créer des pitchs commerciaux personnalisés pour chaque entreprise sélectionnée.

**Fonctionnement détaillé** :

1. **Chargement des prospects** depuis Neo4j — tous les nœuds `Company` avec leur tier, email, pays, score de confiance.

2. **Analyse LLM (Étape 1-3)** — génération d'un plan de ciblage structuré :
   ```json
   {
     "priorité_1": {
       "entreprises": ["Depagne", "Cahors Group"],
       "action": "Prise de contact directe par email + LinkedIn",
       "message_cle": "Présence internationale et capacité de production élevée"
     },
     "priorité_2": { ... },
     "priorité_3": { ... },
     "conseil_global": "Cibler les entreprises avec présence en Europe..."
   }
   ```

3. **Génération de pitchs personnalisés (Étape 4)** — pour chaque entreprise sélectionnée :
   ```json
   {
     "company": "Depagne",
     "tier": 1,
     "priority": "haute",
     "subject": "Partenariat coffrets électriques de chantier",
     "key_argument": "SBT offre une gamme certifiée CE adaptée aux chantiers EDF/Enedis...",
     "pitch_email": "Madame, Monsieur,\n\nNous avons analysé votre activité...",
     "pitch_linkedin": "Bonjour [Prénom],\n\nJ'ai découvert votre expertise...",
     "follow_up": "Si vous n'avez pas eu l'occasion de lire mon message..."
   }
   ```

---

## Protocole Agent-to-Agent (A2A)

**Répertoire** : `src/a2a/`

Implémentation du standard [Google A2A Protocol](https://google.github.io/A2A/) permettant une communication standardisée entre agents indépendants.

### Endpoints exposés par chaque agent

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/.well-known/agent.json` | GET | Découverte — retourne l'AgentCard |
| `/tasks/send` | POST | Envoie une tâche à l'agent |
| `/tasks/{task_id}` | GET | Consulte l'état d'une tâche |
| `/tasks/{task_id}/cancel` | POST | Annule une tâche en cours |
| `/health` | GET | Vérification de santé |

### Cycle de vie d'une tâche

```
SUBMITTED → WORKING → COMPLETED
                    → FAILED
                    → CANCELED
```

### AgentCard (exemple)

```json
{
  "name": "Target Searcher",
  "description": "Recherche et classifie les entreprises cibles Tier1/Tier2",
  "url": "http://localhost:8001",
  "version": "1.0.0",
  "skills": [
    {
      "id": "search_companies",
      "name": "Recherche d'entreprises",
      "description": "Cherche des prospects via DuckDuckGo et les classifie"
    }
  ]
}
```

### Utilisation du client A2A

```python
from src.a2a.client import A2AClient

async def example():
    client = A2AClient("http://localhost:8001", timeout=300.0)

    # Découverte
    card = await client.get_agent_card()
    print(card.name)

    # Envoi d'une tâche
    task = await client.send_task(
        data={"max_per_query": 5},
        text="Lancer la recherche"
    )

    # Récupération du résultat
    result = client.extract_data(task)
    print(result["saved"])
```

---

## Orchestrateur LangGraph

**Fichier** : `src/graph/orchestrator.py`

Pilote le pipeline complet en séquence via un graphe d'état LangGraph. Chaque nœud communique avec son agent A2A correspondant.

### Graphe d'exécution

```
START
  │
  ▼
node_target_searcher  ──→  A2A :8001
  │
  ▼
node_scrapper         ──→  A2A :8002
  │
  ▼
node_marketing        ──→  A2A :8003
  │
  ▼
END
```

### État partagé (`AgentState`)

```python
class AgentState(TypedDict):
    max_per_query: int          # Nb max d'entreprises par requête
    prospects_found: int        # Résultat du target_searcher
    scraped_count: int          # Résultat du scrapper
    marketing_done: bool        # Indicateur marketing terminé
    messages: list              # Log des messages inter-agents
    errors: list                # Erreurs accumulées
```

### Callback de progression (Flask)

L'orchestrateur accepte un callback `_step_callback(step_name, progress_percent)` pour notifier l'interface Flask en temps réel de l'avancement du pipeline.

---

## Stockage des données

### SQLite

**Fichier** : `data/raw/staging.db`

**Table `companies`** :

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | INTEGER | Clé primaire |
| `website` | TEXT | URL du site |
| `name` | TEXT | Nom de l'entreprise |
| `tier` | INTEGER | 1 ou 2 |
| `status` | TEXT | `pending` / `scraped` / `error` |
| `email` | TEXT | Email extrait |
| `phone` | TEXT | Téléphone extrait |
| `country` | TEXT | Pays détecté |
| `confidence` | REAL | Score de classification (0-1) |
| `created_at` | DATETIME | Date d'insertion |

La méthode `get_known_domains()` permet au target_searcher d'éviter de re-traiter des domaines déjà connus.

### Neo4j

**Nœuds** :

| Label | Propriétés clés |
|-------|----------------|
| `Company` | `name`, `website`, `email`, `phone`, `country`, `tier`, `confidence`, `embedding` (vecteur 768 dims) |
| `Tier` | `level` (1 ou 2) |

**Relations** :

| Relation | De → Vers | Signification |
|----------|-----------|---------------|
| `BELONGS_TO` | Company → Tier | Appartenance au tier |
| `MENTIONS` | Company → Company | Une page mentionne une autre société |
| `POTENTIAL_SUPPLIER` | Tier2 → Tier1 | Compatibilité détectée |
| `SUPPLIES` | Tier2 → Tier1 | Relation de fourniture confirmée |

**Contraintes** :
```cypher
CREATE CONSTRAINT IF NOT EXISTS FOR (c:Company) REQUIRE c.website IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (t:Tier) REQUIRE t.level IS UNIQUE;
```

**Exemple de requête** pour trouver les fournisseurs potentiels d'une Tier 1 :
```cypher
MATCH (s:Company)-[:POTENTIAL_SUPPLIER]->(t:Company {name: "Depagne"})
RETURN s.name, s.country, s.email
```

---

## Interface Web Flask

**Fichier** : `src/web/app.py`  
URL : **http://localhost:5000**

### Pages

#### Accueil (`/`)
- Statistiques globales (total entreprises, Tier 1, Tier 2, scrapées)
- Visualisation du pipeline en étapes
- Cartes de chaque agent avec bouton de lancement individuel
- **Bouton "Tout lancer"** — déclenche l'orchestrateur complet avec barre de progression en temps réel

#### Dashboard (`/dashboard`)
- Tableau paginé de toutes les entreprises (SQLite)
- Filtres par tier et statut (chips cliquables)
- Recherche textuelle en temps réel
- Barres de score de confiance visuelles

#### Graphe Neo4j (`/graph`)
- Visualisation interactive du graphe avec [vis.js](https://visjs.org/)
- Nœuds colorés par tier
- Affichage des relations (BELONGS_TO, MENTIONS, POTENTIAL_SUPPLIER, SUPPLIES)
- Bascule "Figer/Animer" la physique du graphe
- Panel de détails au clic sur un nœud

#### Marketing (`/marketing`)
- **Onglet Prospects** : cartes des entreprises Tier 1 et Tier 2 avec pagination (5 par page)
- **Onglet Plan de ciblage** : priorités 1/2/3 avec actions et messages clés
- **Onglet Pitchs** : pitchs dépliables par entreprise (email + LinkedIn + relance) avec bouton "Copier"

### API REST Flask

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/api/status` | GET | État de tous les agents (running, message) |
| `/api/run/<agent>` | POST | Lancer un agent (`target`, `scrapper`, `marketing`, `orchestrator`) |
| `/api/companies` | GET | Liste des entreprises (SQLite) |
| `/api/graph-data` | GET | Données nœuds/arêtes pour vis.js |
| `/api/marketing-results` | GET | Résultats du dernier run marketing |

---

## Flux de données complet

```
1. RECHERCHE (Target Searcher)
   Ollama génère 6-8 requêtes sectorielles
        │
        ▼
   DuckDuckGo Search → URLs
        │
        ▼
   Déduplication (SQLite + Neo4j)
        │
        ▼
   Classification hybride (embedding + LLM)
        │
        ▼
   SQLite → companies [status=pending]

2. SCRAPING (Scrapper Agent)
   SQLite → entreprises [status=pending]
        │
        ▼
   crawl4ai → HTML des pages (contact, about, legal)
        │
        ▼
   LLM extraction (nom, adresse, LinkedIn, description)
   + Regex extraction (email, téléphone, pays)
        │
        ▼
   Validation & nettoyage
        │
        ├──→ SQLite [status=scraped]
        │
        └──→ Neo4j
             ├── Nœud Company (avec embedding vectoriel)
             ├── Relation BELONGS_TO → Tier
             ├── Relation MENTIONS → autres Company
             └── Relation POTENTIAL_SUPPLIER → Tier1

3. MARKETING (Marketing Agent)
   Neo4j → tous les prospects
        │
        ▼
   Ollama → Plan de ciblage (priorités 1/2/3)
        │
        ▼
   Ollama → Pitchs personnalisés (email + LinkedIn + relance)
        │
        ▼
   Résultats stockés en mémoire → /api/marketing-results
```

---

## Auteur

**Hechmi** — [@hechmi06](https://github.com/hechmi06)

Projet développé dans le cadre d'une stratégie de prospection commerciale B2B automatisée pour SBT (secteur coffrets électriques de chantier / distribution électrique industrielle).
