"""Parse nInfer operational request timings without exposing request content."""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


HERE = Path(__file__).resolve().parent
DONE_LINE = re.compile(r"^(?P<date>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)\s+INFO\s+req#(?P<id>\d+) (?P<outcome>done|cancelled during transport) \| (?P<protocol>[^|]+) \|")


def metric(text, label, unit=""):
    match = re.search(rf"(?:^|\|)\s*{re.escape(label)}\s+([\d,.]+)\s*{re.escape(unit)}", text, re.IGNORECASE)
    return number(match.group(1).replace(",", "")) if match else None


def parse_pretty_line(line, source_id):
    match = DONE_LINE.match(line)
    if not match:
        return None
    try:
        stamp = datetime.strptime(match.group("date"), "%Y-%m-%d %H:%M:%S.%f").astimezone()
    except ValueError:
        return None
    prompt = metric(line, "prompt")
    output = metric(line, "output")
    cache = metric(line, "cache")
    ttft = metric(line, "TTFT", "ms")
    total = metric(line, "total", "s")
    speed = metric(line, "decode", "tok/s")
    return {
        "id": f"{source_id}:{match.group('id')}:{match.group('date')}",
        "time": int(stamp.timestamp() * 1000), "status": "ok" if match.group("outcome") == "done" else "error",
        "protocol": match.group("protocol").strip(), "model": "nInfer",
        "promptTokens": prompt, "outputTokens": output, "cachedTokens": cache,
        "ttftMs": ttft, "totalMs": round(total * 1000, 2) if total is not None else None,
        "tokensPerSecond": speed, "finishReason": "—" if match.group("outcome") == "done" else "annulée",
    }


def discover_log():
    structured = HERE / "logs" / "ninfer-requests.jsonl"
    if structured.exists():
        return structured
    root = Path.home() / "AppData" / "Local" / "ninfer-windows"
    candidates = list(root.glob("*/server.stderr.log"))
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def first_number(*values):
    for value in values:
        parsed = number(value)
        if parsed is not None:
            return parsed
    return None


def parse_event(event):
    if event.get("event") not in ("request_done", "request_error", "request_rejected"):
        return None
    result = event.get("result") or {}
    timings = event.get("timings_seconds") or result.get("timings_seconds") or {}
    request = event.get("request") or {}
    kind = event.get("event")
    output_tokens = first_number(
        result.get("completion_tokens"), result.get("output_tokens"),
        event.get("completion_tokens"), event.get("output_tokens"),
    )
    decode = first_number(timings.get("decode"))
    ttft = first_number(timings.get("ttft"))
    total = first_number(timings.get("total"))
    ts = first_number(event.get("timestamp_unix_ms"))
    if ts is None:
        return None
    return {
        "id": f"{event.get('server_instance_id', 'server')}:{event.get('request_id', int(ts))}",
        "time": int(ts),
        "status": "ok" if kind == "request_done" else "error",
        "protocol": event.get("protocol") or request.get("protocol") or "—",
        "model": event.get("model") or result.get("model") or request.get("model") or "nInfer",
        "promptTokens": first_number(result.get("prompt_tokens"), result.get("input_tokens"), event.get("prompt_tokens")),
        "outputTokens": output_tokens,
        "cachedTokens": first_number(result.get("prefix_cache_hit_tokens"), result.get("cached_tokens")),
        "ttftMs": round(ttft * 1000, 2) if ttft is not None else None,
        "totalMs": round(total * 1000, 2) if total is not None else None,
        "tokensPerSecond": round(output_tokens / decode, 2) if output_tokens is not None and decode and decode > 0 else None,
        "finishReason": result.get("finish_reason") or event.get("finish_reason") or ("erreur" if kind != "request_done" else "—"),
    }


def read_requests(log_path):
    if not log_path.exists():
        return [], "missing", 0
    rows = {}
    malformed = 0
    try:
        with log_path.open("r", encoding="utf-8") as source:
            for line in source:
                if not line.lstrip().startswith("{"):
                    row = parse_pretty_line(line, log_path.name)
                    if row:
                        rows[row["id"]] = row
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                if not isinstance(event, dict):
                    continue
                row = parse_event(event)
                if row:
                    rows[row["id"]] = row
    except OSError:
        return [], "unreadable", malformed
    return sorted(rows.values(), key=lambda row: row["time"], reverse=True), "ok", malformed
