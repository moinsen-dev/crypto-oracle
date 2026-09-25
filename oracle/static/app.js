const $ = (id) => document.getElementById(id);
const state = {asset: 'BTC', horizon: 24, scope: 'live', model: 'timesfm', data: null, request: 0};
const names = {BTC: 'Bitcoin', ETH: 'Ethereum', SOL: 'Solana'};
const icons = {BTC: '₿', ETH: 'Ξ', SOL: '≋'};
const models = {persistence: 'Kurs unverändert', momentum: 'Momentum', timesfm: 'TimesFM 2.5', fusion_market: 'TimesFM + Markt', fusion_news: 'TimesFM + Nachrichten'};
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = (n, digits = 2) => n == null ? '—' : Number(n).toLocaleString('de-DE', {minimumFractionDigits: digits, maximumFractionDigits: digits});
const price = (n) => num(n) + (n == null ? '' : ' USDT');
const percent = (n) => n == null ? '—' : (n > 0 ? '+' : '') + num(n * 100, 2) + ' %';
const date = (n, full = false) => n == null ? '—' : new Date(n * 1000).toLocaleString('de-DE', {day: '2-digit', month: '2-digit', ...(full ? {year: 'numeric'} : {}), hour: '2-digit', minute: '2-digit'});
const signClass = (n) => n == null ? '' : n >= 0 ? 'positive' : 'negative';

async function load() {
  const request = ++state.request;
  $('refresh').disabled = true;
  try {
    const response = await fetch(`/api/dashboard?asset=${state.asset}&horizon=${state.horizon}&scope=${state.scope}`);
    if (!response.ok) throw new Error(`Der Server antwortet mit Status ${response.status}.`);
    const data = await response.json();
    if (request !== state.request) return;
    state.data = data;
    $('error-banner').hidden = true;
    render();
  } catch (error) {
    if (request !== state.request) return;
    $('error-banner').textContent = `${error.message} Bereits angezeigte Daten können veraltet sein.`;
    $('error-banner').hidden = false;
    $('connection').textContent = 'Verbindung unterbrochen';
    $('connection').className = 'connection warning';
  } finally { if (request === state.request) $('refresh').disabled = false; }
}

