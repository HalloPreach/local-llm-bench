"""Loopback-only read API for nInfer request timings (no prompt/response fields)."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from ninfer_metrics import discover_log, read_requests

ALLOWED_ORIGIN = "https://hallopreach.github.io"
PUBLIC_FIELDS = (
    "time", "status", "promptTokens", "outputTokens", "cachedTokens",
    "ttftMs", "totalMs", "tokensPerSecond",
)


class Handler(BaseHTTPRequestHandler):
    log_path: Path

    def _cors(self):
        if self.headers.get("Origin") == ALLOWED_ORIGIN:
            self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        if urlparse(self.path).path != "/api/requests" or self.headers.get("Origin") != ALLOWED_ORIGIN:
            self.send_error(403)
            return
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if urlparse(self.path).path != "/api/requests":
            self.send_error(404)
            return
        rows, status, malformed = read_requests(self.log_path)
        rows = [{key: row.get(key) for key in PUBLIC_FIELDS} for row in rows]
        payload = json.dumps({
            "rows": rows, "sourceStatus": status, "malformedLines": malformed,
            "updatedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
        }, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main():
    parser = argparse.ArgumentParser(description="Pont local de métriques nInfer")
    parser.add_argument("--log", type=Path, help="Journal nInfer; détecté automatiquement par défaut")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    selected = args.log or discover_log()
    if selected is None:
        parser.error("journal nInfer introuvable; indiquez --log")
    Handler.log_path = selected.expanduser().resolve()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"nInfer bridge: http://127.0.0.1:{args.port}/api/requests", flush=True)
    print(f"Journal: {Handler.log_path}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
