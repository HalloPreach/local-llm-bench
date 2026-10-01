# Benchmark collectors

`bench.py` runs or parses one benchmark for **llama.cpp**, **NInfer** or
**SGLang** and writes a JSON document that validates against `schema.json`.
A runtime that is not installed on this machine is recorded as
`status="error"` with explicit `null` metrics (not a crash), so every output
is still a valid schema document.

## Usage

```bash
# Run a real benchmark on the NInfer HTTP server (default http://127.0.0.1:30000)
python bench.py --runtime NInfer --model qwen3.8-27b-nvfp4 --quant NVFP4 \
  --context 131072 --prompt-tokens 512 --gen-tokens 128 \
  --version v1.1.0 --output runs/ninfer.json

# Run llama-bench (llama.cpp must be installed)
python bench.py --runtime "llama.cpp" --model /path/to/model.gguf \
  --quant Q4_K_M --context 4096 --prompt-tokens 1024 --gen-tokens 256 \
  --runtime-bin llama-bench --output runs/llamacpp.json

# Run SGLang's bench_serving against a server
python bench.py --runtime SGLang --model Llama-3.1-8B-Instruct --quant Q8_0 \
  --context 4096 --prompt-tokens 1024 --gen-tokens 256 \
  --runtime-bin bench_serving --runtime-url http://127.0.0.1:30000 \
  --output runs/sglang.json
```

Options:
- `--model` model id / name (required)
- `--runtime` one of `llama.cpp`, `NInfer`, `SGLang` (required)
- `--quant` weight quantization label (free string, required)
- `--context` context window in tokens (required)
- `--prompt-tokens` target prompt size in tokens (required)
- `--gen-tokens` target generated tokens (required)
- `--output` where to write the JSON document (required)
- `--runtime-url` endpoint for NInfer / SGLang (or env `NINFER_URL`)
- `--runtime-bin` explicit path to the runtime executable
- `--version` runtime version if known (else `null`)

Agentic-task flags (time-to-solution tracking):
- `--agent-task NAME` the task the model was solving (emits an `agent_task`
  block in the document)
- `--tts SECONDS` time-to-solution in seconds (null when omitted)
- `--agent-success` the task was solved (`success: true`; default false)

Reproducibility: every document carries a `command` field with the exact
bench.py invocation that produced it — re-run that line to reproduce.

## Runtime specifics

- **NInfer** (OpenAI-compatible HTTP). TTFT is wall-clock from request start
  to the first streamed content token. `prompt_processing_tok_s` and
  `generation_tok_s` come from the engine's `timings` field (the
  `predicted_per_second` decode counter), not from a wall-clock count of
  streamed tokens. `vram_peak_gb` is the max `nvidia-smi` used-memory sample
  taken at 1 Hz while the workload runs.
- **llama.cpp** (`llama-bench`). The tool's summary-table `t/s` columns and
  the detailed timing block are parsed. `ttft_s` is not reported by
  llama-bench, so it stays `null`.
- **SGLang** (`bench_serving`). Mean TTFT and output-token throughput are
  parsed from the result block. `prompt_processing_tok_s` is not split out by
  bench_serving, so it stays `null`.

## Measurement limits (read before comparing numbers)

- A **resident NInfer server keeps its KV cache hot**. A warm run reports
  `cached_tokens > 0` (see `raw_output`), and `prompt_processing_tok_s` then
  only covers the *fresh* tokens (`prompt_n - cache_n`). Restart the server
  for a cold prefill figure, or read the cache split out of `raw_output`.
- VRAM peak is a 1 Hz sample; a sub-second spike (model load-in) can be
  missed by a little.
- When a runtime is **absent**, all metrics are explicit `null`
  (`status=error`).
- The OS label maps Windows 11 from the build number (>= 22000) because
  `platform.release()` still reports "10" on Windows 11.

## Verification

- `python check_bench.py` — every `runs/*.json` validates against
  `schema.json` (Draft 2020-12).
- `python check_parsers.py` — the llama-bench and SGLang parsers extract the
  right numbers from realistic sample output.