function render() {
  const d = state.data;
  const a = d.assets.find(a => a.asset === state.asset);
  const worker = d.jobs.find(j => j.name === 'worker');
  const healthy = worker && worker.last_success && d.now - worker.last_success < 2100 && !worker.last_error;
  $('connection').textContent = healthy ? 'Sammler aktiv' : worker?.last_error ? 'Betrieb eingeschränkt' : 'Sammler nicht bestätigt';
  $('connection').className = 'connection ' + (healthy ? 'healthy' : 'warning');
  $('asset-list').innerHTML = d.assets.map(a => `<button class="asset-button ${a.asset === state.asset ? 'active' : ''}" data-asset="${a.asset}" aria-pressed="${a.asset === state.asset}"><span class="coin-icon ${a.asset.toLowerCase()}">${icons[a.asset]}</span><span><span class="asset-line"><strong>${a.asset}</strong><span class="muted">${names[a.asset]}</span></span><span class="asset-price">${num(a.price)}</span> <span class="asset-change ${signClass(a.change)}">${percent(a.change)}</span></span></button>`).join('');
  const hasHoldings = d.assets.some(a => a.holding);
  const missingPrice = d.assets.some(a => a.holding && a.price == null);
  const total = d.assets.reduce((s, a) => s + (a.holding?.quantity || 0) * (a.price || 0), 0);
  const pnl = d.assets.reduce((s, a) => s + (a.holding?.average_cost != null && a.price != null ? (a.price - a.holding.average_cost) * a.holding.quantity : 0), 0);
  const withCost = d.assets.filter(a => a.holding?.average_cost != null).length;
  const holdingCount = d.assets.filter(a => a.holding).length;
  $('portfolio-value').textContent = hasHoldings ? missingPrice ? 'Preise fehlen' : price(total) : '— USDT';
  $('portfolio-pnl').textContent = hasHoldings ? withCost ? `${price(pnl)} Ergebnis${withCost < holdingCount ? ' (nur bekannte Einstandskurse)' : ''}` : 'Einstandskurse noch offen' : 'Bestände manuell hinzufügen';
  $('holding-value').textContent = a.holding ? price(a.holding.quantity * (a.price || 0)) : 'Noch kein Bestand';
  $('holding-quantity').textContent = a.holding ? `${num(a.holding.quantity, 6)} ${a.asset}${a.holding.average_cost != null ? ' · Ø ' + price(a.holding.average_cost) : ''}` : 'Menge und Einstandskurs hinterlegen.';
  $('evaluated-count').textContent = num(d.counts.evaluations, 0);
  $('news-count').textContent = num(d.counts.news, 0);
  $('selected-name').textContent = names[state.asset];
  $('selected-symbol').textContent = state.asset + ' / USDT';
  $('selected-icon').textContent = icons[state.asset];
  $('selected-icon').className = 'coin-icon ' + state.asset.toLowerCase();
  $('current-price').textContent = num(a.price);
  $('daily-change').textContent = percent(a.change) + ' / 24 h';
  $('daily-change').className = 'change ' + signClass(a.change);
  $('price-status').textContent = `Binance Spot · USDT · Kerzenschluss ${date(a.price_at)}${a.price_at && d.now - a.price_at > 7200 ? ' · VERALTET' : ''}`;
  const f = d.forecasts.find(f => f.model === state.model);
  $('legend-model').textContent = models[state.model];
  $('legend-band').hidden = f?.lower == null;
  $('forecast-notice').hidden = !!f;
  $('forecast-notice').textContent = state.model.startsWith('fusion') ? 'Dieses Kombinationsmodell wartet auf genügend prospektive Trainingsdaten. Es wird noch keine angepasste Prognose ausgegeben.' : 'Für dieses Modell liegt noch keine aktuelle Prognose vor. Details im Betriebsstatus.';
  if (f && d.now - f.origin > 7200) { $('forecast-notice').hidden = false; $('forecast-notice').textContent = 'Diese Prognose ist veraltet. Prüfe den Sammler im Betriebsstatus.'; }
  $('forecast-price').textContent = f ? num(f.prediction) : '—';
  $('forecast-target').textContent = f ? date(f.target, true) : 'Noch keine Prognose';
  $('forecast-change').textContent = f ? percent(f.prediction / f.base - 1) : '—';
  $('forecast-change').className = f ? signClass(f.prediction / f.base - 1) : '';
  $('forecast-origin').textContent = f ? 'Start: ' + date(f.origin) : '—';
  $('forecast-range').textContent = f?.lower != null ? `${num(f.lower)} – ${num(f.upper)}` : '—';
  drawChart(d.chart, f);
  const layaJob = d.jobs.find(j => j.name === 'laya-news');
  const layaDetail = layaJob ? JSON.parse(layaJob.detail || '{}') : {};
  const layaStatus = {disabled:'noch nicht aktiviert', active:'aktiv'};
  $('laya-status').textContent = `Laya ${layaJob?.last_error ? 'Einordnung gestört' : layaStatus[layaDetail.state] || 'wartet auf ersten Lauf'} · ${num(d.laya?.evaluated || 0,0)} Titel eingeordnet`;
  $('news-list').innerHTML = d.news.length ? d.news.map(n => {
    const tone = n.sentiment == null ? 'Einordnung ausstehend' : n.sentiment > .3 ? 'Positive Tonalität' : n.sentiment < -.3 ? 'Negative Tonalität' : 'Neutrale Tonalität';
    return `<article class="news-item"><div class="news-meta"><span>${esc(n.source)}</span><time>${date(n.published_at || n.first_seen)}</time></div><a href="${esc(n.url)}" target="_blank" rel="noopener noreferrer">${esc(n.title)} ↗</a><div class="news-tags"><span>${esc(n.event_type)}</span><span class="${n.sentiment == null ? '' : signClass(n.sentiment)}">FinBERT: ${tone}</span></div>${layaAnnotation(n.laya)}<div class="news-meta"><span>Erfasst ${date(n.first_seen)}</span></div></article>`;
  }).join('') : '<div class="empty"><strong>Noch keine passenden Meldungen.</strong>Der Sammler ergänzt neue Quellenfunde automatisch.</div>';
  const fusionReady = d.forecasts.some(f => f.model === 'fusion_news');
  $('fusion-badge').textContent = fusionReady ? 'Experiment läuft' : 'Sammelphase';
  $('fusion-status').textContent = fusionReady ? 'Marktmerkmale und zusätzliche Nachrichten werden als getrennte Modelle bewertet. Ein Vorteil ist noch nicht bewiesen.' : `${d.fusion.samples} von mindestens ${d.fusion.required_samples} ausgereiften Prognosen mit Nachrichtenabdeckung · ${num(d.fusion.span_days, 0)} von mindestens ${d.fusion.required_days} Tagen. Zusätzlich werden unterschiedliche Ereignisse benötigt.`;
  $('metrics-description').textContent = state.scope === 'live' ? `Live-Experiment · ${state.horizon} Stunden. Nur tatsächlich vorher ausgegebene und inzwischen abgeschlossene Prognosen. Vergleich jeweils auf identischen Startzeitpunkten.` : `Explorativer historischer Rücktest · ${state.horizon} Stunden. Keine Nachrichten rückwirkend ergänzt. Ein Rücktest ist kein Nachweis für zukünftige Qualität.`;
  renderMetrics(d.metrics);
  renderJournal(d.journal);
  $('export').href = '/api/export.csv?scope=' + state.scope;
  $('jobs').innerHTML = '<div class="jobs-grid">' + d.jobs.map(j => `<div class="job ${j.last_error ? 'error' : ''}"><strong>${esc(j.name)}</strong><small>Letzter Erfolg: ${date(j.last_success, true)}</small>${j.last_error ? `<small>${esc(j.last_error)}</small>` : '<span>Kein gemeldeter Fehler</span>'}</div>`).join('') + '</div>';
  $('last-updated').textContent = `Aktualisiert ${date(d.now)} · ${d.experiment}`;
}

