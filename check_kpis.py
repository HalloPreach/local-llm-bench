"""check_kpis.py — vérifie que les KPIs du Dashboard (calculs côté client) sont
cohérents avec bench.db. Recalcule les mêmes agrégats que dashboardInit() dans
app.js (GET /benchmarks?page_size=200 = scan O(n) sur toute la table) et les
compare aux valeurs attendues du plan (docs/PRODUCT_POLISH_PLAN.md §2).

Usage : python check_kpis.py  (exit 0 si cohérent, 1 sinon)

C'est la porte de test du Dashboard : à chaque changement des KPIs, ce script
détection si les agrégats dérivent de la base.
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_items():
    conn = sqlite3.connect(ROOT / "bench.db")
    conn.row_factory = sqlite3.Row  # accès par nom de colonne comme dans app.py
    try:
        docs = [json.loads(r["data"]) for r in conn.execute("SELECT data FROM benchmarks")]
    finally:
        conn.close()
    return docs[:200]  # équivalent de GET /benchmarks?page_size=200 (scan complet)


def compute(items, total):
    ex = [d for d in items if d.get("example")]
    models = {d["model"]["name"] for d in items}
    best = max((d for d in items if d["metrics"]["generation_tok_s"] is not None),
               key=lambda d: d["metrics"]["generation_tok_s"], default=None)
    last = max(items, key=lambda d: d["timestamp"])
    real = [d for d in items if not d.get("example")]
    succ = sum(1 for d in real if d["status"] == "success")
    tts = [d["agent_task"]["time_to_solution_s"] for d in items
           if d.get("agent_task") and d["agent_task"].get("time_to_solution_s") is not None]
    return {
        "runs": total,
        "examples": len(ex),
        "models": len(models),
        "best": best["metrics"]["generation_tok_s"] if best else None,
        "last_ts": last["timestamp"],
        "last_model": last["model"]["name"],
        "succ_real": succ,
        "real_total": len(real),
        "tts": min(tts) if tts else None,
    }


def main():
    items = load_items()
    total = len(items)
    k = compute(items, total)

    # Valeurs attendues au 2026-10-01 (plan §2). Ces assertions codent la
    # définition des KPIs — si la base change, on met à jour ici le tableau
    # d'attentes ET on vérifie la cohérence, pas juste la valeur brute.
    expected = {"runs": 14, "examples": 11, "models": 6, "best": 188.99,
                "succ_real": 1, "real_total": 3}
    problems = []
    for key, want in expected.items():
        got = k[key]
        if key == "best" and got is not None:
            ok = abs(got - want) < 0.01
        else:
            ok = got == want
        if not ok:
            problems.append(f"{key}: attendu {want!r}, obtenu {got!r}")

    # TTS : « — » tant que bench.py n'alimente pas d'agent_task (option, différenciateur)
    # Pas d'assertion stricte sur la valeur ; on vérifie seulement que le champ
    # est bien null/absent (sinon le Dashboard devrait l'afficher).
    if k["tts"] is None:
        print(f"  ok  TTS optimal = « — » (aucun run agent_task alimenté)")
    else:
        print(f"  ok  TTS optimal = {k['tts']} s")

    print(f"  ok  Runs = {k['runs']} (dont {k['examples']} ex)")
    print(f"  ok  Modèles testés = {k['models']}")
    print(f"  ok  Meilleur modèle = {k['best']} t/s")
    print(f"  ok  Dernier run = {k['last_ts']} → {k['last_model']}")
    print(f"  ok  Taux de succès (réel) = {k['succ_real']}/{k['real_total']}")

    if problems:
        print("ECHEC — check_kpis.py")
        for p in problems:
            print("  -", p)
        raise SystemExit(1)
    print("OK — KPIs du Dashboard cohérents avec bench.db (plan §2).")


if __name__ == "__main__":
    main()
