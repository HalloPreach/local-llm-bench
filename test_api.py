"""Self-check for the Local LLM Bench API: validation, CRUD, filters, compare, pagination, empty DB.

Run: python test_api.py
"""
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# redirect the DB to a throwaway file before the app touches it
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_path = _tmp.name
_tmp.close()  # release the handle so the file can be unlinked at the end (Windows)
os.environ["BENCH_DB"] = _tmp_path

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402

client = TestClient(app)
example = json.loads((ROOT / "examples" / "benchmark.example.json").read_text(encoding="utf-8"))


def second_example(**overrides):
    """A valid second run, distinct on every filter key."""
    d = json.loads(json.dumps(example))  # deep copy
    d["id"] = "run-2"
    d["timestamp"] = "2026-10-02T09:00:00+00:00"
    d["model"]["name"] = "Mistral-7B-Instruct"
    d["runtime"] = {"name": "NInfer", "version": "v0.9"}
    d["quantization"] = "Q8_0"
    d["hardware"]["gpu"] = "NVIDIA RTX 3090"
    d["metrics"]["generation_tok_s"] = 33.1
    for k, v in overrides.items():
        d[k] = v
    return d


# --- empty DB -----------------------------------------------------------
r = client.get("/benchmarks")
assert r.status_code == 200
assert r.json() == {"items": [], "total": 0, "page": 1, "page_size": 50}, r.text
r = client.get("/benchmarks/filters")
assert r.status_code == 200
assert r.json() == {"models": [], "runtimes": [], "quantizations": [], "gpus": [], "date_min": None, "date_max": None}
assert client.get("/benchmarks/compare").status_code == 400  # no ids
assert client.get("/benchmarks/none").status_code == 404
assert client.delete("/benchmarks/none").status_code == 404

# --- validation ----------------------------------------------------------
bad_runtime = json.loads(json.dumps(example))
bad_runtime["runtime"] = {"name": "vLLM"}
r = client.post("/benchmarks", json=bad_runtime)
assert r.status_code == 400 and "errors" in r.json()["detail"], r.text
assert r.json()["detail"]["errors"][0]["path"] == "runtime/name"

bad_key = json.loads(json.dumps(example))
bad_key["not_a_field"] = 1
assert client.post("/benchmarks", json=bad_key).status_code == 400

bad_ts = json.loads(json.dumps(example))
bad_ts["timestamp"] = "yesterday"
assert client.post("/benchmarks", json=bad_ts).status_code == 400  # ISO guard

r = client.post("/benchmarks", json=[1, 2])
assert r.status_code == 422, "a non-object body must be rejected"

# --- create / read --------------------------------------------------------
r = client.post("/benchmarks", json=example)
assert r.status_code == 201 and r.json()["id"] == example["id"], r.text
assert client.get("/benchmarks/run-2026-10-01-llama31-8b-q4km-rtx4090").json() == example

# create without an id -> the API assigns one
no_id = json.loads(json.dumps(second_example()))
del no_id["id"]
r = client.post("/benchmarks", json=no_id)
assert r.status_code == 201
auto_id = r.json()["id"]
assert auto_id and r.json() == {**no_id, "id": auto_id}
assert client.get(f"/benchmarks/{auto_id}").status_code == 200
assert client.post("/benchmarks", json=example).status_code == 409  # duplicate id

assert client.get("/benchmarks").json()["total"] == 2

def items(**params):
    return client.get("/benchmarks", params=params).json()["items"]

assert len(items(model="Llama-3.1-8B-Instruct")) == 1
assert len(items(runtime="NInfer")) == 1 and items(runtime="NInfer")[0]["id"] == auto_id
assert len(items(quantization="Q8_0")) == 1
assert len(items(gpu="NVIDIA RTX 3090")) == 1
assert len(items(date_from="2026-10-02T00:00:00+00:00")) == 1
assert len(items(date_to="2026-10-01T23:59:59+00:00")) == 1
assert len(items(date_from="2026-10-02T00:00:00+00:00", date_to="2026-10-03T00:00:00+00:00", runtime="NInfer")) == 1
assert items() == sorted(items(), key=lambda d: d["timestamp"], reverse=True)  # newest first
assert len(items(model="does-not-exist")) == 0

assert client.get("/benchmarks", params={"date_from": "nope"}).status_code == 400
assert client.get("/benchmarks", params={"page_size": 0}).status_code == 422
assert client.get("/benchmarks", params={"page_size": 999}).status_code == 422

r = client.get("/benchmarks", params={"page": 1, "page_size": 2})
assert r.json()["total"] == 2 and len(r.json()["items"]) == 2
r = client.get("/benchmarks", params={"page": 2, "page_size": 1})
assert r.json()["total"] == 2 and len(r.json()["items"]) == 1 and r.json()["page"] == 2
r = client.get("/benchmarks", params={"page": 9, "page_size": 2})  # past the end -> empty, not an error
assert r.json()["items"] == [] and r.json()["total"] == 2

# --- filters endpoint -------------------------------------------------------
f = client.get("/benchmarks/filters").json()
assert f == {
    "models": ["Llama-3.1-8B-Instruct", "Mistral-7B-Instruct"],
    "runtimes": ["NInfer", "llama.cpp"],
    "quantizations": ["Q4_K_M", "Q8_0"],
    "gpus": ["NVIDIA RTX 3090", "NVIDIA RTX 4090"],
    "date_min": "2026-10-01T14:30:00+00:00",
    "date_max": "2026-10-02T09:00:00+00:00",
}, f

# --- compare ----------------------------------------------------------------
llama_id = "run-2026-10-01-llama31-8b-q4km-rtx4090"
r = client.get("/benchmarks/compare", params={"ids": f"{auto_id},{llama_id}"})
assert r.status_code == 200
c = r.json()
assert c["ids"] == [auto_id, llama_id] and c["missing"] == []
assert [x["id"] for x in c["runs"]] == [auto_id, llama_id]  # same order as asked

r = client.get("/benchmarks/compare", params={"ids": f"{auto_id},ghost,{auto_id}"})
assert r.json()["missing"] == ["ghost"] and [x["id"] for x in r.json()["runs"]] == [auto_id]  # dedup
assert client.get("/benchmarks/compare", params={"ids": "a,b,c,d,e,f,g,h,i,j,k"}).status_code == 400

# --- delete ------------------------------------------------------------------
assert client.delete("/benchmarks/ghost").status_code == 404
assert client.delete(f"/benchmarks/{auto_id}").status_code == 204
assert client.get(f"/benchmarks/{auto_id}").status_code == 404
assert client.delete(f"/benchmarks/{auto_id}").status_code == 404
assert client.get("/benchmarks").json()["total"] == 1
assert client.get("/benchmarks", params={"runtime": "llama.cpp"}).json()["total"] == 1

os.unlink(_tmp_path)
print("OK: API self-check passed (validation, CRUD, filters, compare, pagination, empty DB)")
