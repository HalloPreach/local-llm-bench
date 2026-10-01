/* Public snapshot contains only timing metrics, token counts and status. */
(() => {
  initTheme();
  const endpoint = './data/requests.json';
  const byId = id => document.getElementById(id);
  let allRows = [];
  let summaries = {};
  let loading = false;

  const format = (value, digits = 1) => value == null ? '—' : Number(value).toLocaleString('fr-FR', {maximumFractionDigits: digits});
  const median = values => {
    const sorted = values.filter(v => typeof v === 'number' && Number.isFinite(v)).sort((a, b) => a - b);
    const n = sorted.length;
    return n ? (sorted[Math.floor((n - 1) / 2)] + sorted[Math.floor(n / 2)]) / 2 : null;
  };
  const milliseconds = value => value == null ? '—' : value >= 1000 ? `${format(value / 1000, 2)} s` : `${format(value, 0)} ms`;

  function render() {
    const period = byId('period').value;
    const cutoff = period === 'all' ? -Infinity : Date.now() - Number(period);
    const rows = allRows.filter(row => Number(row.time) >= cutoff);
    const summary = summaries[period];
    byId('count').textContent = format(summary ? summary.count : rows.length, 0);
    byId('speed').textContent = format(summary ? summary.tokensPerSecond : median(rows.map(row => row.tokensPerSecond)), 1);
    byId('ttft').textContent = milliseconds(summary ? summary.ttftMs : median(rows.map(row => row.ttftMs)));
    byId('total').textContent = milliseconds(summary ? summary.totalMs : median(rows.map(row => row.totalMs)));
    const body = byId('requestRows');
    body.replaceChildren();
    if (!rows.length) {
      const tr = body.insertRow();
      tr.insertCell().colSpan = 6;
      tr.cells[0].textContent = 'Aucune requête sur cette période.';
      return;
    }
    for (const row of rows.slice(0, 200)) {
      const tr = body.insertRow();
      const fields = [
        new Date(Number(row.time)).toLocaleString('fr-FR'),
        row.status === 'ok' ? 'Terminée' : 'Erreur',
        row.tokensPerSecond == null ? '—' : `${format(row.tokensPerSecond, 1)} t/s`,
        milliseconds(row.ttftMs), milliseconds(row.totalMs),
        `${format(row.promptTokens, 0)} / ${format(row.outputTokens, 0)}`,
      ];
      for (const field of fields) tr.insertCell().textContent = field;
    }
  }

  async function refresh() {
    if (loading) return;
    loading = true;
    try {
      const response = await fetch(endpoint, {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!Array.isArray(data.rows)) throw new Error('Réponse invalide');
      allRows = data.rows;
      summaries = data.summaryByPeriod || {};
      render();
      const stale = Date.now() - data.updatedAt > 20 * 60 * 1000;
      byId('connection').textContent = stale ? 'Dernière synchronisation ancienne' : 'Synchronisé · GitHub';
      byId('bridgeHelp').hidden = data.sourceStatus === 'ok';
      byId('updated').textContent = `Synchronisé le ${new Date(data.updatedAt).toLocaleString('fr-FR')} · 200 lignes affichées, 1 000 dernières disponibles · indicateurs sur tout le journal`;
    } catch (_) {
      byId('connection').textContent = 'Données indisponibles';
      byId('bridgeHelp').hidden = false;
      byId('updated').textContent = 'Impossible de lire la dernière synchronisation';
    } finally {
      loading = false;
    }
  }

  byId('period').addEventListener('change', render);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  refresh();
  setInterval(() => { if (!document.hidden) refresh(); }, 30000);
})();
