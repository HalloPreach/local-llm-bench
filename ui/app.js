/* Local LLM Bench — UI (vanilla JS, zéro dépendance).
   3 vues : liste (/), détail (/#/run/<id>), comparaison (/compare.html).
   Consomme : GET /benchmarks, /benchmarks/{id}, /benchmarks/compare, /benchmarks/filters.
   API montée par uvicorn (app:app) — même origine que les pages, donc /benchmarks. */

/* Base relative : fonctionne sur le serveur (uvicorn, pages servies à /) ET sur
   GitHub Pages (site en /<repo>/, l'API n'existe pas → mode démo statique ci-dessous). */
const API = './benchmarks';
/* ponytail : la recherche libre + le tri sont faits côté client sur la page courante (page_size 200).
   S'il dépasse ~2k runs filtrés, déplacer q/sort dans l'API (index SQL) — pas avant. */
const PAGE = 20;

/* ---------- helpers ---------- */
const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const el = (tag, cls, html) => { const n = document.createElement(tag); if (cls) n.className = cls; if (html != null) n.innerHTML = html; return n; };
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = (v, d = 1) => v == null ? '—' : Number(v).toLocaleString('fr-FR', { maximumFractionDigits: d });
const fmtDur = s => s == null ? '—' : (s < 60 ? fmt(s, 1) + ' s' : Math.floor(s / 60) + ':' + String(Math.round(s % 60)).padStart(2, '0') + ' min');
const STATUS_CLS = { success: 'badge--success', partial: 'badge--partial', error: 'badge--error' };
const statusBadge = s => `<span class="badge ${STATUS_CLS[s] || 'badge--neutral'}"><span class="dot"></span>${esc(s)}</span>`;
const CH_COLORS = ['var(--ch-1)', 'var(--ch-2)', 'var(--ch-3)', 'var(--ch-4)', 'var(--ch-5)'];
const short = (name, n = 16) => name.length > n ? name.slice(0, n - 1) + '…' : name;

async function getJSON(url, params, method) {
  if (params) { const q = new URLSearchParams(params); const s = q.toString(); if (s) url += (url.includes('?') ? '&' : '?') + s; }
  const r = await fetch(url, method ? { method } : undefined);
  if (!r.ok) {
    let msg = r.status + ' ' + r.statusText;
    try { const j = await r.json(); if (j.detail) {
      if (Array.isArray(j.detail)) msg = j.detail.join(', ');
      else if (j.detail.errors) msg = j.detail.errors.map(e => e.message).join(', ');
      else if (typeof j.detail === 'string') msg = j.detail;
    } } catch (e) { /* body texte */ }
    throw new Error(msg);
  }
  return r.status === 204 ? null : r.json();
}

/* ---------- mode démo statique (GitHub Pages) ----------
   Sans serveur, l'API répond 404 (hébergement statique) → on bascule sur
   ./seed.json, la capture du jeu de démo. Sur un vrai API (uvicorn), rien de
   tout ceci ne s'exécute : les appels passent en premier. */
let _demo = null;
async function demoRuns() {
  if (_demo) return _demo;
  try {
    const r = await fetch('./seed.json');
    if (!r.ok) { _demo = []; }
    else _demo = (await r.json()).sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1));
  } catch (e) { _demo = []; }
  return _demo;
}
function demoFilter(rows, p) {
  let out = rows;
  if (p.model) out = out.filter(d => d.model.name === p.model);
  if (p.runtime) out = out.filter(d => d.runtime.name === p.runtime);
  if (p.quantization) out = out.filter(d => d.quantization === p.quantization);
  if (p.gpu) out = out.filter(d => d.hardware.gpu === p.gpu);
  return out;
}
function demoFilters(rows) {
  const u = a => [...new Set(a)].sort();
  const stamps = rows.map(d => d.timestamp).sort();
  return { models: u(rows.map(d => d.model.name)), runtimes: u(rows.map(d => d.runtime.name)),
    quantizations: u(rows.map(d => d.quantization)), gpus: u(rows.map(d => d.hardware.gpu)),
    date_min: stamps[0] ?? null, date_max: stamps.at(-1) ?? null };
}

