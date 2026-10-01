"""Self-check: the llama-bench + SGLang parsers extract the right numbers from
realistic sample output (runnable: python check_parsers.py)."""
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("bench", ROOT / "bench.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)

# --- llama-bench: a real run's output shape (from llama.cpp) ---------------
LLAMA_OUT = """
| model | size | params | backend | threads | test | t/s |
|-------|------|--------|---------|---------|------|-----|
|  Llama-3.1-8B-Instruct-Q4_K_M | 5.2G | 8.0B | CUDA | 8 | pp11 | 1024.3 ± 0.0 |
|  Llama-3.1-8B-Instruct-Q4_K_M | 5.2G | 8.0B | CUDA | 8 | tg256 | 52.40 ± 0.3 |
"""
# The "t/s" columns in the summary table are the authoritative numbers; the
# detailed timing block uses the "t/s" arrows. Test the detailed block.
LLAMA_DETAILED = """
llama-bench: model  = Llama-3.1-8B-Instruct-Q4_K_M
llama-bench: test     = prompt eval  n = 1024 tokens
llama-bench: prompt eval  time =    424.8 ms  -> 2410.3 t/s
llama-bench: test     = generation  n = 256 tokens
llama-bench: gen       time =   4885.4 ms  ->   52.4 t/s
llama-bench: total    time =   5310.2 ms
"""
m = bench._parse_llama_bench(LLAMA_DETAILED, 1024, 256)
assert m["prompt_processing_tok_s"] == 2410.3, m
assert m["generation_tok_s"] == 52.4, m
assert m["ttft_s"] is None
assert m["duration_s"] == 5.310, m
print("llama-bench parser OK:", m)

# --- SGLang bench_serving --------------------------------------------------
SGLANG_OUT = """
============ SGLang Benchmark Result ============
Total input tokens: 1024
Total output tokens: 256
Total test duration (s): 138.7
Request throughput (req/s): 0.01
Output token throughput (tok/s): 52.4
Mean TTFT (ms): 620.5
Mean TPOT (ms): 19.3
==================================================
"""
m2 = bench._parse_sglang(SGLANG_OUT)
assert m2["generation_tok_s"] == 52.4, m2
assert m2["ttft_s"] == 0.621, m2  # 620.5 ms -> seconds
assert m2["duration_s"] == 138.7, m2
assert m2["prompt_processing_tok_s"] is None  # bench_serving does not split prefill
print("SGLang parser OK:", m2)

print("Parsers OK")
