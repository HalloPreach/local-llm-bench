# Local LLM Bench — Plan de polish produit

Objectif : faire du projet un projet principal de portfolio **sans réécrire l'architecture**.
Réutiliser l'existant (UI vanilla JS + SVG, zéro dépendance ; API FastAPI + SQLite), polir les
pages, ajouter un Dashboard d'entrance. Aucune dépendance lourde, aucun nouveau schéma de base.

Règle absolue : les données fictives restent marquées « ex » / « exemple ». Ne jamais présenter
un run synthétique (`example: true`) comme une mesure réelle.

## 1. État des lieux (vérifié dans le code)

**Backend** — `app.py` : API REST + montage statique de `ui/` à la racine (zéro CORS).
Table unique `benchmarks(id, data JSON)` ; payloads validés par `schema.json`
(Draft 2020-12, `additionalProperties=false`). Endpoints existants :
`POST /benchmarks`, `GET /benchmarks` (filtres + pagination ≤ 200), `GET /benchmarks/filters`,
`GET /benchmarks/compare` (≤ 10 ids), `GET/DELETE /benchmarks/{id}`.
**Aucun nouvel endpoint n'est requis** pour ce plan (voir §2, plafond documenté).

**UI** — 4 pages HTML + `ui/app.js` (560 lignes) + `ui/style.css`, vanilla JS, graphiques SVG
natifs, thème clair/sombre persisté. Base API relative `./benchmarks` + repli statique
`ui/seed.json` quand l'API est absente (requis : le site est aussi servi par GitHub Pages en
sous-répertoire `/<repo>/ui/` — **tous les liens restent relatifs**, cf. commits 5b213f9/6164779).

| Page | Fichier | Contenu actuel |
|---|---|---|
| Runs (accueil) | `ui/index.html` | filtres (recherche + modèle/runtime/quant/GPU), résumé, graphe Gen tok/s (top 10), table triable desktop / cartes mobile, pagination 20 |
| Modèles | `ui/models.html` | agrégation par modèle : best gen, TTFT moyen, VRAM pic max, variants, nb d'erreurs, marque « ex » |
| Détail | `ui/detail.html#/run/<id>` | stat cards, méta, **commande exacte** (reproductible), Tâche agent / TTS, sortie brute, suppression |
| Comparer | `ui/compare.html` | sélection 2–5 runs, table avec **deltas % vs 1er run**, nuage Gen × VRAM, barres TTFT |

État des données (`bench.db`, 2026-10-01) : 14 runs (11 exemples, 3 réels) · 6 modèles ·
statuts 4 success / 7 partial / 3 error · meilleur gen 188.99 t/s (qwen3.8-27b-nvfp4, NInfer,
NVFP4) · dernier run 2026-10-01T12:10Z · TTFT moyen 59.0 s (6 runs non-nuls).

**Gates de vérification** : `check_ui.py` (HTML bien formé, ids requis par page, toute classe
JS doit exister dans `style.css`, tokens/thèmes, repli seed.json, `.alert[hidden]`),
`check_bench.py`, `e2e_validate.py` (123 checks), `verify_import.py`.
Toute page ajoutée doit passer dans `check_ui.py` (entrée dans la map `required` + liste des pages).

**Points de friction identifiés** :
1. Pas de page d'entrée/KPIs — la liste des Runs est l'accueil ; les indicateurs sont dispersés.
2. TTS / time-to-solution (le différenciateur du projet) n'apparaît que dans la vue détail —
   absent des listes, de Compare et de tout résumé.
3. Compare : la liste de sélection n'est ni filtrable ni triable ; le run de référence
   (1er sélectionné, base des deltas) n'est pas signalé dans la table.
