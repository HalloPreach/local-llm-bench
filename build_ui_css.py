"""Build ui/style.css from design/design-system.html (single source of truth).

Copies the tokens + component CSS verbatim, drops the spec-docs section,
and appends the few app-only rules. Re-run after design changes.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ds = (ROOT / "design" / "design-system.html").read_text(encoding="utf-8").splitlines()

# <style>...</style> block in the design file
start = next(i for i, l in enumerate(ds) if l.strip() == "<style>")
end = next(i for i, l in enumerate(ds) if l.strip() == "</style>")
inner = "\n".join(ds[start + 1:end]).strip()

# drop the doc-specific section (5. DOCS) — everything from its comment on
doc_start = inner.index("/* 5. DOCS")
core = inner[:doc_start].rstrip()

# small additions the app needs and the spec file doesn't carry
extra = """

/* ---------- APP (ajouts au design system) ---------- */
.view{padding-block:var(--sp-5) var(--sp-7)}
.view > .card, .view > .chart{margin-top:var(--sp-4)}
.empty-state .empty-cta{margin-top:var(--sp-2)}
#genChart svg{width:100%; height:auto}
#genChart .bar{transition:opacity .12s}
#genChart .bar:hover{opacity:.8}
.delta{font-size:var(--text-xs); font-family:var(--font-mono)}
.delta.up{color:var(--c-ok)} .delta.down{color:var(--c-err)}
.btn-row{display:flex; gap:var(--sp-2); flex-wrap:wrap}
@media (max-width:639px){ .btn-row{flex-direction:column} .btn-row .btn{width:100%} }
"""

out = ROOT / "ui" / "style.css"
out.write_text(core + extra + "\n", encoding="utf-8")

# self-check: the file must keep the tokens, both themes and the component classes
text = out.read_text(encoding="utf-8")
for token in [":root{", "[data-theme=\"dark\"]", ".cls-table", ".stat-card",
              ".filter-bar", ".cmp-table", ".select-item", ".pager",
              ".run-cards", ".meta-grid", ".empty-state", ".skeleton", ".chart"]:
    assert token in text, f"missing {token}"
assert "/* 5. DOCS" not in text, "docs section should be dropped"
print(f"ui/style.css built: {out.stat().st_size} bytes — tokens+components OK")
