"""Self-check: schema.json validates the example and rejects bad payloads."""
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent
schema = json.loads((ROOT / "schema.json").read_text(encoding="utf-8"))
example = json.loads((ROOT / "examples" / "benchmark.example.json").read_text(encoding="utf-8"))

Draft202012Validator.check_schema(schema)
validator = Draft202012Validator(schema)

# 1. The example is valid.
validator.validate(example)

# 2. The example carries the fields the API/UI filters on.
assert example["model"]["name"]
assert example["runtime"]["name"] in ["llama.cpp", "NInfer", "SGLang"]
assert example["quantization"]
assert example["hardware"]["gpu"]

# 3. A bad payload is rejected.
bad = dict(example)
bad["runtime"] = {"name": "vLLM"}  # not in the runtime enum
errors = list(validator.iter_errors(bad))
assert errors, "expected invalid runtime to fail validation"

# 4. Unknown top-level keys are rejected (no silent drift).
bad2 = dict(example)
bad2["foo"] = 1
assert list(validator.iter_errors(bad2)), "expected unknown key to fail validation"

print(f"OK: example valid, {len(errors)} expected failure(s) for bad runtime, unknown keys rejected")
