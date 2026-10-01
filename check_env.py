"""Env self-check for UI build: python deps, DB state, browser binary."""
import os
import shutil
import sqlite3

try:
    import fastapi, jsonschema, uvicorn
    print("py-deps: ok")
except ImportError as e:
    print("py-deps: MISSING", e)

db = os.path.join(os.path.dirname(__file__), "bench.db")
if os.path.exists(db):
    c = sqlite3.connect(db)
    print("bench.db runs:", c.execute("select count(*) from benchmarks").fetchone()[0])
    print("sample ids:", [r[0] for r in c.execute("select id from benchmarks limit 5")])
    c.close()
else:
    print("bench.db: absent")

for p in [
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python311\python.exe"),
]:
    print(("found " if os.path.exists(p) else "missing ") + p)
print("edge on PATH:", shutil.which("msedge") or shutil.which("msedge.exe"))
print("chrome on PATH:", shutil.which("chrome") or shutil.which("chrome.exe"))
