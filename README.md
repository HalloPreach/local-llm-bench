# Local LLM Bench

Dashboard de runs de benchmarks de LLM **locaux** (llama.cpp, NInfer, SGLang) :
liste, filtres, graphiques, comparaison, vue par modèle. Une seule base SQLite,
zéro dépendance côté UI (vanilla JS + SVG), zéro CORS (l'API sert le dossier `ui/`).

## Démarrage rapide

```bash
pip install fastapi uvicorn jsonschema     # le seul outillage requis
uvicorn app:app --port 8000                # API + dashboard sur http://127.0.0.1:8000/
```

Le dashboard est à `http://127.0.0.1:8000/` (les pages `index`, `models.html`,
`detail.html`, `compare.html` sont servies par la même origine que l'API).

## Présentation portfolio

Projet de référence : un dashboard de benchmarks de LLM **locaux** en
vanilla JS (zéro dépendance côté UI) + API FastAPI/SQLite (zéro CORS).
Cinq vues — Tableau de bord (KPIs), Runs (liste/filtres/sort), Modèles
(groupés par fournisseur), Détail, Comparer (deltas + scatter).

### Captures (thème clair, 1280×900)

| | Dashboard | Runs | Modèles | Détail | Comparer |
|---|---|---|---|---|---|
| | `docs/screenshots/dashboard.png` | `runs.png` | `models.png` | `detail.png` | `compare.png` |

### Critères de qualité

- **Zéro dépendance UI** : HTML/CSS/JS vanilla, graphiques SVG maison.
- **Zéro CORS** : l'API monte `ui/` à la racine → même origine.
- **Contrat de données** : payload validé contre `schema.json`
  (draft 2020-12, `additionalProperties=false`).
- **Portes d'auto-contrôle** (à relancer avant toute livraison) :
  `check_ui.py`, `check_bench.py`, `check_schema.py`, `check_kpis.py`,
  `check_models.js`, `e2e_validate.py` (123 cas).
- **Vérification navigateur** : console JS propre (0 erreur), navigation
  entre vues, responsive 375px (pas de débordement horizontal),
  bascule clair/sombre, accessibilité de base (h1 par page, labels,
  `aria-current`).

### Prochaines étapes

Voir `docs/PRODUCT_POLISH_PLAN.md`. Points ouverts : alimenter
`agent_task.time_to_solution_s` via `bench.py` (la ligne TTS du
dashboard affiche « — » tant que vide), et déplacer les filtres/sort
dans l'API si la base dépasse ~2k runs (voir les `# ponytail` dans
`app.py` / `app.js`).


## Insérer des runs

1. **Exécuter un vrai benchmark** avec le collecteur `bench.py` :

```bash
python bench.py --runtime NInfer --model qwen3.8-27b-nvfp4 --quant NVFP4 \
  --context 131072 --prompt-tokens 512 --gen-tokens 128 \
  --runtime-url http://127.0.0.1:30000 --version v1.1.0 --output runs/ninfer.json

# runs d'agent (time-to-solution) :
python bench.py --runtime NInfer --model qwen3.8-27b-nvfp4 --quant NVFP4 \
  --context 131072 --prompt-tokens 512 --gen-tokens 128 \
  --runtime-url http://127.0.0.1:30000 --agent-task "debug failing pytest" \
  --tts 42.5 --agent-success --output runs/agent.json
```

Le champ `command` enregistre la ligne exacte qui a produit le run —
relancez-la pour reproduire. Voir `BENCH.md` pour les trois runtimes.

2. **Envoyer au stockage** : `POST /benchmarks` (le payload est validé
contre `schema.json` ; `additionalProperties=false`). En Python :

```python
import json, urllib.request
doc = json.load(open("runs/ninfer.json"))
req = urllib.request.Request("http://127.0.0.1:8000/benchmarks",
                             data=json.dumps(doc).encode(),
                             headers={"Content-Type": "application/json"},
                             method="POST")
print(urllib.request.urlopen(req).status)   # 201
```

## Jeu de données démo (marqué comme tel)

```bash
python seed_demo.py          # 14 runs de data/seed_data.json via l'API
```

11 de ces runs sont **synthétiques** et portent `"example": true` — le
dashboard les affiche avec le badge « ex » et la page Modèles le signale.
Ils servent au rendu des graphiques ; ils ne sont **pas** des mesures.
Les 3 autres (1 run NInfer mesuré sur la machine + 2 outputs d'erreur du
collecteur) sont réels et non marqués.

## API (résumé)

| Endpoint | Description |
|---|---|
| `POST /benchmarks` | crée un run (201, id auto `run-xxxxxxxx` si absent, 409 si dupliqué) |
| `GET /benchmarks` | liste + filtres `model, runtime, quantization, gpu, date_from, date_to` + pagination (`page`, `page_size` ≤ 200) |
| `GET /benchmarks/filters` | valeurs distinctes des clés de filtre + bornes de dates |
| `GET /benchmarks/compare?ids=a,b,c` | jusqu'à 10 runs, liste ceux introuvables |
| `GET /benchmarks/{id}` | détail |
| `DELETE /benchmarks/{id}` | supprime (204 / 404) |

Le chemin de la base : variable `BENCH_DB` (défaut `./bench.db`).
`NO_UI=1` désactive le montage du dossier `ui/` (API seule).

## Vérifications

```bash
python check_ui.py        # HTML bien formé, classes CSS, endpoints branchés
python check_bench.py     # les runs/*.json sont valides, statuts attendus
python check_schema.py    # exemples de validité/invalidité du schéma
python e2e_validate.py    # parcours complet API + jeu démo + chemins d'erreur
```

## Structure

```
app.py            API FastAPI + montage statique de ui/
bench.py          collecteur des 3 runtimes (écriture de documents valides)
schema.json       contrat de données (draft 2020-12, additionalProperties=false)
seed_demo.py      envoie data/seed_data.json dans l'API
check_*.py        auto-vérifications ci-dessus
ui/               dashboard : index, models, detail, compare + app.js + style.css
runs/             sorties réelles du collecteur sur cette machine
design/           design-system de référence (maquette statique, hors du scope UI)
```
