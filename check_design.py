"""check_design.py — vérifie que design/design-system.html est bien formé
(paires de balises) et qu'il expose les sections attendues.
Usage : python3 check_design.py
"""
import re
from html.parser import HTMLParser

VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
        'link', 'meta', 'param', 'source', 'track', 'wbr'}


class P(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append((tag, self.getpos()))

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack:
            self.errors.append(f"extra </{tag}> at {self.getpos()}")
            return
        top, pos = self.stack.pop()
        if top != tag:
            self.errors.append(
                f"mismatch: <{top}> opened {pos}, closed by </{tag}> at {self.getpos()}")


src = open('design/design-system.html', encoding='utf-8').read()
p = P()
p.feed(src)
p.close()

problems = []
if p.stack:
    problems.append(f"unclosed tags: {[(t, pos) for t, pos in p.stack]}")
if p.errors:
    problems.append(f"tag errors: {p.errors[:10]}")

# Sections attendues du design system
required = ['Design tokens', 'Composants', 'Vue liste', 'Vue détail',
            'Vue comparaison']
for r in required:
    if r not in src:
        problems.append(f"manquant: {r!r}")

# Un token CSS custom property au moins
if not re.search(r'--[a-z-]+:\s*[^;]+;', src):
    problems.append("aucune CSS custom property trouvée")

if problems:
    print("ECHEC — check_design.py")
    for pr in problems:
        print("  -", pr)
    raise SystemExit(1)

n_colors = len(re.findall(r'--c-[a-z0-9-]+:', src))
n_charts = len(re.findall(r'--ch-\d+:', src))
n_sections = src.count('<section')
print(f"OK — bien formé, {len(src)} chars, {n_sections} sections, "
      f"{n_colors} tokens couleur, {n_charts} couleurs graphique.")
