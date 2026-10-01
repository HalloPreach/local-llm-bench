"""Live smoke test against a running uvicorn server (default http://127.0.0.1:8731)."""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
example = json.loads((ROOT / "examples" / "benchmark.example.json").read_text(encoding="utf-8"))


def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    if data:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


checks = []

# empty / baseline
s, j = req("GET", "/benchmarks")
checks.append(("empty list 200 + total", s == 200 and j["total"] == 0))

# create
s, j = req("POST", "/benchmarks", example)
mid = j["id"]
checks.append(("POST 201", s == 201 and mid))

# read
s, j = req("GET", f"/benchmarks/{mid}")
checks.append(("GET one 200", s == 200 and j == example))

# duplicate
s, j = req("POST", "/benchmarks", example)
checks.append(("dup 409", s == 409))

# invalid runtime
bad = json.loads(json.dumps(example))
bad["runtime"] = {"name": "vLLM"}
s, j = req("POST", "/benchmarks", bad)
checks.append(("bad runtime 400", s == 400 and "errors" in j["detail"]))

# filters
s, j = req("GET", "/benchmarks/filters")
checks.append(("filters reflect data", "Llama-3.1-8B-Instruct" in j["models"] and j["date_min"] is not None))

# compare
s, j = req("GET", f"/benchmarks/compare?ids={mid},ghost")
checks.append(("compare 200 + missing", s == 200 and j["missing"] == ["ghost"] and len(j["runs"]) == 1))

# delete
s, j = req("DELETE", f"/benchmarks/{mid}")
checks.append(("DELETE 204", s == 204))
s, j = req("GET", f"/benchmarks/{mid}")
checks.append(("gone 404", s == 404))

failed = [name for name, ok in checks if not ok]
for name, ok in checks:
    print(("PASS" if ok else "FAIL"), name)
print(f"\n{len(checks) - len(failed)}/{len(checks)} passed", "| FAILURES:", failed or "none")
sys.exit(1 if failed else 0)
