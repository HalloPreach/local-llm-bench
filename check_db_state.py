"""Vérifie l'état de bench.db (ids, comptage) — utilitaire local."""
import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path(__file__).resolve().parent / "bench.db")
rows = conn.execute("SELECT id FROM benchmarks ORDER BY id").fetchall()
print(f"bench.db: {len(rows)} run(s)")
for r in rows:
    print("  ", r[0])
conn.close()
