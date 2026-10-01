"""End-to-end validation of the demo dataset through the full API surface.

Seeds data/seed_data.json into a throwaway DB (POST /benchmarks, exactly what
seed_demo.py does), then walks the whole user journey the dashboard performs:
creation, listing, filters, detail, compare, and the chart inputs.
Also re-checks the error paths (400/404/409) and the empty state.

Usage: python e2e_validate.py
"""
import json
import os
import tempfile
from pathlib import Path

# throwaway DB, before the app touches it (same trick as test_api.py)
_tmp = os.path.join(tempfile.gettempdir(), "bench_e2e.db")
if os.path.exists(_tmp):
    os.remove(_tmp)
os.environ["BENCH_DB"] = _tmp

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402

ROOT = Path(__file__).resolve().parent
SEED = json.loads((ROOT / "data" / "seed_data.json").read_text(encoding="utf-8"))
client = TestClient(app)

ok = 0
fails = []


def check(label, cond, extra=""):
    global ok
    if cond:
        ok += 1
        print(f"  ok  {label}")
    else:
        fails.append(label)
        print(f"  FAIL {label} {extra}")


# 1. creation — every seed doc accepted, 201, echoed back intact
for doc in SEED:
    r = client.post("/benchmarks", json=doc)
    check(f"POST {doc['id']}", r.status_code == 201 and r.json() == doc)

# duplicate id -> 409 (idempotent re-seed)
check("dup POST -> 409", client.post("/benchmarks", json=SEED[0]).status_code == 409)

# 2. listing — all 14 rows, newest first, pagination sane
lst = client.get("/benchmarks").json()
check("list total = 14", lst["total"] == 14 and len(lst["items"]) == 14)
ts = [i["timestamp"] for i in lst["items"]]
check("list sorted desc", ts == sorted(ts, reverse=True))
check(
    "page 2 of 5",
    client.get("/benchmarks", params={"page": 2, "page_size": 5}).json()["page"] == 2
    and len(client.get("/benchmarks", params={"page": 2, "page_size": 5}).json()["items"]) == 5,
)
check("past-end page -> empty, not error", client.get("/benchmarks", params={"page": 99}).json()["items"] == [])

# 3. filters — every filter key reflects the seed data
f = client.get("/benchmarks/filters").json()
check(
    "filters",
    f["models"] == sorted({"Llama-3.1-8B-Instruct", "Mistral-7B-Instruct-v0.3", "Qwen2.5-14B-Instruct", "Qwen3-14B", "Qwen3-32B", "qwen3.8-27b-nvfp4"})
    and f["runtimes"] == ["NInfer", "SGLang", "llama.cpp"]
    and "NVFP4" in f["quantizations"] and f["gpus"] == ["CPU", "NVIDIA GeForce RTX 5090"]
    and f["date_min"] == "2026-09-12T09:15:00+00:00"
    and f["date_max"] == "2026-10-01T12:10:00+00:00",
    str(f),
)
check("filter runtime=llama.cpp", len(client.get("/benchmarks", params={"runtime": "llama.cpp"}).json()["items"]) == 6)
check("filter gpu=CPU", len(client.get("/benchmarks", params={"gpu": "CPU"}).json()["items"]) == 1)
check("filter quant=NVFP4", len(client.get("/benchmarks", params={"quantization": "NVFP4"}).json()["items"]) == 4)
check(
    "date window 09-18..09-24",
    len(client.get("/benchmarks", params={"date_from": "2026-09-18T00:00:00+00:00", "date_to": "2026-09-24T23:59:59+00:00"}).json()["items"]) == 4,
)

# 4. detail — one good and one error-status run
check("detail success run", client.get("/benchmarks/run-2026-10-01-qwen27b-nvfp4-ninfer-live").status_code == 200)
check("detail error run", client.get("/benchmarks/run-2026-10-01-llamacpp-q4k-5090-error").json()["status"] == "error")
check("detail missing -> 404", client.get("/benchmarks/ghost").status_code == 404)
check("DELETE missing -> 404", client.delete("/benchmarks/ghost").status_code == 404)