function layaAnnotation(laya) {
  if (!laya) return '<div class="news-meta">Laya: noch keine Einordnung</div>';
  const tones = {positive:'positiv',negative:'negativ',neutral:'neutral',unclear:'unklar'};
  const events = {security:'Sicherheitsvorfall',regulation:'Regulierung',network:'Netzwerk',exchange:'Börse',market:'Markt',other:'Sonstiges'};
  const a = laya.answers;
  return `<div class="news-tags"><span>Laya: ${esc(tones[a.tone.choice])}</span><span>${esc(events[a.event.choice])}</span></div><div class="news-meta">${state.asset}-Bezug: ${num(a[state.asset].probability*100,0)} % · Ereignisrelevanz: ${num(a.material.probability*100,0)} %</div><div class="news-meta">Laya bewertet ${date(laya.evaluated_at)}</div>`;
}

function drawChart(candles, forecast) {
  if (!candles.length) { $('chart').innerHTML = '<div class="empty"><strong>Der erste Kursabruf steht noch aus.</strong>Der Sammler benötigt 512 zusammenhängende Stundenwerte.</div>'; return; }
  const candlesView = candles.slice(-(state.horizon === 24 ? 72 : 120));
  const history = candlesView.map(c => ({t: c.ts, p: c.close}));
  const points = forecast ? [{t: forecast.origin, p: forecast.base, lo: forecast.base, hi: forecast.base}, ...forecast.path] : [];
  const all = [...history, ...points];
  let ymin = Math.min(...all.map(p => p.lo ?? p.p)), ymax = Math.max(...all.map(p => p.hi ?? p.p));
  const pad = Math.max((ymax - ymin) * .18, ymax * .002); ymin -= pad; ymax += pad;
  const xmin = history[0].t, xmax = Math.max(history.at(-1).t, points.at(-1)?.t || 0);
  const w = 720, h = 250, left = 0, right = 64, top = 18, bottom = 32;
  const x = t => left + (t - xmin) / Math.max(1, xmax - xmin) * (w - left - right);
  const y = v => top + (ymax - v) / (ymax - ymin) * (h - top - bottom);
  const path = p => p.map((q, i) => `${i ? 'L' : 'M'}${x(q.t).toFixed(2)},${y(q.p).toFixed(2)}`).join(' ');
  let svg = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${names[state.asset]}: Kursverlauf${forecast ? ' und ' + models[state.model] + ' Prognose' : ''}"><title>Kursverlauf und Prognose in USDT. Exakte Zielwerte stehen unter dem Diagramm.</title>`;
  for (let i = 0; i <= 4; i++) { const val = ymin + (ymax - ymin) * i / 4; svg += `<line x1="0" x2="${w-right}" y1="${y(val)}" y2="${y(val)}" stroke="#edf0e8"/><text x="${w-right+12}" y="${y(val)+4}">${num(val, val < 1000 ? 1 : 0)}</text>`; }
  for (let i = 0; i < 4; i++) { const t = xmin + (xmax-xmin) * i / 3; svg += `<text x="${x(t)}" y="${h-5}" text-anchor="${i === 0 ? 'start' : 'middle'}">${new Date(t*1000).toLocaleString('de-DE',{day:'2-digit',month:'2-digit',hour:'2-digit'})}</text>`; }
  if (points.length) {
    svg += `<line x1="${x(forecast.origin)}" x2="${x(forecast.origin)}" y1="9" y2="${h-bottom}" stroke="#c2cbb8" stroke-dasharray="3 5"/><text x="${Math.max(0,x(forecast.origin)-5)}" y="11" text-anchor="end">Prognosestart</text>`;
    if (points.every(p => p.lo != null && p.hi != null)) {
      const polygon = points.map(p => `${x(p.t)},${y(p.lo)}`).concat([...points].reverse().map(p => `${x(p.t)},${y(p.hi)}`)).join(' ');
      svg += `<polygon points="${polygon}" fill="#e6eedb" opacity=".85"/>`;
    } else if (forecast.lower != null) { const last = points.at(-1); svg += `<line x1="${x(last.t)}" x2="${x(last.t)}" y1="${y(last.lo)}" y2="${y(last.hi)}" stroke="#a9bf8e" stroke-width="5"/>`; }
    svg += `<path d="${path(points)}" fill="none" stroke="#86a063" stroke-width="2.2" stroke-dasharray="5 4"/>`;
  }
  svg += `<path d="${path(history)}" fill="none" stroke="#46684f" stroke-width="2.4" stroke-linejoin="round"/>`;
  const last = history.at(-1); svg += `<circle cx="${x(last.t)}" cy="${y(last.p)}" r="4" fill="#46684f" stroke="white" stroke-width="2"/>`;
  $('chart').innerHTML = svg + '</svg>';
}

