/* Request telemetry stays on the user's computer. No metrics are fetched from GitHub. */
(() => {
  initTheme();
  const endpoint = 'http://127.0.0.1:8765/api/requests';
  const byId = id => document.getElementById(id);
  let allRows = [];
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
    byId('count').textContent = format(rows.length, 0);
    byId('speed').textContent = format(median(rows.map(row => row.tokensPerSecond)), 1);
    byId('ttft').textContent = milliseconds(median(rows.map(row => row.ttftMs)));
    byId('total').textContent = milliseconds(median(rows.map(row => row.totalMs)));
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
      const response = await fetch(endpoint, {cache: 'no-store', targetAddressSpace: 'loopback'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!Array.isArray(data.rows)) throw new Error('Réponse invalide');
      allRows = data.rows;
      render();
      byId('connection').textContent = data.sourceStatus === 'ok' ? 'Local · connecté' : 'Journal inaccessible';
      byId('bridgeHelp').hidden = data.sourceStatus === 'ok';
      byId('updated').textContent = `Mis à jour à ${new Date(data.updatedAt).toLocaleTimeString('fr-FR')} · actualisation toutes les 5 secondes`;
    } catch (_) {
      byId('connection').textContent = 'Local · déconnecté';
      byId('bridgeHelp').hidden = false;
      byId('updated').textContent = 'En attente du service local';
    } finally {
      loading = false;
    }
  }

  byId('period').addEventListener('change', render);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  refresh();
  setInterval(() => { if (!document.hidden) refresh(); }, 5000);
})();