4. Modèles : pas de recherche/filtre ; le marqueur « ex » est discret (petit sous-texte).
5. Bug : `ui/detail.html` line 18 — `aria-current="page"` est sur le lien « Comparer »
   (copier-coller) au lieu de rien (la page Détail n'est pas dans la nav).
6. Le site GitHub Pages ne doit jamais repasser en chemins absolus (régression connue).

## 2. Dashboard d'entrance (carte P1)

Nouvelle page `ui/dashboard.html` + `dashboardInit()` dans `app.js` + branche de boot
(`location.pathname`) + entrée nav sur les 5 pages. `ui/index.html` reste la page Runs ;
la racine GitHub Pages (`index.html` au repo) redirecte déjà vers `ui/` — on pointe la
redirect vers `ui/dashboard.html`.

**KPIs** (calculs côté client sur `GET /benchmarks?page_size=200`, même pattern que la page
Modèles — un seul fetch partagé, pas de nouvel endpoint) :

| KPI | Définition | Source (champ du schéma) | Valeur actuelle |
|---|---|---|---|
| Runs | nombre total + sous-ligne « dont N exemples » | `len(items)` + `example` | 14 (dont 11 ex) |
| Modèles testés | nb de modèles distincts | `distinct model.name` | 6 |
| Meilleur modèle | max `metrics.generation_tok_s`, sous-ligne nom + runtime + quant | `generation_tok_s` | 188.99 t/s — qwen3.8-27b-nvfp4 · NInfer · NVFP4 |
| Dernier run | max `timestamp`, sous-ligne modèle | `timestamp` | 2026-10-01 12:10 UTC |
| Taux de succès | `success / total` **sur les runs réels** (`example: false`), sous-ligne par statut | `status`, `example` | 1/3 réel (4/14 tous) |
| TTS optimal (option, différenciateur) | min `agent_task.time_to_solution_s` ; « — » si aucun run `agent_task` | `agent_task` | — (à alimenter par bench.py `--agent-task`) |

Latence moyenne (TTFT) volontairement hors Dashboard : c'est la lecture Compare/Modèles,
pas un KPI d'entrée. Si un 7e KPI est demandé plus tard : moyenne des `ttft_s` non-nuls.

**Plafond assumé** : `page_size` plafonné à 200 côté API. Avec 14 runs, tout est exact.
Si la base dépasse 200 runs, ajouter un endpoint `GET /benchmarks/summary` (count distinct +
max/min) — marquer le moment du franchissement dans `app.js` (`# ponytail: ...`).
Le KPI « Runs » utilise le champ `total` de la réponse (exact au-delà de 200) ; les
distincts (modèles, meilleur gen) sont calculés sur les items retournés — exact ≤ 200 runs.

**States** : skeleton au chargement (`.skeleton-row` existant), état vide « Base vide —
insérez des runs (POST /benchmarks) » avec CTA, `errorBox` (pattern `.alert[hidden]` déjà
corrigé), repli `seed.json` comme les autres pages.

## 3. Règles de cohérence UI (applicables à TOUTES les cartes)

1. **Tokens uniquement** : couleurs/espacements/radius via les custom properties
   (`--c-*`, `--sp-*`, `--r-*`, `--ch-1…5`, thème `[data-theme="dark"]`). Toute nouvelle
   classe CSS entre dans `ui/style.css` — la porte d'entrée `check_ui.py` rejette toute
   classe référencée par `app.js` mais absente de `style.css`.
2. **Composants existants d'abord** : `.card`, `.stat-card`/`.stat-grid`, `.badge--*`,
   `.cls-table` + `.run-cards` (mobile < 768 px), `.filter-bar`/`.cls-field`, `.btn`,
   `.empty-state`, `.skeleton`, `.alert`, `.chart` (SVG `role="img"` + `aria-label`),
   `.cmp-table`, `.select-list`. Mobile : tableau → cartes, jamais de scroll horizontal.
3. **Navigation** : liens **relatifs** uniquement (`./`, `models.html`, `compare.html`,
   `detail.html#/run/<id>`) — compatible GitHub Pages sous-répertoire. `aria-current="page"`
   un seul, sur la page courante ; corriger `detail.html`.
4. **Valeurs null** : « — » jamais 0 factice (format `fmt()` existant) ; statuts en
   badges sémantiques (success/partial/error) ; runs d'exemple toujours marqués « ex »
   ou badge « exemple ».
5. **États cohérents** : chaque page a les 3 états (skeleton → contenu ; vide ; erreur),
   le même `errorBox` + CTA d'action (réinitialiser filtres / réessayer).
6. **Zéro dépendance** : pas de lib JS/CSS, pas de build. Graphiques = SVG inline.
7. **Données** : aucune modification du schéma ni de l'API ; les KPIs/résumés sont des
   agrégats clients sur les endpoints existants.
8. **Portes de test** : à chaque carte, `python check_ui.py` (ajouter la page dans la map
   `required` si nouvelle page), `python e2e_validate.py`, et un test navigateur réel
   (API locale + repli Pages statique).

## 4. Priorités (cartes enfants)

| Prio | Carte | Scope (fichiers touchés) | Hors scope |
|---|---|---|---|
| P1 | Dashboard d'entrée + KPIs (`t_e1900caf`) | `ui/dashboard.html` (nouveau), `app.js` (init + boot), nav × 5, `index.html` racine (redirect), `check_ui.py` (entrée) | aucun endpoint API, aucun changement de Runs/Models/Compare |
| P2 | Polir Runs + détail (`t_e4530b31`) | `ui/index.html`, `app.js` (colonne Durée/Date, liens détail, tri) | refonte de la pagination |
| P3 | Polir Modèles (`t_f50f8ddd`) | `ui/models.html`, `app.js` (recherche/filtre léger, badges, groupage) | tri par colonne avancé |
| P4 | Polir Compare (`t_8f3dca81`) | `ui/compare.html`, `app.js` (filtre/tri de la sélection, signal du run de référence, lisibilité des deltas ; graphe compromis Gen/TTS/VRAM = extension du scatter existant) | pas de nouveau type de graphique lib |
| P5 | QA finale + docs (`t_1b3821a5`) | README (description, captures, qualité), passe accessibilité/responsive/console, récap | aucune feature |

## 5. Critères d'acceptation

- **Plan** : ce document couvre les KPIs du Dashboard, les règles UI et les priorités ;
  aucune fonctionnalité existante n'est modifiée par ce plan (documentation seule).
- **Dashboard** : KPIs cohérents avec `bench.db` (valeurs §2 au 2026-10-01), responsive,
  navigation vers Runs/Modèles/Compare, états vide/chargement/erreur.
- **Pages** : un utilisateur comprend l'historique (Runs), scanne les modèles (Modèles),
  compare et lit les écarts (Compare) ; chaque page revient vers les autres.
- **Qualité** : `check_ui.py` + `e2e_validate.py` verts ; test navigateur réel (API +
  repli statique) ; liens relatifs ; aucune dépendance ajoutée ; données d'exemple
  toujours marquées ; README à jour.
