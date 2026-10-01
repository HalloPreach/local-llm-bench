"""Publish only numerical nInfer telemetry to the existing public Pages site."""
from __future__ import annotations

import argparse
import base64
import json
import math
import shutil
import statistics
import subprocess
import time
from pathlib import Path

from ninfer_metrics import discover_log, read_requests

ROOT = Path(__file__).resolve().parent
FIELDS = ("time", "promptTokens", "outputTokens", "cachedTokens", "ttftMs", "totalMs", "tokensPerSecond")


def make_snapshot(log_path, now_ms=None):
    rows, status, _ = read_requests(log_path)
    if status != "ok":
        raise OSError(f"Journal nInfer inaccessible: {status}")
    safe_rows = []
    for row in rows:
        safe = {key: value if isinstance(value := row.get(key), (int, float))
                and not isinstance(value, bool) and math.isfinite(value) else None
                for key in FIELDS}
        safe["status"] = "ok" if row.get("status") == "ok" else "error"
        if safe["time"] is not None:
            safe_rows.append(safe)
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    summaries = {}
    for period in ("3600000", "86400000", "604800000", "all"):
        selected = [row for row in safe_rows if period == "all" or row["time"] >= now_ms - int(period)]
        summary = {"count": len(selected)}
        for key in ("tokensPerSecond", "ttftMs", "totalMs"):
            values = [row[key] for row in selected if row[key] is not None]
            summary[key] = round(statistics.median(values), 2) if values else None
        summaries[period] = summary
    return {"rows": safe_rows[:1000], "summaryByPeriod": summaries,
            "sourceStatus": "ok", "updatedAt": now_ms,
            "latestRequestAt": safe_rows[0]["time"] if safe_rows else None}


def gh_api(*args, payload=None):
    executable = shutil.which("gh") or str(Path("C:/Program Files/GitHub CLI/gh.exe"))
    result = subprocess.run([executable, "api", *args],
                            input=json.dumps(payload) if payload is not None else None,
                            text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout)


def publish(snapshot):
    endpoint = "repos/HalloPreach/local-llm-bench/contents/ui/data/requests.json"
    remote = gh_api(endpoint)
    content = json.dumps(snapshot, separators=(",", ":"), sort_keys=True, allow_nan=False) + "\n"
    gh_api(endpoint, "--method", "PUT", "--input", "-", payload={
        "message": "Update public nInfer timing metrics",
        "content": base64.b64encode(content.encode()).decode(),
        "sha": remote["sha"], "branch": "main",
    })


def main():
    parser = argparse.ArgumentParser(description="Synchronisation automatique des métriques nInfer publiques")
    parser.add_argument("--log", type=Path)
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    path = args.log or discover_log()
    if path is None:
        raise FileNotFoundError("Journal nInfer introuvable")
    snapshot = make_snapshot(path)
    if args.build_only:
        output = ROOT / "ui" / "data" / "requests.json"
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(snapshot, separators=(",", ":"), sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    else:
        publish(snapshot)
    print(f"Synchronisé: {snapshot['summaryByPeriod']['all']['count']} requêtes (1000 dernières dans l'historique)")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        with (ROOT / ".metrics-sync.log").open("a", encoding="utf-8") as log:
            log.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(exc) + "\n")
        raise
