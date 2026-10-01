"""live_verify.py — vérifie le dashboard live (ASGI in-process, DB temporaire) :
pages statiques servies par l'API, endpoints branchés, tri/filtres/compare,
et que le mount statique ne masque pas /benchmarks. Usage : python live_verify.py
"""
import os
import tempfile

os.environ["BENCH_DB"] = os.path.join(tempfile.gettempdir(), "bench_ui_verify.db")
if os.path.exists(os.environ["BENCH_DB"]):
    os.remove(os.environ["BENCH_DB"])

from fastapi.testclient import TestClient
from app import app  # noqa: E402

client = TestClient(app)
RUNS = [
    {"id": "ui-a", "timestamp": "2026-10-01T09:00:00+00:00",
     "model": {"name": "Llama-3.1-8B-Instruct", "parameters": "8B", "arch": "llama"},
     "runtime": {"name": "llama.cpp", "version": "b4952"}, "quantization": "Q4_K_M",
     "hardware": {"gpu": "NVIDIA RTX 4090", "gpu_vram_total_gb": 24, "cpu": "AMD Ryzen 9 7950X", "ram_gb": 64, "os": "Windows 11"},
     "context_length": 4096, "prompt_tokens": 1024, "generation_tokens": 256,
     "metrics": {"prompt_processing_tok_s": 2410.3, "generation_tok_s": 52.4, "ttft_s": 0.62, "vram_peak_gb": 7.1, "duration_s": 138.7},
     "status": "success", "raw_output": "llama-bench: 52.4 t/s"},
    {"id": "ui-b", "timestamp": "2026-10-01T10:00:00+00:00",
     "model": {"name": "Mistral-7B-Instruct-v0.3", "parameters": "7B"},
     "runtime": {"name": "SGLang", "version": "v0.4.1"}, "quantization": "FP16",
     "hardware": {"gpu": "NVIDIA RTX 4090", "gpu_vram_total_gb": 24, "cpu": "AMD Ryzen 9 7950X", "ram_gb": 64, "os": "Windows 11"},
     "context_length": 8192, "prompt_tokens": 2048, "generation_tokens": 512,
     "metrics": {"prompt_processing_tok_s": 1980.0, "generation_tok_s": 41.7, "ttft_s": 1.1, "vram_peak_gb": 13.8, "duration_s": 301.2},
     "status": "success", "raw_output": ""},
    {"id": "ui-c", "timestamp": "2026-10-01T11:30:00+00:00",
     "model": {"name": "Qwen2.5-14B-Instruct", "parameters": "14B"},
     "runtime": {"name": "NInfer", "version": "v2.0"}, "quantization": "NVFP4",
     "hardware": {"gpu": "CPU", "cpu": "AMD Ryzen 9 7950X", "ram_gb": 64, "os": "Windows 11"},
     "context_length": 4096, "prompt_tokens": 512, "generation_tokens": 128,
     "metrics": {"prompt_processing_tok_s": None, "generation_tok_s": 2.9, "ttft_s": 4.8, "vram_peak_gb": None, "duration_s": 96.0},
     "status": "partial", "raw_output": "OOM sur 16GB, run partiel"},
]

ok = 0


def check(label, cond, extra=""):
    global ok
    assert cond, f"ECHEC {label} {extra}"
    ok += 1
    print(f"  ✓ {label}")


# 1. Seed
for r in RUNS:
    resp = client.post("/benchmarks", json=r)
    check(f"POST {r['id']}", resp.status_code == 201)

# 2. Pages statiques servies par le backend (montage ui/ à la racine)
for path, marker in [("/", 'id="genChart"'), ("/compare.html", 'id="runList"'),
                     ("/detail.html", 'id="detail"'), ("/style.css", "--c-accent"),
                     ("/app.js", "listInit")]:
    resp = client.get(path)
    check(f"GET {path}", resp.status_code == 200 and marker in resp.text,
          f"({resp.status_code})")

# 3. Le mount statique ne masque PAS l'API
resp = client.get("/benchmarks")
check("GET /benchmarks (non masqué par le UI)", resp.status_code == 200 and len(resp.json()["items"]) == 3)
resp = client.get("/benchmarks", params={"runtime": "llama.cpp"})
check("filtre runtime", len(resp.json()["items"]) == 1 and resp.json()["items"][0]["id"] == "ui-a")
resp = client.get("/benchmarks", params={"date_from": "2026-10-01T10:30:00+00:00"})
check("filtre date_from", len(resp.json()["items"]) == 1)
resp = client.get("/benchmarks/filters")
f = resp.json()
check("filters", f["models"] == ["Llama-3.1-8B-Instruct", "Mistral-7B-Instruct-v0.3", "Qwen2.5-14B-Instruct"]
      and f["runtimes"] == ["NInfer", "SGLang", "llama.cpp"], str(f["runtimes"]))
resp = client.get("/benchmarks/ui-b")
check("GET détail ui-b", resp.status_code == 200 and resp.json()["runtime"]["name"] == "SGLang")
resp = client.get("/benchmarks/compare", params={"ids": "ui-a,ui-b,ui-c"})
check("compare 3 runs", len(resp.json()["runs"]) == 3 and resp.json()["missing"] == [])

# 4. Tri par date : le plus récent d'abord (comportement API attendu par la UI)
items = client.get("/benchmarks").json()["items"]
check("tri timestamp desc", [i["id"] for i in items] == ["ui-c", "ui-b", "ui-a"], str([i["id"] for i in items]))

# 5. Suppression
resp = client.delete("/benchmarks/ui-c")
check("DELETE ui-c", resp.status_code == 204)
check("ui-c absent", client.get("/benchmarks/ui-c").status_code == 404)

print(f"\nOK — live_verify.py : {ok} vérifications (pages UI + API, DB temporaire)")
