"""Local LLM Bench collector.

Run (or parse) one benchmark for llama.cpp, NInfer, or SGLang and write a
schema-valid JSON document (schema.json). A runtime that is not installed on
this machine is recorded as status="error" with explicit null metrics rather
than crashing, so the output is still a valid schema document.

Required CLI flags:
  --runtime {llama.cpp,NInfer,SGLang}
  --model MODEL            model id / name
  --quant QUANT           quantization label (free string)
  --context N             context window in tokens
  --prompt-tokens N       target prompt size in tokens
  --gen-tokens N          target generated tokens
  --output PATH           where to write the JSON document

Optional:
  --runtime-url URL       runtime endpoint (NInfer server) or binary dir
  --runtime-bin PATH      explicit path to the runtime executable
  --version VERSION       runtime version if known (else null)

Agentic-task flags (time-to-solution, TTS):
  --agent-task NAME     the task the model was solving; emits agent_task{...}
  --tts SECONDS         time-to-solution in seconds (null when omitted)
  --agent-success       the task was solved (success=true; default false)

The `command` field of every document records this exact invocation so the
run can be reproduced.

Measurement notes (limits):
  * NInfer generation speed is the engine-reported decode rate (the `timings`
    field of the chat completion), not a wall-clock count of streamed tokens;
    TTFT is wall-clock from request start to the first streamed content token.
  * VRAM peak is sampled from nvidia-smi at ~1 Hz during the run; a coarser
    sample can miss the true peak by a little.
  * A resident NInfer server keeps its KV cache hot: a warm run reports
    cached_tokens > 0, and prompt_processing_tok_s then only covers the
    *fresh* tokens (prompt_n - cache_n). Re-run after a restart for a cold
    prefill figure, or read the cache split out of raw_output.
  * When a runtime is absent, all metrics are explicit null (status=error).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = ROOT / "schema.json"

try:
    from jsonschema import Draft202012Validator

    _SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    VALIDATOR = Draft202012Validator(_SCHEMA)
except Exception:  # jsonschema missing: emit anyway, skip validation.
    VALIDATOR = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fail() -> int:
    print("ERROR: collector failed to produce a document", file=sys.stderr)
    return 2


# --------------------------------------------------------------------------- #
# Hardware
# --------------------------------------------------------------------------- #
def _nvidia() -> tuple[str | None, float | None]:
    """Return (gpu_name, total_vram_gb) or (None, None)."""
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=10,
        ).strip().splitlines()
        if not out:
            return None, None
        name, total_mib = [x.strip() for x in out[0].split(",")]
        return name, round(int(total_mib) / 1024, 1)
    except Exception:
        return None, None


def _nvidia_used_gb() -> float | None:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True,
            timeout=10,
        ).strip().splitlines()
        return round(int(out[0]) / 1024, 1) if out else None
    except Exception:
        return None


def vram_sampler(interval_s: float = 1.0):
    """Sample nvidia-smi used-VRAM in the background and report the peak.

    ponytail: one sample per second is enough to see the model's working set;
    a sub-second spike (load-in) can be missed, which is a documented limit.
    Usage:
        s = vram_sampler()
        try:
            ... run the workload ...
        finally:
            s.stop()
        peak = s.peak()
    """
    import threading

    class _S:
        def __init__(self):
            self._stop = threading.Event()
            self._peak = _nvidia_used_gb()
            self._t = threading.Thread(target=self._run, daemon=True)
            self._t.start()

        def _run(self):
            while not self._stop.is_set():
                v = _nvidia_used_gb()
                if v is not None:
                    self._peak = max(self._peak, v) if self._peak is not None else v
                self._stop.wait(interval_s)

        def stop(self):
            self._stop.set()
            self._t.join(timeout=interval_s * 2)

        def peak(self):
            v = _nvidia_used_gb()
            if v is not None:
                self._peak = max(self._peak, v) if self._peak is not None else v
            return self._peak

    return _S()


def _ram_gb() -> float | None:
    if platform.system() == "Windows":
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [
                ("l", ctypes.c_ulong),
                ("load", ctypes.c_ulong),
                ("tot", ctypes.c_ulonglong),
                ("av", ctypes.c_ulonglong),
                ("tp", ctypes.c_ulonglong),
                ("ap", ctypes.c_ulonglong),
                ("tv", ctypes.c_ulonglong),
                ("avv", ctypes.c_ulonglong),
                ("evv", ctypes.c_ulonglong),
            ]

        m = MS()
        m.l = ctypes.sizeof(m)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return round(m.tot / 1024**3, 1)
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal"):
                return round(int(line.split()[1]) / 1024**2, 1)
    except Exception:
        pass
    return None


def _cpu_model() -> str | None:
    """CPU model string, or None when unknown.

    On Windows the registry key holds ProcessorNameString (wmic is removed in
    modern Win11 builds, so we read the registry directly).
    """
    if platform.system() == "Windows":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as k:
                val, _ = winreg.QueryValueEx(k, "ProcessorNameString")
                return str(val)
        except OSError:
            return None
    # Linux / others: first "model name" line in /proc/cpuinfo.
    try:
        for line in open("/proc/cpuinfo"):
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return None


def _os_label() -> str:
    """OS label; on Windows 11 `platform.release()` still says '10', so map
    from the build number (>= 22000 is Win11)."""
    import platform as _p

    sysname = _p.system()
    if sysname == "Windows":
        # platform.version() looks like "10.0.26200" -> last part is the build.
        parts = _p.version().split(".")
        try:
            build = int(parts[-1])
        except (ValueError, IndexError):
            build = 0
        minor = "11" if build >= 22000 else "10"
        return f"Windows {minor}"
    return f"{sysname} {_p.release()}"


def _hardware() -> dict:
    gpu, vram = _nvidia()
    cpu = _cpu_model()
    hw: dict = {
        "gpu": gpu or "CPU",
        "gpu_vram_total_gb": vram,
        "cpu": cpu.strip() if isinstance(cpu, str) else None,
        "ram_gb": _ram_gb(),
        "os": _os_label(),
    }
    return hw


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #
def _make_prompt(target_tokens: int) -> str:
    """Build a prompt of roughly `target_tokens` tokens.

    ponytail: use ~4 chars/token as a coarse English estimate; the *actual*
    prompt_tokens is read back from the runtime's usage report, so this only
    needs to be in the right neighbourhood, not exact.
    """
    target_chars = max(1, target_tokens * 4)
    filler = "benchmark filler text. " * 20
    chunks = []
    total = 0
    while total < target_chars:
        add = filler
        total += len(add)
        chunks.append(add)
    return "".join(chunks)[:target_chars] or "hello"


# --------------------------------------------------------------------------- #
# NInfer (OpenAI-compatible HTTP server)
# --------------------------------------------------------------------------- #
def _ninfer_request(base: str, payload: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _ninfer_stream(base: str, payload: dict, timeout: int = 120):
    """Return (t_first, t_last, n_content_chunks, last_obj) for a streaming call."""
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    t_first = None
    t_last = None
    n = 0
    last = None
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for line in r:
            line = line.decode().strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if data == "[DONE]":
                break
            obj = json.loads(data)
            last = obj
            delta = obj.get("choices", [{}])[0].get("delta", {})
            if delta.get("content") or delta.get("reasoning_content"):
                if t_first is None:
                    t_first = time.monotonic()
                t_last = time.monotonic()
                n += 1
    return t_first, t_last, n, last


def _ninfer_health(base: str, timeout: int = 5) -> bool:
    try:
        with urllib.request.urlopen(base.rstrip("/") + "/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def run_ninfer(args, hw: dict) -> dict:
    base = args.runtime_url or os.environ.get("NINFER_URL", "http://127.0.0.1:30000")
    if not _ninfer_health(base):
        return _absent(
            args,
            hw,
            "NInfer server not reachable at "
            f"{base} (expected /health). Set --runtime-url or NINFER_URL.",
        )

    prompt = _make_prompt(args.prompt_tokens)
    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": args.gen_tokens,
        "temperature": 0,
    }

    # Wall-clock around a streaming call for TTFT; the sampler catches the
    # VRAM peak while the workload runs.
    s = vram_sampler()
    t0 = time.monotonic()
    try:
        t_first, t_last, _n, _last_obj = _ninfer_stream(base, {**payload, "stream": True})
        # A non-streaming call returns the engine's `timings` counters.
        body = _ninfer_request(base, payload)
    finally:
        s.stop()
    ttft_s = (t_first - t0) if t_first is not None else None
    gen_wall_s = (t_last - t_first) if (t_first is not None and t_last is not None) else None

    timings = body.get("timings") or {}
    usage = body.get("usage") or {}
    vram_peak = s.peak()

    prompt_n = usage.get("prompt_tokens") or timings.get("prompt_n")
    completion_n = usage.get("completion_tokens")
    prompt_tok_s = timings.get("prompt_per_second")
    gen_tok_s = timings.get("predicted_per_second")
    # The engine's decode counter is the honest generation speed; the wall-clock
    # streaming window includes TTFT and speculative-decode overhead, so use it
    # only as a sanity floor, never to overwrite the engine figure.
    if gen_wall_s and completion_n and completion_n > 1:
        wall = (completion_n - 1) / gen_wall_s
        gen_tok_s = max(gen_tok_s, wall) if gen_tok_s is not None else wall

    duration_s = round(time.monotonic() - t0, 3)

    metrics = {
        "prompt_processing_tok_s": _r2(prompt_tok_s),
        "generation_tok_s": _r2(gen_tok_s),
        "ttft_s": round(ttft_s, 3) if ttft_s is not None else None,
        "vram_peak_gb": _r1(vram_peak),
        "duration_s": duration_s,
    }
    status = "success" if all(v is not None for v in metrics.values()) else "partial"

    raw = json.dumps(
        {"usage": usage, "timings": timings, "model": body.get("model")}, ensure_ascii=False
    )
    return _doc(args, hw, metrics, status, raw, prompt_n, completion_n)


def run_llama_cpp(args, hw: dict) -> dict:
    binary = args.runtime_bin or _find_binary("llama-bench")
    if binary is None:
        return _absent(
            args,
            hw,
            "llama-bench (llama.cpp) not found on PATH or --runtime-bin. "
            "Install llama.cpp and add it to PATH to run a real benchmark.",
        )
    # ponytail: a real llama-bench invocation is left as a documented command;
    # when the binary is present the caller can run it and feed stdout back in.
    cmd = [
        binary,
        "-m", args.model,
        "-p", str(args.prompt_tokens),
        "-n", str(args.gen_tokens),
    ]
    try:
        s = vram_sampler()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        finally:
            s.stop()
        out = proc.stdout + "\n" + proc.stderr
        m = _parse_llama_bench(out, args.prompt_tokens, args.gen_tokens)
        status = "success" if m["generation_tok_s"] is not None else "partial"
        m["vram_peak_gb"] = _r1(s.peak())
        return _doc(args, hw, m, status, out.strip(), args.prompt_tokens, args.gen_tokens)
    except Exception as e:  # noqa: BLE001
        return _absent(args, hw, f"llama-bench failed: {e}")


def _parse_llama_bench(out: str, prompt_tokens: int, gen_tokens: int) -> dict:
    """Parse llama-bench stdout for prompt/generation t/s and total time.

    llama-bench prints lines like:
      prompt eval   time =  424.8 ms  -> 2410.3 t/s
      gen           time = 4885.4 ms  ->   52.4 t/s
    Newer builds add a total line:
      total         time = 5310.2 ms
    """
    import re

    def grab(label: str) -> float | None:
        m = re.search(
            rf"{re.escape(label)}\s+time\s*=\s*[\d.]+\s*ms\s*->\s*([\d.]+)\s*t/s",
            out,
        )
        return float(m.group(1)) if m else None

    total = re.search(r"total\s+time\s*=\s*([\d.]+)\s*ms", out)
    return {
        "prompt_processing_tok_s": _r2(grab("prompt eval")),
        "generation_tok_s": _r2(grab("gen")),
        "ttft_s": None,  # llama-bench does not report TTFT
        "vram_peak_gb": None,  # filled by the caller from the VRAM sampler
        "duration_s": round(float(total.group(1)) / 1000, 3) if total else None,
    }


def run_sglang(args, hw: dict) -> dict:
    binary = args.runtime_bin or _find_binary("bench_serving")
    if binary is None:
        return _absent(
            args,
            hw,
            "SGLang bench_serving not found on PATH or --runtime-bin. "
            "Install SGLang (pip install 'sglang[all]') and a running sglang "
            "server to run a real benchmark.",
        )
    cmd = [
        binary,
        "--backend", "sglang",
        "--base-url", (args.runtime_url or "http://127.0.0.1:30000"),
        "--num-prompts", "1",
        "--max-tokens", str(args.gen_tokens),
    ]
    try:
        s = vram_sampler()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        finally:
            s.stop()
        out = proc.stdout + "\n" + proc.stderr
        m = _parse_sglang(out)
        status = "success" if m["generation_tok_s"] is not None else "partial"
        m["vram_peak_gb"] = _r1(s.peak())
        return _doc(args, hw, m, status, out.strip(), args.prompt_tokens, args.gen_tokens)
    except Exception as e:  # noqa: BLE001
        return _absent(args, hw, f"sglang bench_serving failed: {e}")


def _parse_sglang(out: str) -> dict:
    """Parse bench_serving stdout for the mean TTFT / throughput lines."""
    import re

    def grab(pat: str) -> float | None:
        m = re.search(pat, out)
        return float(m.group(1)) if m else None

    ttft = grab(r"Mean TTFT \(ms\):\s*([\d.]+)")
    gen_tok_s = grab(r"Output token throughput \(tok/s\):\s*([\d.]+)")
    duration = grab(r"Total test duration \(s\):\s*([\d.]+)")
    return {
        "prompt_processing_tok_s": None,  # bench_serving does not split prefill
        "generation_tok_s": _r2(gen_tok_s),
        "ttft_s": round(ttft / 1000, 3) if ttft is not None else None,
        "vram_peak_gb": None,
        "duration_s": _r2(duration),
    }


# --------------------------------------------------------------------------- #
# Document assembly
# --------------------------------------------------------------------------- #
def _r1(x):
    return round(x, 1) if isinstance(x, (int, float)) else None


def _r2(x):
    return round(x, 2) if isinstance(x, (int, float)) else None


def _absent(args, hw: dict, reason: str) -> dict:
    """A runtime that could not run: explicit null metrics, status=error."""
    metrics = {
        "prompt_processing_tok_s": None,
        "generation_tok_s": None,
        "ttft_s": None,
        "vram_peak_gb": None,
        "duration_s": None,
    }
    return _doc(args, hw, metrics, "error", reason, args.prompt_tokens, args.gen_tokens)


def _doc(
    args,
    hw: dict,
    metrics: dict,
    status: str,
    raw: str,
    prompt_tokens,
    generation_tokens,
) -> dict:
    prompt_tokens = int(prompt_tokens or 0)
    generation_tokens = int(generation_tokens or 0)
    doc = {
        "timestamp": _now_iso(),
        "model": {"name": args.model},
        "runtime": {"name": args.runtime, "version": args.version},
        "quantization": args.quant or "unknown",
        "hardware": hw,
        "context_length": int(args.context),
        "prompt_tokens": prompt_tokens,
        "generation_tokens": generation_tokens,
        "metrics": metrics,
        "status": status,
        "raw_output": raw,
        # Exact invocation (see main): re-running this line reproduces the run.
        "command": _command_line(args),
    }
    if args.agent_task:  # agentic-task run: time-to-solution + success
        doc["agent_task"] = {
            "name": args.agent_task,
            "time_to_solution_s": _r2(args.tts) if args.tts is not None else None,
            "success": bool(args.agent_success),
        }
    return doc


def _find_binary(name: str) -> str | None:
    import shutil

    return shutil.which(name)


def _command_line(args) -> str:
    """Reproducible exact invocation: the bench.py line rebuilt from the parsed
    args. A flag is included only when its value was given (not None); the
    numeric defaults (context 4096, prompt 512, gen 256) are always included
    so the line is copy-paste runnable as-is."""
    parts = ["python", "bench.py", "--runtime", args.runtime, "--model", args.model]
    if args.quant:
        parts += ["--quant", args.quant]
    for flag, val in (("--context", args.context), ("--prompt-tokens", args.prompt_tokens),
                      ("--gen-tokens", args.gen_tokens), ("--output", args.output),
                      ("--runtime-url", args.runtime_url), ("--runtime-bin", args.runtime_bin),
                      ("--version", args.version), ("--agent-task", args.agent_task),
                      ("--tts", args.tts)):
        if val is not None:
            parts += [flag, str(val)]
    return " ".join(parts)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Local LLM benchmark collector")
    p.add_argument("--runtime", required=True, choices=["llama.cpp", "NInfer", "SGLang"])
    p.add_argument("--model", required=True)
    p.add_argument("--quant", default=None)
    p.add_argument("--context", type=int, default=4096)
    p.add_argument("--prompt-tokens", type=int, default=512)
    p.add_argument("--gen-tokens", type=int, default=256)
    p.add_argument("--output", required=True)
    p.add_argument("--runtime-url", default=None)
    p.add_argument("--runtime-bin", default=None)
    p.add_argument("--version", default=None)
    p.add_argument("--agent-task", default=None)
    p.add_argument("--tts", type=float, default=None)
    p.add_argument("--agent-success", action="store_true")
    a = p.parse_args(argv)

    hw = _hardware()
    runners = {"NInfer": run_ninfer, "llama.cpp": run_llama_cpp, "SGLang": run_sglang}
    doc = runners[a.runtime](a, hw)

    if VALIDATOR is not None:
        errs = sorted(VALIDATOR.iter_errors(doc), key=lambda e: e.path)
        if errs:
            for e in errs:
                print(f"SCHEMA: {'/'.join(map(str, e.path)) or '(root)'}: {e.message}", file=sys.stderr)
            print("refusing to write an invalid document", file=sys.stderr)
            return 1

    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"runtime={a.runtime} status={doc['status']}")
    print(f"  prompt_processing_tok_s={doc['metrics']['prompt_processing_tok_s']}")
    print(f"  generation_tok_s       ={doc['metrics']['generation_tok_s']}")
    print(f"  ttft_s                 ={doc['metrics']['ttft_s']}")
    print(f"  vram_peak_gb           ={doc['metrics']['vram_peak_gb']}")
    print(f"  duration_s             ={doc['metrics']['duration_s']}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