function renderMetrics(rows) {
  if (!rows.length) { $('metrics').innerHTML = `<div class="empty"><strong>${state.scope === 'live' ? 'Die ersten Prognosen müssen noch reifen.' : 'Noch kein abgeschlossener Rücktest.'}</strong>${state.scope === 'live' ? `Nach ${state.horizon} Stunden vergleichen wir die Prognosen automatisch mit dem beobachteten Kurs.` : 'Ein Rücktest erscheint hier, sobald er ausgeführt wurde.'}</div>`; return; }
  const hasNews = rows.some(r => r.model === 'fusion_news');
  $('metrics').innerHTML = '<table><thead><tr><th>Coin / Modell</th><th>Prognosen</th><th>Fehler ↓</th><th>Vorteil zur Basis ↑</th>' + (hasNews ? '<th>News vs. Markt ↑</th>' : '') + '<th>Richtung</th><th>Bandabdeckung</th></tr></thead><tbody>' + rows.map(r => `<tr><td><span class="muted">${r.asset}</span> <span class="model-label">${models[r.model] || esc(r.model)}</span></td><td>${r.n} <span class="muted">/ ${r.calendar_days} Kalendertage</span></td><td>${num(r.mae*100,3)} Pp.</td><td class="${signClass(r.improvement)}">${r.model === 'persistence' ? 'Referenz' : percent(r.improvement)}</td>${hasNews ? `<td class="${signClass(r.news_lift_vs_market)}">${percent(r.news_lift_vs_market)}</td>` : ''}<td>${r.direction == null ? '—' : num(r.direction*100,1)+' %'}</td><td>${r.coverage == null ? '—' : num(r.coverage*100,1)+' %'}</td></tr>`).join('') + '</tbody></table>';
}

