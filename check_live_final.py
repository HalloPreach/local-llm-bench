"""Final live check: command + example fields through the running API (port 8011)."""
import json
import urllib.request

live = json.load(urllib.request.urlopen(
    "http://127.0.0.1:8011/benchmarks/run-2026-10-01-qwen27b-nvfp4-ninfer-live"))
print("live command:", live["command"][:70], "...")
print("live example:", live.get("example"))
lst = json.load(urllib.request.urlopen("http://127.0.0.1:8011/benchmarks"))
ex = sum(1 for i in lst["items"] if i.get("example"))
print(f"list: {lst['total']} runs, {ex} example-marked (expect 11)")
assert live["command"].startswith("python bench.py") and live.get("example") is None
assert lst["total"] == 14 and ex == 11
print("LIVE OK")
