"""Mark synthetic seed runs with example=true, add exact commands.

The two runs/*.json error docs are real collector output (status=error,
honest) and the live NInfer run is a real measurement: only the 10
invented runs are marked example=true. Idempotent: re-running keeps state.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SEED = ROOT / "data" / "seed_data.json"
docs = json.loads(SEED.read_text(encoding="utf-8"))

# Synthetic runs: id -> command string (the equivalent bench.py line)
EXAMPLES = {
    "run-2026-09-12-llama31-8b-q4km-5090":
        "llama-bench -m Llama-3.1-8B-Instruct-Q4_K_M.gguf -p 1024 -n 256",
    "run-2026-09-14-mistral7b-q4k-5090":
        "llama-bench -m Mistral-7B-Instruct-v0.3-Q4_K_M.gguf -p 1024 -n 256",
    "run-2026-09-16-llama31-8b-q8-5090":
        "llama-bench -m Llama-3.1-8B-Instruct-Q8_0.gguf -p 2048 -n 512",
    "run-2026-09-18-qwen14b-q4k-5090":
        "llama-bench -m Qwen2.5-14B-Instruct-Q4_K_M.gguf -p 2048 -n 512",
    "run-2026-09-20-qwen3-32b-q4k-cpu":
        "llama-bench -m Qwen3-32B-Q4_K_M.gguf -p 1024 -n 256 (CPU-only, --n-gpu-layers 0)",
    "run-2026-09-22-llama31-8b-fp16-ninfer":
        "python bench.py --runtime NInfer --model Llama-3.1-8B-Instruct --quant FP16 "
        "--context 8192 --prompt-tokens 2048 --gen-tokens 512 --runtime-url http://127.0.0.1:30000 "
        "--version v1.0.4 --output runs/ninfer-llama31-fp16.json",
    "run-2026-09-24-qwen3-14b-nvfp4-ninfer":
        "python bench.py --runtime NInfer --model Qwen3-14B --quant NVFP4 "
        "--context 16384 --prompt-tokens 4096 --gen-tokens 512 --runtime-url http://127.0.0.1:30000 "
        "--version v1.1.0 --output runs/ninfer-qwen3-14b.json",
    "run-2026-09-27-llama31-8b-q8-sglang":
        "python bench.py --runtime SGLang --model Llama-3.1-8B-Instruct --quant Q8_0 "
        "--context 4096 --prompt-tokens 1024 --gen-tokens 256 --runtime-url http://127.0.0.1:30000 "
        "--version v0.4.1 --output runs/sglang-llama31-q8.json",
    "run-2026-09-29-mistral7b-fp16-sglang":
        "python bench.py --runtime SGLang --model Mistral-7B-Instruct-v0.3 --quant FP16 "
        "--context 8192 --prompt-tokens 2048 --gen-tokens 512 --runtime-url http://127.0.0.1:30000 "
        "--version v0.4.1 --output runs/sglang-mistral-fp16.json",
    "run-2026-10-01-qwen27b-nvfp4-131k-ninfer":
        "python bench.py --runtime NInfer --model qwen3.8-27b-nvfp4 --quant NVFP4 "
        "--context 131072 --prompt-tokens 131072 --gen-tokens 1024 --runtime-url http://127.0.0.1:30000 "
        "--version v1.1.0 --output runs/ninfer-qwen27b-131k.json",
    "run-2026-10-01-ninfer-qwen27b-oome":
        "python bench.py --runtime NInfer --model qwen3.8-27b-nvfp4 --quant NVFP4 "
        "--context 131072 --prompt-tokens 131072 --gen-tokens 2048 --runtime-url http://127.0.0.1:30000 "
        "--version v1.1.0 --output runs/ninfer-qwen27b-oome.json",
}

# Real collector output (status=error docs written by bench.py, kept as-is).
# Their commands were not captured by the collector (predates the feature),
# so they are reconstructed from the documented invocation that produced them.
REAL_RECONSTRUCTED = {
    "run-2026-10-01-llamacpp-q4k-5090-error":
        "python bench.py --runtime llama.cpp --model Llama-3.1-8B-Instruct --quant Q4_K_M "
        "--context 4096 --prompt-tokens 1024 --gen-tokens 256 --runtime-bin llama-bench "
        "--output runs/llamacpp.json",
    "run-2026-10-01-sglang-q8-5090-error":
        "python bench.py --runtime SGLang --model Llama-3.1-8B-Instruct --quant Q8_0 "
        "--context 4096 --prompt-tokens 1024 --gen-tokens 256 --runtime-bin bench_serving "
        "--runtime-url http://127.0.0.1:30000 --output runs/sglang.json",
}

LIVE_COMMAND = ("python bench.py --runtime NInfer --model qwen3.8-27b-nvfp4 --quant NVFP4 "
                "--context 131072 --prompt-tokens 512 --gen-tokens 128 "
                "--runtime-url http://127.0.0.1:30000 --version v1.1.0 --output runs/ninfer.json")

changed = 0
for d in docs:
    rid = d["id"]
    if rid in EXAMPLES:
        if not d.get("example"):
            d["example"] = True
            changed += 1
        d["command"] = EXAMPLES[rid]
    elif rid == "run-2026-10-01-qwen27b-nvfp4-ninfer-live":
        d["command"] = LIVE_COMMAND  # real measured run, real command
    elif rid in REAL_RECONSTRUCTED:
        # real collector output; exact invocation reconstructed from BENCH.md
        d["command"] = REAL_RECONSTRUCTED[rid]

SEED.write_text(json.dumps(docs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
n_example = sum(1 for d in docs if d.get("example"))
n_cmd = sum(1 for d in docs if "command" in d)
print(f"example=true: {n_example}/14 | command present: {n_cmd}/14 | new flags set this run: {changed}")
