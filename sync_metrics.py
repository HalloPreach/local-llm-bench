"""Publish only numerical nInfer telemetry to the existing public Pages site."""
from __future__ import annotations

import argparse
from contextlib import closing
import base64
import hashlib
import json
import math
import shutil
import sqlite3
import statistics
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

from ninfer_metrics import discover_log, read_requests

ROOT = Path(__file__).resolve().parent
FIELDS = ("time", "promptTokens", "outputTokens", "cachedTokens", "ttftMs", "totalMs", "tokensPerSecond")


def make_snapshot(log_path, now_ms=None):
    rows, status, _ = read_requests(log_path)
    if status != "ok":
        raise OSError(f"Journal nInfer inaccessible: {status}")
    return snapshot_from_rows(rows, now_ms)


def snapshot_from_rows(rows, now_ms=None):
    safe_rows = sanitize_rows(rows)
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


def sanitize_rows(rows):
    safe_rows = []
    for row in rows:
        safe = {key: value if isinstance(value := row.get(key), (int, float))
                and not isinstance(value, bool) and math.isfinite(value) else None
                for key in FIELDS}
        safe["status"] = "ok" if row.get("status") == "ok" else "error"
        if safe["time"] is not None:
            safe_rows.append(safe)
    return sorted(safe_rows, key=lambda row: row["time"], reverse=True)


def update_history(rows, db_path):
    """Retain sanitized measurements when the server truncates its operational log."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS requests (fingerprint TEXT PRIMARY KEY, stamp INTEGER NOT NULL, data TEXT NOT NULL)")
        records = []
        for row in sanitize_rows(rows):
            data = json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
            records.append((hashlib.sha256(data.encode()).hexdigest(), row["time"], data))
        connection.executemany("INSERT OR IGNORE INTO requests VALUES (?, ?, ?)", records)
        connection.commit()
        return [json.loads(row[0]) for row in connection.execute("SELECT data FROM requests ORDER BY stamp DESC")]


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
    parser.add_argument("--bridge", action="store_true", help="Lire les métriques via le pont local")
    parser.add_argument("--include-bridge", action="store_true", help="Fusionner les mesures du pont local s'il est actif")
    args = parser.parse_args()
    if args.bridge:
        with urlopen("http://127.0.0.1:8765/api/requests", timeout=20) as response:
            data = json.load(response)
        if data.get("sourceStatus") != "ok":
            raise OSError("Le pont local ne peut pas lire le journal")
        rows = data["rows"]
    else:
        workspace_log = ROOT / "logs" / "ninfer.stderr.log"
        path = args.log or (workspace_log if workspace_log.exists() else discover_log())
        if path is None:
            raise FileNotFoundError("Journal nInfer introuvable")
        rows, status, _ = read_requests(path)
        if status != "ok":
            raise OSError(f"Journal nInfer inaccessible: {status}")
        if args.include_bridge:
            try:
                with urlopen("http://127.0.0.1:8765/api/requests", timeout=3) as response:
                    extra = json.load(response)
                if extra.get("sourceStatus") == "ok":
                    rows.extend(extra["rows"])
            except (OSError, ValueError, KeyError):
                pass
    rows = update_history(rows, ROOT / "logs" / "metrics.sqlite3")
    snapshot = snapshot_from_rows(rows)
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
