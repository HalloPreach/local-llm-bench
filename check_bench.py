"""Verify all three runs/*.json validate against schema.json (independent check)."""
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent
schema = json.loads((ROOT / "schema.json").read_text(encoding="utf-8"))
v = Draft202012Validator(schema)

for f in sorted((ROOT / "runs").glob("*.json")):
    doc = json.loads(f.read_text(encoding="utf-8"))
    errs = list(v.iter_errors(doc))
    assert not errs, f"{f.name}: {errs}"
    m = doc["metrics"]
    print(f"{f.name:22s} status={doc['status']:8s} runtime={doc['runtime']['name']:10s} "
          f"pp={m['prompt_processing_tok_s']} gen={m['generation_tok_s']} "
          f"ttft={m['ttft_s']} vram={m['vram_peak_gb']} dur={m['duration_s']}")

print("ALL VALID against schema.json")