/* ---------- thème (3 pages) ---------- */
function initTheme() {
  const btn = $('#themeToggle'); if (!btn) return;
  const root = document.documentElement, label = $('#themeLabel');
  const apply = t => { root.setAttribute('data-theme', t); btn.setAttribute('aria-pressed', t === 'dark' ? 'true' : 'false'); if (label) label.textContent = t === 'dark' ? 'Thème sombre' : 'Thème clair'; };
  apply(root.getAttribute('data-theme') || 'light');
  btn.addEventListener('click', () => { const n = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark'; localStorage.setItem('llm-bench-theme', n); apply(n); });
}

/* ---------- graphiques SVG natifs (pas de lib) ---------- */
function emptyChart() { return '<div class="empty-state"><h3>Aucune donnée</h3></div>'; }

function barChart(container, items, { color = 'var(--c-accent)' } = {}) {
  if (!items.length) { container.innerHTML = emptyChart(); return; }
  const W = 680, H = 240, pad = { l: 46, r: 14, t: 18, b: 34 };
  const max = Math.max(...items.map(i => i.value)) || 1;
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const gap = iw / items.length, bw = Math.min(60, gap * 0.6);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Gen tok/s par run">`;
  for (let g = 0; g <= 3; g++) { const yv = max * g / 3, y = pad.t + ih - ih * (yv / max);
    s += `<line class="grid-line" x1="${pad.l}" y1="${y}" x2="${W - pad.r}" y2="${y}"${g ? ' stroke-dasharray="3 4"' : ''}/>`;
    s += `<text class="axis-label" x="${pad.l - 6}" y="${y + 4}" text-anchor="end">${fmt(yv, 0)}</text>`; }
  items.forEach((it, i) => {
    const x = pad.l + gap * i + (gap - bw) / 2, h = ih * (it.value / max), y = pad.t + ih - h;
    s += `<rect class="bar" x="${x}" y="${y}" width="${bw}" height="${Math.max(h, 2)}" rx="3" fill="${color}"><title>${esc(it.label)} : ${fmt(it.value)} t/s</title></rect>`;
    s += `<text class="bar-label" x="${x + bw / 2}" y="${y - 5}" text-anchor="middle">${fmt(it.value, 1)}</text>`;
    if (items.length <= 8) s += `<text class="axis-label" x="${x + bw / 2}" y="${H - pad.b + 16}" text-anchor="middle">${esc(short(it.label, 12))}</text>`;
  });
  s += `<text class="axis-label" x="${W - pad.r}" y="${H - 4}" text-anchor="end">Gen tok/s (t/s)</text></svg>`;
  container.innerHTML = s;
}

function scatter(container, runs, legendEl) {
  if (!runs.length) { container.innerHTML = emptyChart(); if (legendEl) legendEl.innerHTML = ''; return; }
  const W = 320, H = 200, pad = { l: 40, r: 14, t: 14, b: 34 };
  const gmax = Math.max(...runs.map(r => r.gen || 0), 1), vmax = Math.max(...runs.map(r => r.vram || 0), 1);
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const sx = v => pad.l + iw * (v / vmax), sy = g => pad.t + ih - ih * (g / gmax);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Gen tok/s × VRAM par run">`;
  for (let g = 0; g <= 3; g++) { const yv = gmax * g / 3, y = pad.t + ih - ih * (yv / gmax);
    s += `<line class="grid-line" x1="${pad.l}" y1="${y}" x2="${W - pad.r}" y2="${y}"${g ? ' stroke-dasharray="3 4"' : ''}/>`;
    s += `<text class="axis-label" x="${pad.l - 5}" y="${y + 4}" text-anchor="end">${fmt(yv, 0)}</text>`; }
  for (let g = 0; g <= 2; g++) { const xv = vmax * g / 2;
    s += `<text class="axis-label" x="${sx(xv)}" y="${H - pad.b + 16}" text-anchor="middle">${fmt(xv, 0)} GB</text>`; }
  s += `<text class="axis-label" x="${pad.l + iw / 2}" y="${H - 4}" text-anchor="middle">VRAM pic (GB)</text>`;
  runs.forEach(r => { if (r.gen == null || r.vram == null) return;
    const cx = sx(r.vram), cy = sy(r.gen);
    s += `<circle cx="${cx}" cy="${cy}" r="9" fill="${r.color}" fill-opacity=".85"><title>${esc(r.label)} — ${fmt(r.gen)} t/s · ${fmt(r.vram)} GB</title></circle>`;
    s += `<text class="bar-label" x="${cx}" y="${cy - 13}" text-anchor="middle">${fmt(r.gen, 1)}</text>`; });
  s += '</svg>';
  container.innerHTML = s;
  if (legendEl) legendEl.innerHTML = runs.map(r => `<span><i style="background:${r.color}"></i>${esc(r.label)}</span>`).join('');
}

function ttftChart(container, runs) {
  const rows = runs.filter(r => r.ttft != null);
  if (!rows.length) { container.innerHTML = emptyChart(); return; }
  const W = 320, rowH = 34, pad = { l: 120, r: 44, t: 8 };
  const H = pad.t + rows.length * rowH + 8, max = Math.max(...rows.map(r => r.ttft), 0.1);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="TTFT par run">`;
  rows.forEach((r, i) => {
    const y = pad.t + i * rowH + rowH / 2, bw = (W - pad.l - pad.r) * (r.ttft / max);
    s += `<text class="bar-label" x="${pad.l - 6}" y="${y + 4}" text-anchor="end">${esc(short(r.label, 14))}</text>`;
    s += `<rect class="bar" x="${pad.l}" y="${y - 9}" width="${Math.max(bw, 2)}" height="18" rx="3" fill="${r.color}" fill-opacity=".85"><title>${esc(r.label)} — ${fmt(r.ttft)} s</title></rect>`;
    s += `<text class="axis-label" x="${pad.l + bw + 4}" y="${y + 4}">${fmt(r.ttft, 2)} s</text>`; });
  s += '</svg>';
  container.innerHTML = s;
}

/* ================= VUE LISTE (index.html) ================= */
const list = {
  items: [], q: '', sort: { key: 'date', dir: -1 }, page: 1,
  F: { model: '', runtime: '', quantization: '', gpu: '' },
};

/* Tri des colonnes métriques : valeurs brutes ; les metrics manquants (null)
   sont toujours placés en fin de liste par le comparateur ci-dessous. */
const SORTS = {
  gen: d => d.metrics.generation_tok_s,
  ttft: d => d.metrics.ttft_s,
  vram: d => d.metrics.vram_peak_gb,
};

async function listInit() {
  initTheme();
  // lien "Voir les runs" (page Modèles) : ?model=X pré-remplit le filtre
  const pm = new URLSearchParams(location.search).get('model');
  if (pm) { list.F.model = pm; }
  const filters = await safeGetFilters();
  if (filters) {
    fillSelect('#f-model', filters.models);
    fillSelect('#f-runtime', filters.runtimes);
    fillSelect('#f-quant', filters.quantizations);
    fillSelect('#f-gpu', filters.gpus);
    // sync the model prefilter (?model=) into the select box
    if (list.F.model) $('#f-model').value = list.F.model;
  }
  $('#q').addEventListener('input', e => { list.q = e.target.value.trim().toLowerCase(); list.page = 1; renderList(); });
  for (const [id, k] of [['#f-model', 'model'], ['#f-runtime', 'runtime'], ['#f-quant', 'quantization'], ['#f-gpu', 'gpu']])
    $(id).addEventListener('change', e => { list.F[k] = e.target.value; list.page = 1; renderList(); });
  $('#resetBtn').addEventListener('click', () => {
    list.q = ''; list.page = 1;
    for (const k in list.F) list.F[k] = '';
    $('#q').value = '';
    for (const id of ['#f-model', '#f-runtime', '#f-quant', '#f-gpu']) $(id).value = '';
    renderList();
  });
  $('#prevBtn').addEventListener('click', () => { list.page--; renderList(); });
  $('#nextBtn').addEventListener('click', () => { list.page++; renderList(); });
  // délégation : les th sont régénérés par chaque rendu du tableau
  $('#runs').addEventListener('click', e => {
    const th = e.target.closest('th[data-sort]');
    if (!th) return;
    const k = th.dataset.sort;
    if (list.sort.key === k) list.sort.dir *= -1; else { list.sort.key = k; list.sort.dir = k === 'date' ? -1 : 1; }
    list.page = 1; renderList();
  });
  await listLoad();
}

function safeGetFilters() {
  // démo statique : l'API répond 404 sur un hébergement sans serveur
  return getJSON(`${API}/filters`).catch(async e => {
    if (e instanceof TypeError || /fetch|404|load/i.test(e.message)) {
      const rows = await demoRuns();
      return rows.length ? demoFilters(rows) : null;
    }
    return null;
  });
}

function fillSelect(sel, values) {
  const s = $(sel), cur = s.value;
  s.innerHTML = s.querySelector('option').outerHTML + values.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
  s.value = cur;
}

async function listLoad() {
  const p = { page: 1, page_size: 200 };
  for (const k in list.F) if (list.F[k]) p[k] = list.F[k];
  try {
    const data = await getJSON(API, p);
    list.items = data.items;
    renderList();
  } catch (e) {
    // démo statique : API absente → jeu de démo local (seed.json)
    if (e instanceof TypeError || /fetch|404|load/i.test(e.message)) {
      const rows = (await demoRuns()).filter(d => demoFilter([d], p).length);
      list.items = rows.slice(0, 200);
      renderList();
      return;
    }
    showListError(e.message);
  }
}

function showListError(msg) {
  $('#runs').innerHTML = '';
  const b = $('#errorBox'); b.hidden = false; $('#errorText').textContent = `API injoignable — ${msg}. Lancez le backend : uvicorn app:app --port 8000`;
}

function clientFiltered() {
  let rows = list.items;
  if (list.q) rows = rows.filter(d => [d.model.name, d.runtime.name, d.quantization, d.hardware.gpu, d.status]
    .join(' ').toLowerCase().includes(list.q));
  const dir = list.sort.dir, key = list.sort.key;
  rows = [...rows].sort((a, b) => {
    if (key === 'date') return a.timestamp.localeCompare(b.timestamp) * dir;
    const va = SORTS[key](a), vb = SORTS[key](b);
    if (va == null && vb == null) return a.timestamp.localeCompare(b.timestamp);
    if (va == null) return 1;   // metric manquant : toujours en fin de liste
    if (vb == null) return -1;
    return (vb - va) * dir;
  });
  return rows;
}

function renderList() {
  const rows = clientFiltered();
  const total = rows.length, pages = Math.max(1, Math.ceil(total / PAGE));
  list.page = Math.min(list.page, pages);
  const start = (list.page - 1) * PAGE, pageRows = rows.slice(start, start + PAGE);
  renderSummary(rows);
  const top = [...rows].filter(d => d.metrics.generation_tok_s != null)
    .sort((a, b) => b.metrics.generation_tok_s - a.metrics.generation_tok_s).slice(0, 10);
  barChart($('#genChart'), top.map(d => ({ label: `${d.model.name} · ${d.runtime.name}`, value: d.metrics.generation_tok_s })));
  // dir=1 -> métriques décroissantes (plus grand en haut) ; date à l'inverse (dir=-1 -> plus récent en haut)
  const descNow = list.sort.key === 'date' ? list.sort.dir < 0 : list.sort.dir > 0;
  const as = k => list.sort.key === k ? (descNow ? 'descending' : 'ascending') : 'none';
  $('#runs').innerHTML = total ? (rows.some((_, i) => i < start + PAGE) ? (
    `<div class="table-wrap"><table class="cls-table"><caption class="sr-only">Runs filtrés et triables</caption><thead><tr>` +
    `<th>Modèle</th><th>Runtime</th><th>Quant</th><th>GPU</th>` +
    `<th data-sort="gen" aria-sort="${as('gen')}">Gen t/s</th><th data-sort="ttft" aria-sort="${as('ttft')}">TTFT</th><th data-sort="vram" aria-sort="${as('vram')}">VRAM</th>` +
    `<th data-sort="date" aria-sort="${as('date')}">Date</th><th>Statut</th></tr></thead><tbody>` +
    pageRows.map(d => {
      const m = d.metrics, best = d.metrics.generation_tok_s == (top[0] ? top[0].metrics.generation_tok_s : null);
      return `<tr><td><a href="/detail.html#/run/${esc(d.id)}">${esc(d.model.name)}${d.model.parameters ? `<span class="sub">${esc(d.model.parameters)}</span>` : ''}${d.example ? `<span class="sub"> ex</span>` : ''}</a></td>` +
        `<td>${esc(d.runtime.name)}</td><td>${esc(d.quantization)}</td><td>${esc(d.hardware.gpu)}</td>` +
        `<td class="num${best ? ' best' : ''}">${fmt(m.generation_tok_s, 1)}</td><td class="num">${fmt(m.ttft_s, 2)}</td>` +
        `<td class="num">${fmt(m.vram_peak_gb, 1)}</td><td class="num">${new Date(d.timestamp).toLocaleDateString('fr-FR')}</td>` +
        `<td>${statusBadge(d.status)}</td></tr>`;
    }).join('') + '</tbody></table></div>' +
    `<div class="run-cards">` + pageRows.map(d => {
      const m = d.metrics;
      return `<div class="run-card"><a href="/detail.html#/run/${esc(d.id)}" style="display:block">` +
        `<div class="run-title">${esc(d.model.name)} <span class="mono" style="color:var(--c-text-faint);font-weight:400">· ${esc(d.runtime.name)}</span></div>` +
        statusBadge(d.status) +
        `<dl style="margin-top:var(--sp-2)"><div class="kv"><dt>Gen</dt><dd>${fmt(m.generation_tok_s, 1)} t/s</dd></div>` +
        `<div class="kv"><dt>TTFT</dt><dd>${fmt(m.ttft_s, 2)} s</dd></div>` +
        `<div class="kv"><dt>VRAM</dt><dd>${fmt(m.vram_peak_gb, 1)} GB</dd></div></dl></a></div>`;
    }).join('') + '</div>') : '') :
    `<div class="empty-state"><div class="empty-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none"><path d="M21 21l-4.3-4.3M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></div>` +
    `<h3>Aucun run</h3><p>${total === 0 && list.items.length === 0 ? 'La base est vide pour l\'instant — insérez des runs via l\'API (POST /benchmarks).' : 'Aucun résultat avec ces filtres.'}</p>` +
    `<button class="btn btn--ghost btn--sm empty-cta" type="button" onclick="document.getElementById('resetBtn').click()">Réinitialiser les filtres</button></div>`;
  const pager = $('#pager');
  if (total > PAGE) {
    pager.hidden = false;
    $('#pagerInfo').textContent = `${start + 1}–${start + pageRows.length} sur ${total}`;
    $('#pagerPages').innerHTML = pagerButtons(pages);
    $('#prevBtn').disabled = list.page <= 1;
    $('#nextBtn').disabled = list.page >= pages;
  } else pager.hidden = true;
}

function pagerButtons(pages) {
  let h = '';
  const push = n => { h += `<button class="page-btn" type="button" ${n === list.page ? 'aria-current="true"' : ''} data-p="${n}">${n}</button>`; };
  const keep = new Set([1, pages]);
  for (let n = Math.max(2, list.page - 1); n <= Math.min(pages - 1, list.page + 1); n++) keep.add(n);
  let last = 0;
  for (let n = 1; n <= pages; n++) {
    if (n > 2 && n < pages && !keep.has(n)) {
      if (last !== 0 && last !== n - 1) h += '<span class="mono" style="color:var(--c-text-faint)">…</span>';
      last = 0;
      continue;
    }
    push(n); last = n;
  }
  $('#pagerPages').querySelectorAll('button').forEach(b => b.addEventListener('click', () => { list.page = +b.dataset.p; renderList(); }));
  return h;
}

/* 4 cartes résumé sur le jeu filtré */
function renderSummary(rows) {
  const withGen = rows.filter(d => d.metrics.generation_tok_s != null);
  const best = withGen.length ? Math.max(...withGen.map(d => d.metrics.generation_tok_s)) : null;
  const avg = (arr) => { const v = arr.filter(x => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
  const ttfts = rows.map(d => d.metrics.ttft_s), vrams = rows.map(d => d.metrics.vram_peak_gb);
  $('#summary').innerHTML = `<div class="stat-grid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
    <div class="stat-card"><div class="stat-label">Runs filtrés</div><div class="stat-value">${rows.length}</div><div class="stat-sub">sur ${list.items.length} au total</div></div>
    <div class="stat-card"><div class="stat-label">Gen max</div><div class="stat-value">${best == null ? '—' : fmt(best, 1)}</div><div class="stat-sub">t/s (meilleure gen)</div></div>
    <div class="stat-card"><div class="stat-label">TTFT moyen</div><div class="stat-value">${avg(ttfts) == null ? '—' : fmt(avg(ttfts), 2)}</div><div class="stat-sub">s</div></div>
    <div class="stat-card"><div class="stat-label">VRAM pic max</div><div class="stat-value">${avg(vrams) == null ? '—' : fmt(Math.max(...vrams.filter(v => v != null)), 1)}</div><div class="stat-sub">GB</div></div></div>`;
}

/* ================= VUE DÉTAIL (detail.html# / run) ================= */
async function detailInit() {
  initTheme();
  const box = $('#detail'), err = $('#errorBox');
  const runId = (location.hash.match(/#\/run\/(.+)$/) || [])[1];
  if (!runId) { location.replace('./'); return; }
  let d;
  try {
    d = await getJSON(`${API}/${encodeURIComponent(runId)}`);
  } catch (e) {
    // démo statique : API absente → jeu de démo local (seed.json)
    if (!(e instanceof TypeError || /fetch|404|load/i.test(e.message))) {
      box.innerHTML = '';
      err.hidden = false;
      $('#errorText').textContent = 'Erreur API — ' + e.message;
      return;
    }
    const found = (await demoRuns()).find(x => x.id === runId);
    if (!found) {
      box.innerHTML = '';
      err.hidden = false;
      $('#errorText').innerHTML = `Run introuvable : ${esc(runId)}. <a href="./">← Retour aux runs</a>`;
      return;
    }
    d = found;
  }
    const m = d.metrics, h = d.hardware;
    $('#crumb').textContent = d.id;
    const opt = v => v != null ? esc(v) : '<span style="color:var(--c-text-faint)">—</span>';
    box.innerHTML = `
    <div style="display:flex;align-items:center;gap:var(--sp-3);flex-wrap:wrap">
      <h2 style="font-size:var(--text-xl)">${esc(d.model.name)}${d.model.parameters ? `<span class="sub"> ${esc(d.model.parameters)}</span>` : ''}</h2>
      ${statusBadge(d.status)}
      ${d.example ? '<span class="badge badge--partial">exemple</span>' : ''}
      <span class="mono" style="color:var(--c-text-faint);font-size:var(--text-xs)">${esc(d.timestamp)}</span>
      <span class="spacer"></span>
      <button class="btn btn--ghost btn--sm" id="delBtn" type="button">Supprimer ce run</button>
    </div>
    <section class="stat-grid" style="margin-top:var(--sp-4); grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
      <div class="stat-card"><div class="stat-label">Gen</div><div class="stat-value">${m.generation_tok_s == null ? '—' : fmt(m.generation_tok_s, 1)}</div><div class="stat-sub">t/s</div></div>
      <div class="stat-card"><div class="stat-label">Prompt</div><div class="stat-value">${m.prompt_processing_tok_s == null ? '—' : fmt(m.prompt_processing_tok_s, 0)}</div><div class="stat-sub">t/s</div></div>
      <div class="stat-card"><div class="stat-label">TTFT</div><div class="stat-value">${m.ttft_s == null ? '—' : fmt(m.ttft_s, 2)}</div><div class="stat-sub">s</div></div>
      <div class="stat-card"><div class="stat-label">Durée</div><div class="stat-value">${m.duration_s == null ? '—' : fmtDur(m.duration_s)}</div><div class="stat-sub">totale</div></div>
    </section>
    <div class="card" style="overflow:hidden;margin-top:var(--sp-4)">
      <div class="card-pad" style="padding:var(--sp-3) 0"><div class="table-wrap"><table class="cmp-table" style="margin:0">
        <thead><tr><th>Contexte</th><th>Prompt tok</th><th>Gen tok</th><th>Runtime</th><th>Quant</th><th>VRAM pic / totale</th><th>Matériel</th><th>OS / CPU / RAM</th></tr></thead>
        <tbody><tr>
          <td class="num">${d.context_length.toLocaleString('fr-FR')}</td>
          <td class="num">${d.prompt_tokens.toLocaleString('fr-FR')}</td>
          <td class="num">${d.generation_tokens.toLocaleString('fr-FR')}</td>
          <td>${esc(d.runtime.name)}${d.runtime.version ? ` <span class="mono" style="color:var(--c-text-faint)">v${esc(d.runtime.version)}</span>` : ''}</td>
          <td>${esc(d.quantization)}</td>
          <td class="num">${fmt(m.vram_peak_gb, 1)} / ${opt(h.gpu_vram_total_gb)} GB</td>
          <td>${esc(h.gpu)}</td>
          <td>${[h.os, h.cpu, h.ram_gb != null ? h.ram_gb + ' GB' : null].filter(Boolean).map(esc).join(' · ') || '—'}</td>
        </tr></tbody>
      </table></div></div>
    </div>
    ${(d.command != null || d.agent_task) ? `<section class="card card-pad" style="margin-top:var(--sp-4)">
      ${d.command != null ? `<h4 style="font-size:var(--text-base);font-weight:600">Commande exacte</h4>
      <p style="margin:0; font-size:var(--text-xs); color:var(--c-text-faint)">Relance cette ligne pour reproduire le run.</p>
      <pre style="margin:var(--sp-2) 0 0; background:var(--c-surface-2); border:1px solid var(--c-border); border-radius:var(--r-md); padding:var(--sp-3); font-size:var(--text-xs); overflow-x:auto; white-space:pre-wrap; word-break:break-word">${esc(d.command)}</pre>` : ''}
      ${d.agent_task ? `<h4 style="font-size:var(--text-base);font-weight:600;margin-top:var(--sp-3)">Tâche agent (TTS)</h4>
      <p style="margin:var(--sp-2) 0 0">${esc(d.agent_task.name)} — ${d.agent_task.success ? 'résolue' : 'non résolue'}${d.agent_task.time_to_solution_s != null ? ` · TTS ${fmt(d.agent_task.time_to_solution_s, 2)} s` : ''}</p>` : ''}
    </section>` : ''}
    ${d.raw_output ? `<section class="card card-pad" style="margin-top:var(--sp-4)">
      <h4 style="font-size:var(--text-base);font-weight:600">Sortie brute</h4>
      <pre style="margin:var(--sp-2) 0 0; background:var(--c-surface-2); border:1px solid var(--c-border); border-radius:var(--r-md); padding:var(--sp-3); font-size:var(--text-xs); overflow-x:auto; white-space:pre-wrap; word-break:break-word">${esc(d.raw_output)}</pre>
    </section>` : ''}`;
    $('#delBtn').addEventListener('click', async () => {
      if (!confirm('Supprimer définitivement ce run ?')) return;
      try { await getJSON(`${API}/${encodeURIComponent(runId)}`, null, 'DELETE'); location.href = './'; }
      catch (e) { err.hidden = false; $('#errorText').textContent = 'Suppression impossible — ' + e.message; }
    });
}

/* ================= VUE COMPARAISON (compare.html) ================= */
const cmp = { sel: new Set() };
const CMP_ROWS = [
  { key: 'generation_tok_s', label: 'Gen t/s', dir: 1, d: 1 },
  { key: 'prompt_processing_tok_s', label: 'Prompt t/s', dir: 1, d: 0 },
  { key: 'ttft_s', label: 'TTFT (s)', dir: -1, d: 2 },
  { key: 'vram_peak_gb', label: 'VRAM pic (GB)', dir: -1, d: 1 },
  { key: 'duration_s', label: 'Durée (s)', dir: -1, d: 1 },
];

async function compareInit() {
  initTheme();
  let items = [];
  try {
    items = (await getJSON(API, { page_size: 200 })).items;
  } catch (e) {
    // démo statique : API absente → jeu de démo local (seed.json)
    if (e instanceof TypeError || /fetch|404|load/i.test(e.message)) {
      items = (await demoRuns()).slice(0, 200);
    } else { const b = $('#errorBox'); b.hidden = false; $('#errorText').textContent = 'API injoignable — ' + e.message; return; }
  }
  if (!items.length) {
    $('#runList').innerHTML = '<div class="empty-state" style="grid-column:1/-1"><h3>Base vide</h3><p>Aucun run à comparer — insérez d\'abord des runs via l\'API.</p></div>';
    return;
  }
  const shortId = d => d.id.length > 14 ? d.id.slice(0, 8) + '…' : d.id;
  $('#runList').innerHTML = items.map(d => `
    <label class="select-item"><input type="checkbox" value="${esc(d.id)}">
      <span class="run-title" style="font-size:var(--text-sm)">${esc(d.model.name)}<span class="sel-sub">${esc(d.runtime.name)} · ${shortId(d)}</span></span>
    </label>`).join('');
  const refresh = () => {
    const boxes = $$('#runList input:checked');
    boxes.slice(5).forEach(c => { c.checked = false; });
    cmp.sel = new Set(boxes.slice(0, 5).map(c => c.value));
    $('#selCount').textContent = `${cmp.sel.size} / 5`;
    $('#goBtn').disabled = cmp.sel.size < 2;
    $('#goBtn').textContent = `Comparer (${cmp.sel.size})`;
  };
  $$('#runList input').forEach(c => c.addEventListener('change', refresh));
  $('#goBtn').addEventListener('click', runCompare);
  refresh();
}

async function runCompare() {
  const ids = [...cmp.sel];
  const err = $('#errorBox'); err.hidden = true;
  $('#compareResult').hidden = true;
  let res;
  try {
    res = await getJSON(`${API}/compare`, { ids: ids.join(',') });
  } catch (e) {
    // démo statique : compare sur le jeu de démo local
    if (e instanceof TypeError || /fetch|404|load/i.test(e.message)) {
      const all = await demoRuns();
      const found = all.filter(d => ids.includes(d.id));
      renderCompare(found);
      return;
    }
    err.hidden = false; $('#errorText').textContent = e.message;
    return;
  }
  if (res.missing.length) {
    err.hidden = false;
    $('#errorText').innerHTML = `Runs introuvables : <span class="mono">${res.missing.map(esc).join(', ')}</span> — exclus de la comparaison.`;
  }
  renderCompare(res.runs);
}

/* rend la comparaison (table + scatter + TTFT) — partagé API / démo statique */
function renderCompare(found) {
  const runs = found.map((d, i) => ({ d, color: CH_COLORS[i % CH_COLORS.length],
    label: `${d.model.name} · ${d.runtime.name}`, id: d.id,
    gen: d.metrics.generation_tok_s, vram: d.metrics.vram_peak_gb, ttft: d.metrics.ttft_s }));
  renderCmpTable(runs);
  scatter($('#scatter'), runs, $('#scatterLegend'));
  ttftChart($('#ttftChart'), runs);
  $('#compareResult').hidden = false;
  $('#compareResult').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function deltaCell(ref, v, dir) {
  if (ref == null || v == null) return '';
  const pct = Math.round((v - ref) / ref * 100);
  if (!pct) return '<span class="delta">0%</span>';
  const good = (pct > 0) === (dir > 0);
  return `<div class="delta ${good ? 'up' : 'down'}">${pct > 0 ? '+' : ''}${pct}%</div>`;
}

function renderCmpTable(runs) {
  const ths = runs.map((r, i) => `<th class="num"><span class="run-head"><i style="background:${r.color}"></i><span>${esc(r.label)}<br><span class="mono" style="font-size:var(--text-xs);color:var(--c-text-faint)">${esc(r.id)}</span></span></span></th>`).join('');
  const body = CMP_ROWS.map(row => {
    const vals = runs.map(r => r.d.metrics[row.key]);
    const refV = vals[0];
    return `<tr><td style="font-weight:500">${row.label}</td>` + vals.map((v, i) =>
      `<td class="num">${fmt(v, row.d)}${i === 0 ? '' : deltaCell(refV, v, row.dir)}</td>`).join('') + '</tr>';
  }).join('');
  const metaRows = (label, get) => `<tr><td style="font-weight:500">${label}</td>` + runs.map(r =>
    `<td>${esc(get(r.d) ?? '—')}</td>`).join('') + '</tr>';
  $('#cmpTable').innerHTML = `<div class="table-wrap"><table class="cmp-table"><thead><tr><th>Métrique</th>${ths}</tr></thead>
    <tbody>${body}
    ${metaRows('Runtime', d => d.runtime.name + (d.runtime.version ? ' ' + d.runtime.version : ''))}
    ${metaRows('Quant', d => d.quantization)}
    ${metaRows('Contexte (tok)', d => d.context_length.toLocaleString('fr-FR'))}
    ${metaRows('GPU', d => d.hardware.gpu)}
    ${metaRows('Statut', d => d.status)}
    </tbody></table></div>`;
}

/* ================= VUE MODÈLES (models.html) ================= */
async function modelsInit() {
  initTheme();
  let items = [];
  try {
    items = (await getJSON(API, { page_size: 200 })).items;
  } catch (e) {
    // démo statique : API absente → jeu de démo local (seed.json)
    if (e instanceof TypeError || /fetch|404|load/i.test(e.message)) {
      items = (await demoRuns()).slice(0, 200);
    } else { const b = $('#errorBox'); b.hidden = false; $('#errorText').textContent = 'API injoignable — ' + e.message; return; }
  }
  if (!items.length) {
    $('#models').innerHTML = '<div class="empty-state" style="padding:var(--sp-4)"><h3>Base vide</h3><p>Aucun run — insérez des runs via l\'API (POST /benchmarks).</p></div>';
    return;
  }
  // agrégation par modèle : best gen, mean TTFT, max VRAM, counts
  const byModel = {};
  for (const d of items) {
    const g = (byModel[d.model.name] ||= { name: d.model.name, runs: 0, err: 0, ex: 0, gens: [], ttfts: [], vrams: [], variants: new Set() });
    g.runs++; if (d.status === 'error') g.err++; if (d.example) g.ex++;
    g.variants.add(`${d.runtime.name} · ${d.quantization}`);
    if (d.metrics.generation_tok_s != null) g.gens.push(d.metrics.generation_tok_s);
    if (d.metrics.ttft_s != null) g.ttfts.push(d.metrics.ttft_s);
    if (d.metrics.vram_peak_gb != null) g.vrams.push(d.metrics.vram_peak_gb);
  }
  const avg = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : null;
  const rows = Object.values(byModel).sort((a, b) =>
    (b.gens.length ? Math.max(...b.gens) : -1) - (a.gens.length ? Math.max(...a.gens) : -1));
  $('#models').innerHTML = `
    <div class="table-wrap"><table class="cls-table"><caption class="sr-only">Synthèse par modèle</caption>
    <thead><tr><th>Modèle</th><th>Runs</th><th>Best Gen</th><th>TTFT moyen</th><th>VRAM pic max</th><th>Variants (runtime · quant)</th></tr></thead>
    <tbody>${rows.map(g => {
      const best = g.gens.length ? Math.max(...g.gens) : null;
      return `<tr>
        <td><a href="/?model=${encodeURIComponent(g.name)}">${esc(g.name)}</a>${g.ex ? `<span class="sub"> ex</span>` : ''}</td>
        <td class="num">${g.runs}${g.err ? ` <span class="sub">${g.err} en erreur</span>` : ''}</td>
        <td class="num">${fmt(best, 1)}</td>
        <td class="num">${fmt(avg(g.ttfts), 2)}</td>
        <td class="num">${g.vrams.length ? fmt(Math.max(...g.vrams), 1) : '—'}</td>
        <td>${[...g.variants].map(esc).join('<br>')}</td></tr>`;
    }).join('')}</tbody></table></div>`;
}

/* ================= boot ================= */
const page = location.pathname;
const booted = /index\.html$|\/$/.test(page) ? listInit()
  : page.includes('detail') ? detailInit()
  : page.includes('models') ? modelsInit()
  : page.includes('compare') ? compareInit() : null;
if (booted) booted.catch(e => { const b = $('#errorBox'); if (b) { b.hidden = false; $('#errorText').textContent = e.message; } });
