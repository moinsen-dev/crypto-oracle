(() => {
  const $ = id => document.getElementById(id);
  const node = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const names = { timesfm: 'TimesFM · original', calibrated: 'Learned calibration · shadow', fusion_market: 'Market correction · shadow', fusion_news: 'FinBERT news correction · shadow', volband: 'Volatility band · shadow', timesfm_path: 'TimesFM band at this horizon · shadow' };
  const bandModels = new Set(['volband', 'timesfm_path']);
  const pairedModel = { volband: 'timesfm_path', timesfm_path: 'volband' };
  const number = (n, digits = 2) => n === null || n === undefined ? '—' : Number(n).toLocaleString('en-GB', { maximumFractionDigits: digits, minimumFractionDigits: digits });
  const percent = n => n === null || n === undefined ? '—' : `${n > 0 ? '+' : ''}${number(n * 100)}%`;
  const date = t => t === null ? 'Not available' : new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Berlin', timeZoneName: 'short' }).format(t * 1000);
  const controls = { asset: 'forecast-asset', horizon: 'forecast-horizon', model: 'forecast-model', status: 'forecast-filter' };
  let summary, listing, selected, committed, busy = false, page = 0;
  let selectedId = new URL(location.href).searchParams.get('id');
  const values = () => Object.fromEntries(Object.entries(controls).map(([k, id]) => [k, $(id).value]));
  function setValues(v) { for (const [key, id] of Object.entries(controls)) if (v[key] !== undefined) $(id).value = String(v[key]); }
  const params = new URL(location.href).searchParams;
  for (const [key, id] of Object.entries(controls)) if ([...$(id).options].some(o => o.value === params.get(key))) $(id).value = params.get(key);
  function state(r) { return r.outcome ? 'Settled' : r.claim.target > Date.now()/1000 ? 'Waiting for target' : 'Waiting for outcome data'; }
  function status(message, error = false) { $('forecast-status').textContent = message; $('forecast-status').parentElement.dataset.error = String(error); }
  async function read(url) {
    const response = await fetch(url, { cache: 'no-store', credentials: 'omit', signal: AbortSignal.timeout(12000) });
    if (!response.ok) throw new Error(response.status === 404 ? 'forecast_not_found' : 'unavailable');
    return response.json();
  }
  function updateUrl() {
    const url = new URL(location.href); url.search = new URLSearchParams(committed).toString();
    if (selectedId) url.searchParams.set('id', selectedId);
    history.replaceState(null, '', url);
  }
  function addPair(dl, name, value) { dl.append(node('dt', name), node('dd', value)); }
  function score(title, value, detail) { const n = node('div', undefined, 'forecast-score'); n.append(node('span', title), node('strong', value), node('small', detail)); return n; }
  function renderScores() {
    const f = committed;
    const g = summary.groups.find(g => g.asset === f.asset && g.horizon === +f.horizon && g.model === f.model);
    const n = g?.paired || 0, days = g?.calendar_days || 0;
    const count = share => share == null || !n ? '—' : `${Math.round(share*n)} of ${n}`;
    const isBand = bandModels.has(f.model);
    const entry = isBand && summary.volband?.entries.find(x => x.asset === f.asset && x.horizon === +f.horizon);
    const bandScore = m => entry?.interval_score?.[m] == null ? '—' : `${number(entry.interval_score[m] * 100, 2)} pts`;
    $('forecast-scores').replaceChildren(
      score('Settled forecasts', String(g?.scored || 0), `${g?.issued || 0} issued · about ${days} ${days === 1 ? 'day' : 'days'} of market`),
      isBand
        ? score('Direction matched', '—', 'This model has no opinion on direction')
        : score('Direction matched', count(g?.direction), 'Hourly forecasts overlap: one market move is counted many times'),
      score('Inside its own 80% range', count(g?.coverage), 'A well-calibrated range would hold about 8 in 10'),
      isBand
        ? score('Band score', bandScore(f.model), entry?.interval_score?.[pairedModel[f.model]] == null ? 'No paired outcomes yet' : `${names[pairedModel[f.model]]}: ${bandScore(pairedModel[f.model])} · lower is better`)
        : score('Average miss', g?.mae == null ? '—' : number(g.mae*100, 2) + ' pts', g?.baseline_mae == null ? 'No paired outcomes yet' : `“The price stays the same” missed by ${number(g.baseline_mae*100, 2)} pts · lower is better`)
    );
    $('forecast-cohort').textContent = `${f.asset} · ${f.horizon}h · ${names[f.model]}. ${n} matched outcomes from about ${days} calendar ${days === 1 ? 'day' : 'days'}${days < 28 ? ' — a first look, not a result' : ''}. A miss is the absolute log-return error × 100, in percentage points. It is not a portfolio return.`;
  }
  function svgNode(tag, attrs, text) { const el = document.createElementNS('http://www.w3.org/2000/svg', tag); Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, String(v))); if (text !== undefined) el.textContent = text; return el; }
  function chart(r) {
    const mobile = matchMedia('(max-width: 650px)').matches;
    const c = r.claim, w = mobile ? 360 : 880, h = mobile ? 235 : 285, left = mobile ? 8 : 18, right = mobile ? 75 : 100, top = 28, bottom = 42;
    const predicted = [{ t: c.origin, p: c.base }, ...c.path];
    const actual = [{ t: c.origin, p: c.base }, ...r.actual_path];
    const all = [...predicted, ...actual];
    let low = Math.min(...all.map(x => x.p), c.lower ?? Infinity), high = Math.max(...all.map(x => x.p), c.upper ?? 0);
    const pad = Math.max((high - low)*.15, high*.001); low -= pad; high += pad;
    const x = t => left+(t-c.origin)/(c.target-c.origin)*(w-left-right);
    const y = p => top+(high-p)/(high-low)*(h-top-bottom);
    const svg = svgNode('svg', { viewBox: `0 0 ${w} ${h}`, role: 'img', 'aria-label': `${c.asset} frozen forecast and observed hourly closes in USDT`, class: 'forecast-plot' });
    svg.append(svgNode('title', {}, 'Blue dashed: frozen forecast. Orange solid: observed closes. Exact endpoint values are listed above.'));
    for (let i = 0; i < 4; i++) { const p = low+(high-low)*i/3; svg.append(svgNode('line', { x1: left, x2: w-right, y1: y(p), y2: y(p), class: 'forecast-gridline' }), svgNode('text', { x: w-right+10, y: y(p)+4, class: 'forecast-axis' }, number(p, p < 1000 ? 2 : 0))); }
    svg.append(svgNode('text', { x: w-right+10, y: 16, class: 'forecast-axis' }, 'USDT'));
    for (const [t, text, anchor] of [[c.origin, 'Original reference', 'start'], [c.target, mobile ? 'Target close' : `Target · ${date(c.target)}`, 'end']]) svg.append(svgNode('text', { x: x(t), y: h-7, 'text-anchor': anchor, class: 'forecast-axis' }, text));
    const line = pts => pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(2)},${y(p.p).toFixed(2)}`).join(' ');
    if (c.lower !== null) svg.append(svgNode('line', { x1: x(c.target), x2: x(c.target), y1: y(c.lower), y2: y(c.upper), stroke: '#a4bad5', 'stroke-width': 9 }));
    svg.append(svgNode('path', { d: line(predicted), fill: 'none', stroke: '#1755a1', 'stroke-width': 3, 'stroke-dasharray': '8 5' }));
    // A missing hour is a gap, not an invented observation.
    let segment = [];
    for (const p of actual) { if (segment.length && p.t - segment.at(-1).t > 3600) { svg.append(svgNode('path', { d: line(segment), fill: 'none', stroke: '#b45313', 'stroke-width': 3 })); segment = []; } segment.push(p); }
    if (segment.length) svg.append(svgNode('path', { d: line(segment), fill: 'none', stroke: '#b45313', 'stroke-width': 3 }));
    const last = actual.at(-1); svg.append(svgNode('circle', { cx: x(last.t), cy: y(last.p), r: 4, fill: '#b45313' }));
    return svg;
  }
  function renderDetail(r) {
    const keepOpen = selected?.id === r.id && $('forecast-detail').querySelector('details')?.open;
    selected = r; const c = r.claim, e = r.outcome, q = r.quality, box = $('forecast-detail'); box.hidden = false;
    box.replaceChildren(node('span', state(r), 'forecast-badge' + (e ? '' : ' pending')), node('h2', bandModels.has(c.model) && c.lower !== null ? (e ? `${c.asset}: the range was ${number(c.lower)}–${number(c.upper)} USDT. It closed at ${number(e.actual)}, ${e.covered ? 'inside' : 'outside'}.` : `${c.asset}: the range is ${number(c.lower)}–${number(c.upper)} USDT by ${date(c.target)}.`) : e ? `${c.asset}: ${percent(c.prediction/c.base-1)} was the forecast. It moved ${percent(e.actual/c.base-1)}.` : c.target > Date.now()/1000 ? `${c.asset}: the model expects ${percent(c.prediction/c.base-1)} by ${date(c.target)}.` : `${c.asset}: ${percent(c.prediction/c.base-1)} was the forecast. The outcome is not in yet.`), node('p', `${names[c.model]} · issued ${date(c.issued_at)} · target ${date(c.target)}`, 'record-subtitle'));
    const comparison = node('div', undefined, 'forecast-comparison');
    for (const [title, primary, secondary, cls] of [
      ['Predicted at target', `${number(c.prediction)} USDT`, `${percent(c.prediction/c.base-1)} from the original close`, 'prediction'],
      ['Observed at target', e ? `${number(e.actual)} USDT` : 'Not settled', e ? `${percent(e.actual/c.base-1)} from the same close` : 'The target outcome is still required', 'observation'],
      ['Return error', e ? `${number(100*Math.abs(c.prediction-e.actual)/c.base, 3)} pp` : '—', 'Absolute difference in percentage points', '']
    ]) { const part = node('div', undefined, cls); part.append(node('span', title), node('strong', primary), node('small', secondary)); comparison.append(part); }
    box.append(comparison, chart(r));
    const legend = node('div', undefined, 'forecast-chart-legend'); legend.append(node('span', 'Frozen prediction · dashed'), node('span', 'Observed price · solid')); box.append(legend);
    const verdict = node('div', undefined, 'forecast-verdict');
    verdict.append(node('p', e ? `${e.direction_correct ? 'Direction matched.' : 'Direction did not match.'} ${e.covered === null ? 'No interval was issued.' : e.covered ? 'The target was inside the forecast band.' : 'The target was outside the forecast band.'} A direction match alone does not establish an accurate or profitable forecast.` : c.target > Date.now()/1000 ? `This claim is still open. It will be scored after ${date(c.target)} when the completed target candle arrives.` : 'The target time has passed. The exact target candle or its evaluation has not been published yet; no result is assumed.'));
    box.append(verdict);
    const quality = node('div', undefined, 'forecast-quality');
    const qualityText = { qualified: 'The saved input and exact target close passed the learning checks. Coinbase and Kraken USD closes agreed with converted Binance within 1%.', reference_missing: 'An independent target-hour reference is missing. The original score stays visible, but this example cannot train the calibration candidate.', source_revised: 'The source later revised this target candle. The original evaluation is preserved; the example is held out of the calibration learner.', input_unverified: 'The original input could not pass the learning verification. The example is held out.', outcome_unverified: 'The original outcome observation time could not be verified. The example is held out.', fx_divergence: 'The target-hour USDT/USD conversion exceeded the fixed tolerance. The example is held out.', venue_divergence: 'The target-hour prices disagreed across venues. The example is held out.' };
    quality.append(node('b', q?.status === 'qualified' ? 'Outcome checked · eligible for later learning' : e ? 'Learning eligibility · awaiting or under review' : 'Outcome checks follow settlement'), node('p', q ? qualityText[q.status] : e ? 'Independent outcome checks have not been published for this record. A score is not yet a qualified learning label.' : 'A later observation must pass its own data checks before the calibration learner can use it.'));
    box.append(quality);
    const details = node('details'); details.append(node('summary', 'Original reference, comparisons & evidence'));
    const dl = node('dl', undefined, 'forecast-proof');
    addPair(dl, 'Original reference', `${number(c.base)} USDT · ${date(c.origin)}`);
    addPair(dl, 'Market', 'Binance spot · completed hourly close · USDT');
    addPair(dl, 'Interval at target', c.lower === null ? 'None' : `${number(c.lower)} – ${number(c.upper)} USDT · nominal Q10–Q90`);
    for (const b of r.baselines) addPair(dl, b.model === 'persistence' ? 'Price unchanged' : b.model === 'momentum' ? 'Momentum baseline' : b.model === 'timesfm' ? 'Original TimesFM' : names[b.model], `${number(b.prediction)} USDT${b.error !== null ? ` · error × 100: ${number(b.error*100, 3)}` : ''}`);
    if (e) { addPair(dl, 'Evaluated', date(e.evaluated_at)); addPair(dl, 'Outcome hash', e.actual_hash); }
    if (q) { addPair(dl, 'Outcome review', `${date(q.at)} · ${q.status}`); addPair(dl, 'Original outcome seen', date(q.actual_observed_at)); for (const v of q.references) addPair(dl, `${v.source} · ${v.asset}/USD`, `${number(v.close, v.asset === 'USDT' ? 6 : 2)} · hour ending ${date(v.ts)} · observed ${date(v.observed_at)}`); }
    addPair(dl, 'Forecast ID', r.id); addPair(dl, 'Experiment', c.experiment); addPair(dl, 'Model revision', c.revision); addPair(dl, 'Input hash', c.input_hash);
    if (c.artifact_id) addPair(dl, 'Fitted artifact', c.artifact_id);
    details.open = Boolean(keepOpen); details.append(dl); box.append(details);
    const actions = node('div', undefined, 'forecast-detail-actions');
    const link = node('a', 'Link to this forecast'); link.href = '/forecasts/?id=' + r.id;
    const download = node('a', 'Download this record'); download.href = '/api/forecasts?id=' + r.id; download.download = `forecast-${r.id.slice(0, 12)}.json`;
    actions.append(link, download); box.append(actions);
  }
  function renderList() {
    const box = $('forecast-list'); box.replaceChildren();
    for (const r of listing.records) {
      const c = r.claim, button = node('button', undefined, 'forecast-row'); button.type = 'button'; button.setAttribute('aria-pressed', String(selectedId === r.id));
      const title = node('span'); title.append(node('small', `${state(r)} · target`), node('span', date(c.target), 'row-date'));
      const predicted = node('span'); predicted.append(node('small', 'Predicted move'), node('strong', percent(c.prediction/c.base-1)));
      const actual = node('span'); actual.append(node('small', 'Observed move'), node('strong', r.outcome ? percent(r.outcome.actual/c.base-1) : 'Pending'));
      button.append(title, predicted, actual, node('span', 'Inspect forecast ↗', 'row-inspect'));
      button.addEventListener('click', () => { selectedId = r.id; renderDetail(r); renderList(); updateUrl(); $('forecast-detail').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' }); });
      box.append(button);
    }
    if (!listing.records.length) box.append(node('p', committed.model !== 'timesfm' ? 'No matching shadow forecasts have been published. Check the learning stage below; predictions are never fabricated to fill this view.' : committed.status === 'scored' ? 'No settled forecasts in this view yet. Choose “Waiting for target” to inspect already-issued predictions.' : 'No forecasts match this view.', 'forecast-empty'));
    $('forecast-count').textContent = `${listing.total} matching forecasts`;
    $('forecast-page-number').textContent = listing.total ? `Page ${page+1} of ${Math.ceil(listing.total/12)}` : 'No records';
    $('forecast-prev').disabled = page === 0; $('forecast-next').disabled = (page+1)*12 >= listing.total;
  }
  function renderLearning() {
    const f = committed, l = summary.learning.find(x => x.asset === f.asset && x.horizon === +f.horizon), n = summary.news.find(x => x.asset === f.asset && x.horizon === +f.horizon);
    if (!l) return;
    const box = $('learning-state'); box.replaceChildren(node('span', `${f.asset} · ${f.horizon} hours`, 'eyebrow'), node('h3', l.issued ? 'Shadow forecasts are being evaluated' : l.ready ? 'Data gates met · waiting for the next forecast' : 'Collecting qualified outcomes'));
    box.append(node('p', l.issued ? `${l.issued} calibration forecasts issued; ${l.evaluated} settled. The original TimesFM model continues alongside it.` : 'The candidate has not issued a forecast yet. It must have enough settled, independently checked examples before fitting.'));
    const progress = node('div', undefined, 'learning-progress');
    for (const [text, value, max] of [[`${l.samples} / 120 eligible examples`, l.samples, 120], [`${number(l.span_days, 1)} / 21 days of origin history`, l.span_days, 21]]) {
      const label = node('label', text); const bar = node('progress'); bar.max = max; bar.value = Math.min(value, max); bar.setAttribute('aria-label', text); label.append(bar); progress.append(label);
    }
    box.append(progress, node('p', `${l.training} training / ${l.calibration} calibration examples after excluding overlapping targets. Minimums: 60 / 30. Reaching a data threshold permits fitting; it does not demonstrate improvement.`, 'fine-print'));
    if (l.review) box.append(node('p', `Recorded 28-day review: ${l.review.status === 'supported_for_review' ? 'candidate supported for review' : 'inconclusive'}. ${l.review.n} common qualified origins. No trading policy was automatically promoted.`));
    else box.append(node('p', l.review_due ? `First fixed review can begin after ${date(l.review_due)}. Pending or missing outcomes may limit its conclusion.` : 'The 28-day future comparison begins when this candidate issues its first forecast. There is no automatic model or trading-policy promotion.', 'fine-print'));
    if (n) box.append(node('p', `Separate FinBERT news experiment: ${n.samples} covered mature examples, ${number(n.span_days, 1)} days and ${n.news_ids} news IDs; ${n.issued} news-corrected forecasts issued. Its minimums are 120 examples, 21 days and 10 IDs. JEV remains a separate headline evaluator and paper buy guard.`, 'learning-news'));
    box.append(node('p', `Experiment ${summary.experiment} · activated ${date(summary.started_at)}`, 'fine-print'));
  }
  async function load(options = {}) {
    if (busy) return; busy = true; $('refresh-forecasts').disabled = true;
    for (const id of Object.values(controls)) $(id).disabled = true;
    const requested = values(), requestedPage = options.page ?? page;
    status('Refreshing the public record…');
    try {
      const s = await read('/api/learning');
      let detail = null;
      const id = options.clearSelection ? null : selectedId;
      if (id) { const d = await read('/api/forecasts?id=' + encodeURIComponent(id)); detail = d.record; requested.asset = detail.claim.asset; requested.horizon = String(detail.claim.horizon); requested.model = detail.claim.model; }
      const l = await read('/api/forecasts?' + new URLSearchParams({ ...requested, page: requestedPage }));
      summary = s; listing = l; committed = requested; page = requestedPage; setValues(committed);
      selectedId = detail?.id || l.records[0]?.id || null;
      selected = detail || l.records[0] || null;
      renderScores(); renderLearning(); renderList();
      if (selected) renderDetail(selected); else { $('forecast-detail').hidden = true; $('forecast-detail').replaceChildren(); }
      updateUrl();
      const stale = Date.now()/1000 - s.generated_at > 2100;
      status(`${stale ? 'Publication is stale. Last known record: ' : 'Published '}${date(s.generated_at)} · updates about every 15 minutes · all times Europe/Berlin.`, stale);
    } catch (error) {
      if (committed) setValues(committed);
      status(error.message === 'forecast_not_found' ? 'This forecast has not been published or the link is invalid. Change a filter to browse the available journal.' : `The public record could not be refreshed.${summary ? ' Last successfully loaded values remain visible.' : ' No results are assumed.'} Please retry.`, true);
    } finally { busy = false; $('refresh-forecasts').disabled = false; for (const id of Object.values(controls)) $(id).disabled = false; syncHorizons(); }
  }
  function syncHorizons() {
    const band = bandModels.has($(controls.model).value), horizon = $(controls.horizon);
    for (const option of horizon.options) option.disabled = !band && !['24', '72'].includes(option.value);
    if (horizon.selectedOptions[0]?.disabled) horizon.value = '24';
  }
  for (const id of Object.values(controls)) $(id).addEventListener('change', () => { syncHorizons(); load({ clearSelection: true, page: 0 }); });
  $('forecast-prev').addEventListener('click', () => load({ clearSelection: true, page: Math.max(0, page-1) }));
  $('forecast-next').addEventListener('click', () => load({ clearSelection: true, page: page+1 }));
  $('refresh-forecasts').addEventListener('click', () => load());
  syncHorizons();
  load();
  let resizeTimer;
  addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { if (selected) $('forecast-detail').querySelector('.forecast-plot')?.replaceWith(chart(selected)); }, 100); });
  setInterval(() => { if (!document.hidden) load(); }, 60000);
})();
