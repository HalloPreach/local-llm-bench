import json
import tempfile
import unittest
from pathlib import Path

from sync_metrics import FIELDS, make_snapshot


class SnapshotTests(unittest.TestCase):
    def test_private_text_cannot_enter_export(self):
        secret = "PRIVATE_SENTINEL_PROMPT_RESPONSE_TOKEN"
        event = {"event": "request_done", "timestamp_unix_ms": 1000,
                 "request_id": secret, "model": secret, "protocol": secret,
                 "prompt": secret, "response": secret, "api_key": secret,
                 "result": {"completion_tokens": 20, "prompt_tokens": 10,
                            "finish_reason": secret},
                 "timings_seconds": {"decode": 2, "ttft": 0.1, "total": 3}}
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "requests.jsonl"
            log.write_text(json.dumps(event), encoding="utf-8")
            snapshot = make_snapshot(log, now_ms=2000)
        self.assertNotIn(secret, json.dumps(snapshot))
        self.assertEqual(set(snapshot["rows"][0]), set(FIELDS) | {"status"})
        self.assertEqual(snapshot["rows"][0]["tokensPerSecond"], 10)

    def test_summaries_cover_rows_beyond_history_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "requests.jsonl"
            events = [{"event": "request_done", "request_id": i,
                       "timestamp_unix_ms": 1000 + i,
                       "result": {"completion_tokens": i},
                       "timings_seconds": {"decode": 1}} for i in range(1001)]
            log.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
            snapshot = make_snapshot(log, now_ms=3000)
        self.assertEqual(len(snapshot["rows"]), 1000)
        self.assertEqual(snapshot["summaryByPeriod"]["all"]["count"], 1001)
        self.assertEqual(snapshot["summaryByPeriod"]["all"]["tokensPerSecond"], 500)


if __name__ == "__main__":
    unittest.main()