function renderJournal(rows) {
  if (!rows.length) { $('journal-table').innerHTML = '<div class="empty"><strong>Das Journal ist noch leer.</strong>Neue Prognosen werden hier dauerhaft mit ihrem Startzeitpunkt gespeichert.</div>'; return; }
  $('journal-table').innerHTML = '<table><thead><tr><th>Prognosestart</th><th>Modell</th><th>Zielzeitpunkt</th><th>Prognose</th><th>Tatsächlich</th><th>Fehler</th></tr></thead><tbody>' + rows.map(r => `<tr><td>${date(r.origin)}</td><td>${models[r.model] || esc(r.model)}</td><td>${date(r.target)}</td><td>${num(r.prediction)}</td><td>${r.actual == null ? '<span class="pending">Noch offen</span>' : num(r.actual)}</td><td>${r.absolute_log_error == null ? '—' : num(r.absolute_log_error*100,3)+' Pp.'}</td></tr>`).join('') + '</tbody></table>';
}

function toast(message) { $('toast').textContent = message; $('toast').hidden = false; setTimeout(() => { $('toast').hidden = true; }, 3500); }
$('asset-list').addEventListener('click', e => { const b = e.target.closest('[data-asset]'); if (b) { state.asset = b.dataset.asset; load(); } });
$('horizon-control').addEventListener('click', e => { const b = e.target.closest('[data-horizon]'); if (!b) return; state.horizon = Number(b.dataset.horizon); for (const x of b.parentElement.children) { x.classList.toggle('active', x === b); x.setAttribute('aria-pressed', x === b); } load(); });
$('scope-control').addEventListener('click', e => { const b = e.target.closest('[data-scope]'); if (!b) return; state.scope = b.dataset.scope; for (const x of b.parentElement.children) { x.classList.toggle('active', x === b); x.setAttribute('aria-pressed', x === b); } load(); });
$('forecast-model').addEventListener('change', e => { state.model = e.target.value; if (state.data) render(); });
$('refresh').addEventListener('click', load);
$('edit-holding').addEventListener('click', () => {
  if (!state.data) return;
  const a = state.data.assets.find(a => a.asset === state.asset);
  $('dialog-title').textContent = names[state.asset] + ' · Bestand';
  $('quantity').value = a.holding?.quantity ?? '';
  $('average-cost').value = a.holding?.average_cost ?? '';
  $('form-error').textContent = '';
  $('delete-holding').hidden = !a.holding;
  $('holding-dialog').showModal();
});
$('close-dialog').addEventListener('click', () => $('holding-dialog').close());
$('holding-form').addEventListener('submit', async e => {
  e.preventDefault();
  const button = e.submitter; button.disabled = true;
  try {
    const response = await fetch('/api/holdings/' + state.asset, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({quantity: Number($('quantity').value), average_cost: $('average-cost').value === '' ? null : Number($('average-cost').value)})});
    if (!response.ok) throw new Error('Der Bestand konnte nicht gespeichert werden. Bitte Eingaben prüfen.');
    $('holding-dialog').close(); await load(); toast('Bestand gespeichert');
  } catch (error) { $('form-error').textContent = error.message; } finally { button.disabled = false; }
});
$('delete-holding').addEventListener('click', async () => {
  const button = $('delete-holding'); button.disabled = true;
  try { const response = await fetch('/api/holdings/' + state.asset, {method: 'DELETE'}); if (!response.ok) throw new Error('Der Bestand konnte nicht entfernt werden.'); $('holding-dialog').close(); await load(); toast('Bestand entfernt'); }
  catch(error) { $('form-error').textContent = error.message; } finally { button.disabled = false; }
});
setInterval(() => { if (!document.hidden && !$('holding-dialog').open) load(); }, 60000);
load();
