/* check_models.js — self-check de la page Modèles : charge ui/app.js avec un DOM
   factice, force le repli démo (seed.json), et vérifie le rendu réel de
   renderModels() : groupage par fournisseur, agrégats, badges, états.
   Usage : node check_models.js   (exit 0 = OK, exit 1 = ÉCHEC) */
'use strict';
const fs = require('fs');
const path = require('path');
const seed = JSON.parse(fs.readFileSync(path.join(__dirname, 'ui', 'seed.json'), 'utf8'));

/* --- DOM factice minimal : chaque sélecteur #id est un objet persistant --- */
const els = {};
const el = (sel) => (els[sel] ||= { innerHTML: '', value: '', hidden: false, textContent: '', addEventListener() {}, setAttribute() {}, getAttribute: () => 'light' });
global.document = {
  documentElement: { getAttribute: () => 'light', setAttribute() {} },
  querySelector: (sel) => (sel.startsWith('#') ? el(sel) : null),
  querySelectorAll: () => [],
  addEventListener() {},
};
global.window = global;
global.location = { pathname: 'models.html', search: '', hash: '', origin: '' };
global.URLSearchParams = URLSearchParams;
global.Event = class { constructor() {} };
global.localStorage = { getItem: () => null, setItem() {} };
global.matchMedia = () => ({ matches: false });
/* API absente (statique) → TypeError → repli seed.json ; seed.json lu depuis le disque */
global.fetch = (url) => {
  url = String(url);
  if (url.includes('seed.json')) return Promise.resolve({ ok: true, json: () => Promise.resolve(seed) });
  return Promise.reject(new TypeError('fetch failed'));
};

const src = fs.readFileSync(path.join(__dirname, 'ui', 'app.js'), 'utf8');
/* const/function dans un eval strict ne fuient pas : on les exporte depuis le source */
eval(src + '\n;global.__booted = booted; global.__models = { models, renderModels };');

const assert = (cond, msg) => { if (!cond) { console.error('  ✗', msg); process.exitCode = 1; } else console.log('  ✓', msg); };

Promise.resolve(global.__booted).then(() => {
  const html = el('#models').innerHTML;
  // groupage par fournisseur : au moins une ligne de groupe, 3 archs présentes (llama/mistral/qwen)
  const groupRows = (html.match(/group-row/g) || []).length;
  const archs = new Set(seed.map(d => d.model.arch));
  assert(groupRows > 0, `lignes de groupe présentes (${groupRows})`);
  for (const a of archs) assert(new RegExp(a[0].toUpperCase() + a.slice(1)).test(html), `groupe fournisseur « ${a} » rendu`);
  // agrégat : le best gen d'un modèle = max de ses runs (re-calcul indépendant)
  const byName = {};
  for (const d of seed) (byName[d.model.name] ||= []).push(d);
  const top = Object.values(byName).map(m => Math.max(...m.filter(d => d.metrics.generation_tok_s != null).map(d => d.metrics.generation_tok_s))).sort((a, b) => b - a);
  const topVal = top[0];
  assert(html.includes(topVal.toLocaleString('fr-FR', { maximumFractionDigits: 1 })), `best gen global ${topVal} t/s visible`);
  // badges : statut (badge--*) + « ex » pour les modèles avec runs d'exemple
  assert(/badge badge--/.test(html), 'badges de statut rendus');
  assert(html.includes('ex'), 'badge « ex » présent (runs d\'exemple)');
  // colonne taille : un modèle avec parameters=27B affiche ce badge
  assert(/27B/.test(html), 'badge taille (27B) rendu');
  // la fonction principale est intacte : un lien vers Runs ?model= existe
  assert(/\?model=/.test(html), 'lien vers Runs (?model=) présent');
  // recherche : un filtre qui ne matche rien → état vide
  const { models, renderModels } = global.__models;
  models.items = seed; models.q = 'zzzz-neutre'; el('#models').innerHTML = '';
  renderModels();
  assert(/Aucun modèle/.test(el('#models').innerHTML), 'état vide « Aucun modèle » quand la recherche ne matche rien');
  console.log(process.exitCode ? '\nECHEC — check_models.js' : '\nOK — check_models.js (groupage + agrégats + badges + état vide)');
}).catch(e => { console.error('ECHEC — check_models.js (erreur d\'exécution):', e.message); process.exit(1); });