# 5. compare — the compare.html payload (3 mixed runs) and chart inputs
c = client.get("/benchmarks/compare", params={"ids": "run-2026-09-29-mistral7b-fp16-sglang,run-2026-09-22-llama31-8b-fp16-ninfer,run-2026-10-01-qwen27b-nvfp4-ninfer-live"}).json()
check("compare 3 runs", len(c["runs"]) == 3 and c["missing"] == [])
check(
    "compare chart inputs",  # gen bar chart + VRAM scatter + TTFT bars (detail UI reads these)
    all(r["metrics"]["generation_tok_s"] for r in c["runs"])
    and all(r["metrics"]["vram_peak_gb"] for r in c["runs"])
    and all(r["metrics"]["ttft_s"] is not None for r in c["runs"]),
)
check("compare missing listed", client.get("/benchmarks/compare", params={"ids": "run-2026-09-12-llama31-8b-q4km-5090,ghost"}).json()["missing"] == ["ghost"])
check("compare >10 ids -> 400", client.get("/benchmarks/compare", params={"ids": ",".join(f"a{i}" for i in range(11))}).status_code == 400)

# 6. metric sanity — units and status/null contract
for doc in SEED:
    m = doc["metrics"]
    for k in ("prompt_processing_tok_s", "generation_tok_s", "ttft_s", "vram_peak_gb", "duration_s"):
        v = m[k]
        check(f"unit {doc['id']}/{k}", v is None or (isinstance(v, (int, float)) and v >= 0))
    if doc["status"] == "error" and "error" in doc["id"] and "oome" not in doc["id"]:
        check(f"error run all-null {doc['id']}", all(m[k] is None for k in m))
    if doc["status"] == "success":
        check(f"success run no-null {doc['id']}", all(m[k] is not None for k in m))
# the OOM run: vram_peak_gb is measured (server still sampled), generation is null
oom = client.get("/benchmarks/run-2026-10-01-ninfer-qwen27b-oome").json()
check("OOM run partial nulls", oom["metrics"]["generation_tok_s"] is None and oom["metrics"]["vram_peak_gb"] == 31.2)

# 7. error paths (regression)
bad = json.loads(json.dumps(SEED[0]))
bad["runtime"] = {"name": "vLLM"}
r = client.post("/benchmarks", json=bad)
check("bad runtime -> 400 + error list", r.status_code == 400 and r.json()["detail"]["errors"][0]["path"] == "runtime/name")
bad_ts = json.loads(json.dumps(SEED[0]))
bad_ts["timestamp"] = "yesterday"
check("bad timestamp -> 400", client.post("/benchmarks", json=bad_ts).status_code == 400)
check("bad date filter -> 400", client.get("/benchmarks", params={"date_from": "nope"}).status_code == 400)
check("page_size bound -> 422", client.get("/benchmarks", params={"page_size": 999}).status_code == 422)

# 9. new fields — command (reproducibility), agent_task (TTS), example (honest sample data)
check(
    "all 14 seeds carry a command",
    all(doc["command"] is not None for doc in SEED),
)
check(
    "11 synthetic runs marked example",
    sum(1 for doc in SEED if doc.get("example")) == 11
    and not any(doc.get("example") for doc in SEED if "live" in doc["id"] or doc["id"].endswith("-error")),
)
agent_doc = json.loads(json.dumps(SEED[0]))
agent_doc["id"] = "check-agent"
agent_doc["agent_task"] = {"name": "debug failing pytest", "time_to_solution_s": 42.5, "success": True}
agent_doc["example"] = False
r = client.post("/benchmarks", json=agent_doc)
check("agent_task accepted", r.status_code == 201 and r.json()["agent_task"]["time_to_solution_s"] == 42.5)
bad_task = json.loads(json.dumps(agent_doc))
bad_task["agent_task"] = {"name": "x", "success": "yes", "time_to_solution_s": -1}
check("bad agent_task -> 400", client.post("/benchmarks", json=bad_task).status_code == 400)
check(
    "live run carries the exact bench.py invocation",
    client.get("/benchmarks/run-2026-10-01-qwen27b-nvfp4-ninfer-live").json()["command"].startswith(
        "python bench.py --runtime NInfer --model qwen3.8-27b-nvfp4"),
)
check("example flag survives roundtrip", client.get("/benchmarks/run-2026-09-12-llama31-8b-q4km-5090").json()["example"] is True)

# 10. empty state (fresh empty DB behaves as the UI expects)
os.remove(_tmp)
check("empty list", client.get("/benchmarks").json() == {"items": [], "total": 0, "page": 1, "page_size": 50})
check(
    "empty filters",
    client.get("/benchmarks/filters").json()
    == {"models": [], "runtimes": [], "quantizations": [], "gpus": [], "date_min": None, "date_max": None},
)
check("empty compare -> 400", client.get("/benchmarks/compare").status_code == 400)
check("empty detail -> 404", client.get("/benchmarks/anything").status_code == 404)

print(f"\ne2e_validate.py: {ok} ok, {len(fails)} failed", "| FAILURES:", fails or "none")
os.path.exists(_tmp) and os.remove(_tmp)
raise SystemExit(1 if fails else 0)
