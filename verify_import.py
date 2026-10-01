"""Post-import integrity check: bench.db vs the versioned seed source.

- every DB row parses as JSON and validates against schema.json
- no duplicate ids, no loss, no encoding errors (UTF-8 round-trip)
- DB id set == seed_data.json id set (parity with the versioned source)

Usage: python verify_import.py   (exit 0 = OK, exit 1 = mismatch)
"""
import json
import sqlite3
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent
con = sqlite3.connect(ROOT / "bench.db")
schema = json.loads((ROOT / "schema.json").read_text(encoding="utf-8"))
validator = Draft202012Validator(schema)
seed = json.loads((ROOT / "data" / "seed_data.json").read_text(encoding="utf-8"))
seed_ids = {doc["id"] for doc in seed}

rows = con.execute("SELECT id, data FROM benchmarks").fetchall()
con.close()

errors = []
db_ids = set()
for rid, data in rows:
    if rid in db_ids:
        errors.append(f"duplicate id: {rid}")
    db_ids.add(rid)
    # encoding round-trip: bytes -> str -> JSON
    try:
        doc = json.loads(data.encode("utf-8").decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as e:
        errors.append(f"{rid}: unparseable payload ({e})")
        continue
    for err in validator.iter_errors(doc):
        errors.append(f"{rid}: schema error at {err.path} ({err.message})")

if db_ids != seed_ids:
    errors.append(f"id set mismatch with seed source: "
                  f"only in db={sorted(db_ids - seed_ids)}, only in seed={sorted(seed_ids - db_ids)}")

if errors:
    print(f"FAIL: bench.db ({len(rows)} rows)")
    for e in errors:
        print("  !", e)
    sys.exit(1)

n_example = sum(1 for _, d in rows if json.loads(d).get("example"))
print(f"OK: bench.db {len(rows)} rows == seed source {len(seed_ids)} ids; "
      f"all schema-valid, no dupes, no encoding errors ({n_example} marked example)")
