"""Local LLM Bench backend: SQLite storage + REST API.

Run: uvicorn app:app --port 8000
DB path: BENCH_DB env var, defaults to ./bench.db.
Payloads are validated against schema.json (draft 2020-12, additionalProperties=false).
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = ROOT / "schema.json"
validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
MAX_COMPARE_IDS = 10
MAX_PAGE_SIZE = 200
UI_DIR = ROOT / "ui"

app = FastAPI(title="Local LLM Bench API")

def db_path() -> str:
    # read per call so tests can redirect via BENCH_DB before first request
    return os.environ.get("BENCH_DB", str(ROOT / "bench.db"))


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS benchmarks (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
    return conn


def _validate(payload: dict) -> None:
    # jsonschema treats "format" as annotation-only; the sort and date filters
    # rely on a parseable timestamp, so guard it here (schema says ISO 8601).
    ts = payload.get("timestamp")
    if not isinstance(ts, str):
        raise HTTPException(400, "timestamp must be an ISO 8601 date-time string")
    try:
        datetime.fromisoformat(ts)
    except ValueError:
        raise HTTPException(400, "timestamp must be an ISO 8601 date-time")
    errors = list(validator.iter_errors(payload))
    if errors:
        detail = {
            "errors": [
                {"path": "/".join(map(str, e.path)) or "(root)", "message": e.message}
                for e in errors
            ]
        }
        raise HTTPException(400, detail)


def _check_date(value: str, name: str) -> None:
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"{name} must be an ISO 8601 date-time")


def _get(id: str) -> dict:
    conn = db()
    try:
        row = conn.execute("SELECT data FROM benchmarks WHERE id = ?", (id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, f"benchmark {id} not found")
    return json.loads(row["data"])


def _matches(doc: dict, model, runtime, quantization, gpu, date_from, date_to) -> bool:
    # ISO timestamps are comparable as strings once validated
    if model and doc["model"]["name"] != model:
        return False
    if runtime and doc["runtime"]["name"] != runtime:
        return False
    if quantization and doc["quantization"] != quantization:
        return False
    if gpu and doc["hardware"]["gpu"] != gpu:
        return False
    ts = doc["timestamp"]
    if date_from and ts < date_from:
        return False
    if date_to and ts > date_to:
        return False
    return True


@app.post("/benchmarks", status_code=201)
def create_benchmark(payload: dict):
    _validate(payload)
    payload.setdefault("id", f"run-{uuid.uuid4().hex[:8]}")
    conn = db()
    try:
        conn.execute(
            "INSERT INTO benchmarks (id, data) VALUES (?, ?)",
            (payload["id"], json.dumps(payload)),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"benchmark id {payload['id']} already exists")
    finally:
        conn.close()
    return payload


@app.get("/benchmarks")
def list_benchmarks(
    model: str | None = None,
    runtime: str | None = None,
    quantization: str | None = None,
    gpu: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
):
    # ponytail: O(n) scan + Python-side filter, fine for a personal dataset of
    # a few thousand rows; switch to JSON1 WHERE clauses + indexes past ~50k.
    if date_from:
        _check_date(date_from, "date_from")
    if date_to:
        _check_date(date_to, "date_to")
    conn = db()
    try:
        docs = [json.loads(r["data"]) for r in conn.execute("SELECT data FROM benchmarks")]
    finally:
        conn.close()
    matched = [d for d in docs if _matches(d, model, runtime, quantization, gpu, date_from, date_to)]
    matched.sort(key=lambda d: d["timestamp"], reverse=True)
    start = (page - 1) * page_size
    return {
        "items": matched[start:start + page_size],
        "total": len(matched),
        "page": page,
        "page_size": page_size,
    }


# declared before /benchmarks/{id} so literal paths win
@app.get("/benchmarks/filters")
def benchmark_filters():
    conn = db()
    try:
        docs = [json.loads(r["data"]) for r in conn.execute("SELECT data FROM benchmarks")]
    finally:
        conn.close()
    stamps = sorted(d["timestamp"] for d in docs)
    return {
        "models": sorted({d["model"]["name"] for d in docs}),
        "runtimes": sorted({d["runtime"]["name"] for d in docs}),
        "quantizations": sorted({d["quantization"] for d in docs}),
        "gpus": sorted({d["hardware"]["gpu"] for d in docs}),
        "date_min": stamps[0] if stamps else None,
        "date_max": stamps[-1] if stamps else None,
    }


@app.get("/benchmarks/compare")
def compare(ids: str = ""):
    id_list = list(dict.fromkeys(i.strip() for i in ids.split(",") if i.strip()))
    if not id_list:
        raise HTTPException(400, "ids must be a comma-separated list of benchmark ids")
    if len(id_list) > MAX_COMPARE_IDS:
        raise HTTPException(400, f"at most {MAX_COMPARE_IDS} ids per comparison")
    conn = db()
    try:
        runs, missing = [], []
        for i in id_list:
            row = conn.execute("SELECT data FROM benchmarks WHERE id = ?", (i,)).fetchone()
            if row:
                runs.append(json.loads(row["data"]))
            else:
                missing.append(i)
    finally:
        conn.close()
    return {"ids": id_list, "runs": runs, "missing": missing}


@app.get("/benchmarks/{id}")
def get_benchmark(id: str):
    return _get(id)


@app.delete("/benchmarks/{id}", status_code=204)
def delete_benchmark(id: str):
    conn = db()
    try:
        cur = conn.execute("DELETE FROM benchmarks WHERE id = ?", (id,))
        conn.commit()
    finally:
        conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, f"benchmark {id} not found")
    return None


# ---------- Serve le dashboard statique (ui/) à la racine ----------
# Même origine que l'API -> zéro config CORS côté navigateur. Opt-out : NO_UI=1.
if os.environ.get("NO_UI") != "1":
    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
