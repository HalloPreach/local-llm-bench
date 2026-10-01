"""Seed the Local LLM Bench demo dataset through the API.

Reads data/seed_data.json (each doc is schema-valid) and POSTs every run to
POST /benchmarks. Re-runnable: an existing id returns 409 and is skipped.

Usage:
    python seed_demo.py [base_url]     # default http://127.0.0.1:8000
Start the API first: uvicorn app:app --port 8000
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SEED = ROOT / "data" / "seed_data.json"


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    runs = json.loads(SEED.read_text(encoding="utf-8"))
    print(f"Seeding {len(runs)} runs into {base} ...")
    created = skipped = 0
    for doc in runs:
        req = urllib.request.Request(
            f"{base}/benchmarks",
            data=json.dumps(doc).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        if status == 201:
            created += 1
            print(f"  + {doc['id']}")
        elif status == 409:
            skipped += 1
            print(f"  = {doc['id']} (already present)")
        else:
            print(f"  ! {doc['id']} -> HTTP {status}")
            return 1
    print(f"Done: {created} created, {skipped} already present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
