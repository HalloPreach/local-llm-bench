"""check_ui.py — self-check du dashboard (ui/) : HTML bien formé, éléments
requis présents, et chaque classe référencée par app.js existe dans style.css.
Usage : python check_ui.py
"""
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
        'link', 'meta', 'param', 'source', 'track', 'wbr'}


class P(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack:
            self.errors.append(f"extra </{tag}>")
            return
        top = self.stack.pop()
        if top != tag:
            self.errors.append(f"mismatch: <{top}> closed by </{tag}>")


pages = [ROOT / 'ui' / f for f in ('index.html', 'detail.html', 'compare.html', 'models.html')]
css = (ROOT / 'ui' / 'style.css').read_text(encoding='utf-8')
js = (ROOT / 'ui' / 'app.js').read_text(encoding='utf-8')

problems = []
for pg in pages:
    src = pg.read_text(encoding='utf-8')
    p = P()
    p.feed(src)
    p.close()
    if p.stack:
        problems.append(f"{pg.name}: balises non fermées : {p.stack}")
    if p.errors:
        problems.append(f"{pg.name}: {p.errors[:5]}")

# Éléments requis par page
required = {
    'index.html': ['id="q"', 'id="f-model"', 'id="f-runtime"', 'id="f-quant"',
                   'id="f-gpu"', 'id="genChart"', 'id="runs"', 'id="pager"', 'id="summary"'],
    'detail.html': ['id="detail"', 'id="crumb"'],
    'compare.html': ['id="runList"', 'id="goBtn"', 'id="cmpTable"', 'id="scatter"', 'id="ttftChart"'],
    'models.html': ['id="models"'],
}
for name, reqs in required.items():
    src = (ROOT / 'ui' / name).read_text(encoding='utf-8')
    for r in reqs:
        if r not in src:
            problems.append(f"{name}: manquant {r}")

# la nav "Modèles" est présente sur les 4 pages
for name in ('index.html', 'detail.html', 'compare.html', 'models.html'):
    src = (ROOT / 'ui' / name).read_text(encoding='utf-8')
    if 'href="/models.html"' not in src:
        problems.append(f"{name}: lien nav /models.html manquant")

# Toutes les classes CSS référencées par app.js doivent exister dans style.css
classes = set(re.findall(r'class="([\w\- ]+)"', js))
classes = {c.strip() for grp in classes for c in grp.split()}
for c in sorted(classes):
    if c not in css and '.' + c not in css:
        problems.append(f"classe absente de style.css : {c!r}")

# Style : tokens + thèmes sombres présents (design system réutilisé, pas recopié)
for token in ('--c-accent:', '--c-surface:', '--ch-1:', '[data-theme="dark"]'):
    if token not in css:
        problems.append(f"style.css : token/thème manquant {token!r}")

# app.js consomme bien les 4 endpoints du backend
for ep in ('/benchmarks', '/benchmarks/filters', '/benchmarks/compare'):
    if ep not in js:
        problems.append(f"app.js : endpoint non consommé {ep}")

# app.js affiche bien les champs de reproductibilité / TTS / exemple
for token in ('d.command', 'd.agent_task', 'd.example', 'modelsInit', 'Tâche agent'):
    if token not in js:
        problems.append(f"app.js : champ absent {token!r}")

if problems:
    print("ECHEC — check_ui.py")
    for pr in problems:
        print("  -", pr)
    raise SystemExit(1)

print(f"OK — 4 pages bien formées, {len(classes)} classes vérifiées dans style.css "
      f"({len(css)} bytes), endpoints API branchés, thème clair+sombre présent.")
