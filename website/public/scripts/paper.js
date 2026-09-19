const root = document.querySelector('[data-paper]');
if (root) {
  const $ = name => root.querySelector(`[data-${name}]`);
  const money = n => n === null ? 'Unavailable' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(n);
  const pct = n => `${(n * 100).toFixed(2)}%`;
  const date = n => new Date(n * 1000).toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
  const names = { 'news-guarded': 'AI + news', 'price-only': 'Price AI', reference: 'Buy & hold', trend: 'Trend filter', rebalanced: 'Rebalanced' };
  const numbers = { 'news-guarded': '01', 'price-only': '02', reference: '03', trend: '01', rebalanced: '02' };
  // The third run reuses the three visual slots (colour, marker, line style) of the first two.
  const slot = id => ({ trend: 'news-guarded', rebalanced: 'price-only' })[id] || id;
  const cards = { trend: ['Fixed trend rule', 'Holds each coin in proportion to its positive 7-, 14-, 28- and 56-day returns. The rest stays in cash.'], rebalanced: ['20 / 20 / 20 / 40', 'Keeps 20% in each coin and restores the weights when they drift.'], 'news-guarded': ['TimesFM + JEV', 'Trades on price forecasts. Negative news can block a new buy.'], 'price-only': ['TimesFM only', 'The same trading rules, without the news filter.'], reference: ['Market reference', 'Buys BTC, ETH and SOL once, then holds. No AI decisions.'] };
  const signedMoney = n => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', signDisplay: 'exceptZero', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Math.abs(n) < .005 ? 0 : n);
  const signedPct = n => `${n >= .00005 ? '+' : ''}${pct(Math.abs(n) < .00005 ? 0 : n)}`;
  const shortDate = n => new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }).format(new Date(n * 1000));
  const titles = { initial_allocation: 'Set up the shared starting allocation', initial_allocation_wait: 'Waiting for a common, valid starting point', below_entry: 'The forecast is not strong enough to buy', reference_hold: 'Keep the initial investment', execution_invalid: 'A reliable execution price is missing', position_stop: 'Reduce a position after a price fall', allocation_limit: 'Keep the portfolio within its limits', negative_forecast: 'The forecast now favours an exit', data_quality: 'Market data did not pass the checks', drawdown_brake: 'New buys paused after a portfolio decline', forecast_missing: 'Waiting for an eligible forecast', forecast_stale: 'Waiting for a newer forecast', input_invalid: 'Forecast inputs could not be verified', cooldown: 'Waiting between trades', news_veto: 'Negative news blocked a new buy', reference_entry: 'Make the initial comparison purchase', positive_forecast: 'The signal is strong enough for a small buy', pending_order: 'Waiting for an execution result', within_band: 'Weights are close enough to the target', trend_up: 'Trailing returns support a larger position', trend_down: 'Trailing returns support a smaller position', rebalance: 'Restore the 20% weights', trend_input_missing: 'A daily close for the trend rule is missing' };
  const why = { trend_up: 'Trailing returns support a larger position', trend_down: 'Trailing returns support a smaller position', rebalance: 'Weights drifted more than five points', initial_allocation: 'Shared starting allocation, not a signal', reference_entry: 'Initial comparison purchase', positive_forecast: 'The forecast cleared the entry hurdle', negative_forecast: 'The forecast turned negative', position_stop: 'Stop after a 6% fall below cost', allocation_limit: 'Back within the allocation limits' };
  const reason = {
    initial_allocation: 'This fixed setup targets 20% of starting capital per coin in all three portfolios. It uses common execution quotes and fees, independently of the forecast and news. Subsequent AI trades follow the forecast and news rules.',
    initial_allocation_wait: 'At least one coin failed a market-data check. All three portfolios keep cash until the shared starting allocation can be attempted together.',
    initial_allocation_cancelled: 'Another order in the common setup failed. All nine starting buys were cancelled together to preserve equal initial holdings.',
    below_entry: 'The forecast does not clear the estimated trading costs and uncertainty margin. It does not justify a new buy.',
    reference_hold: 'The reference keeps its initial holdings without rebalancing.',
    execution_invalid: 'A fresh, plausible executable USD quote is unavailable. No fill is invented.',
    position_stop: 'The valid market mark is at least 6% below the position’s average cost. Reduce the position.',
    allocation_limit: 'An allocation limit prevents a new buy or requires a position reduction.',
    negative_forecast: 'The forecast crossed the negative exit threshold after the normal cooldown.',
    data_quality: 'A data gate failed or the portfolio could not be valued reliably. New risk is blocked.',
    drawdown_brake: 'An 8% drawdown has paused new buys for this strategy version.',
    forecast_missing: 'No eligible, already-issued TimesFM forecast is available.',
    forecast_stale: 'The latest forecast is too old for a new trading decision.',
    input_invalid: 'The stored forecast inputs or their timestamps did not pass validation.',
    cooldown: 'This asset is within the six-hour interval between regular trades.',
    news_veto: 'A material negative JEV-classified event blocks this otherwise eligible new buy.',
    reference_entry: 'Enter the fixed comparison with up to 20% of starting capital in this asset.',
    positive_forecast: 'The price signal clears costs and the uncertainty margin, and risk checks allow a small buy.',
    pending_order: 'An earlier order still awaits a recorded execution outcome.',
    within_band: 'Current and wanted weights differ by five points or less in total. Trading now would only add costs.',
    trend_up: 'The share of positive 7-, 14-, 28- and 56-day returns supports a larger weight than the portfolio holds. Buy towards 20% × that share.',
    trend_down: 'The share of positive 7-, 14-, 28- and 56-day returns supports a smaller weight than the portfolio holds. Sell towards 20% × that share; at zero the coin is sold completely.',
    rebalance: 'The weights drifted more than five points in total from 20% per coin. Trade back to the fixed weights.',
    trend_input_missing: 'A completed daily close needed for the 7-, 14-, 28- or 56-day comparison is not in the database. The rule does not guess.',
    order_expired: 'The order expired after 120 seconds without a valid fill.',
    quote_before_decision: 'The available quote was requested before the decision and cannot fill it.',
    insufficient_depth: 'The visible book cannot fill the full quantity within the allowed price range.',
    execution_risk_limit: 'Price movement, cash or allocation limits prevented the fill at execution.',
    insufficient_position: 'The portfolio does not hold enough units for this sale.',
  };
  const checkNames = { coinbase_fresh: 'Fresh Coinbase USD book', kraken_fresh: 'Fresh Kraken USD book', binance_fresh: 'Fresh Binance USDT book', usd_pair_agreement: 'Coinbase / Kraken agree within 1%', usdt_conversion: 'Fresh USDT/USD within 1% of parity', three_venue_agreement: 'Three converted prices agree within 1%', spread: 'Executable spread ≤ 30 bps' };
  let data = null;
  let selectedRun = new URL(window.location.href).searchParams.get('run') || '';
  const commonStart = () => data?.policy.version === 'paper-v2';
  const trendRun = () => data?.policy.version === 'paper-v3';
  const explain = code => trendRun() && code === 'cooldown' ? 'This coin already traded today. The rule acts at most once per coin and UTC day.' : trendRun() && code === 'reference_entry' ? 'Enter the held comparison with 20% of starting capital in this coin.' : reason[code];
  const setupDecision = d => d.reason.startsWith('initial_allocation');
  const runName = run => run.startsWith('paper-v3-') ? 'Trend filter · v3' : run.startsWith('paper-v2-') ? 'Common start · v2' : 'Cash start · v1';
  let loading = false;
  let selected = 'news-guarded';
  let chartMode = 'all';
  let historyLimit = 6;
  function node(tag, text, cls) { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; }
  function rows(target, values) { target.replaceChildren(...values.map(row => { const tr = node('tr'); row.forEach(v => tr.append(node('td', String(v)))); return tr; })); }
  function text(name, value) { $(name).textContent = value; }
  function pair(dl, label, value) { dl.append(node('dt', label), node('dd', value)); }
  function svg(tag, attrs, content) { const n = document.createElementNS('http://www.w3.org/2000/svg', tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v)); if (content !== undefined) n.textContent = content; return n; }
  function marker(g, account, x, y) {
    const attrs = { class: `equity-marker ${account}` };
    if (slot(account) === 'news-guarded') g.append(svg('circle', { ...attrs, cx: x, cy: y, r: 4.5 }));
    else if (slot(account) === 'price-only') g.append(svg('rect', { ...attrs, x: x - 4.5, y: y - 4.5, width: 9, height: 9 }));
    else g.append(svg('path', { ...attrs, d: `M${x},${y - 5.5}l5.5,10h-11Z` }));
  }
  function chart() {
    if (!data) return;
    const el = $('equity-chart');
    el.querySelectorAll('g').forEach(n => n.remove());
    const width = Math.max(280, el.clientWidth || 960), height = 290;
    el.setAttribute('viewBox', `0 0 ${width} ${height}`);
    const g = svg('g', {});
    const points = data.history.flatMap(h => h.points).filter(p => p.fresh);
    const values = [0, ...points.map(p => p.equity - data.policy.starting_usd)];
    const minimum = Math.min(...values), maximum = Math.max(...values);
    const pad = Math.max(5, (maximum - minimum) * .18);
    const roughStep = (maximum - minimum + 2 * pad) / 5;
    const power = 10 ** Math.floor(Math.log10(roughStep));
    const step = [1, 2, 5, 10].find(n => n * power >= roughStep) * power;
    const low = Math.floor((minimum - pad) / step) * step, high = Math.ceil((maximum + pad) / step) * step;
    const start = points.length ? Math.min(...points.map(p => p.at)) : data.started_at;
    const end = Math.max(start + 1, ...points.map(p => p.at));
    const left = 72, right = width - 15;
    const x = t => left + (t - start) / (end - start) * (right - left);
    const y = value => 241 - (value - low) / (high - low) * 212;
    for (let value = low; value <= high + step / 100; value += step) {
      if (Math.abs(y(value) - y(0)) < 14) continue;
      g.append(svg('line', { x1: left, x2: right, y1: y(value), y2: y(value), class: 'equity-grid' }));
      g.append(svg('text', { x: left - 10, y: y(value) + 4, 'text-anchor': 'end', class: 'chart-tick' }, signedMoney(value)));
    }
    g.append(svg('line', { x1: left, x2: right, y1: y(0), y2: y(0), class: 'equity-cash' }));
    g.append(svg('text', { x: left - 10, y: y(0) + 4, 'text-anchor': 'end', class: 'chart-tick baseline-tick' }, '$0'));
    const histories = data.history.filter(h => chartMode === 'all' || h.account === selected);
    // Draw the selected strategy last, so it remains visible when values overlap.
    histories.sort((a, b) => Number(a.account === selected) - Number(b.account === selected));
    for (const h of histories) {
      let path = '', previous = false;
      for (const p of h.points) {
        if (!p.fresh) { previous = false; continue; }
        path += `${previous ? 'L' : 'M'}${x(p.at).toFixed(2)},${y(p.equity - data.policy.starting_usd).toFixed(2)} `; previous = true;
      }
      g.append(svg('path', { d: path, class: `equity-series ${slot(h.account)}`, 'data-series': h.account }));
      const valid = h.points.filter(p => p.fresh);
      const stride = Math.max(1, Math.ceil(valid.length / (width < 500 ? 5 : 10)));
      valid.forEach((p, i) => { if (i % stride === 0 || i === valid.length - 1) marker(g, h.account, x(p.at), y(p.equity - data.policy.starting_usd)); });
    }
    g.append(svg('text', { x: left, y: 278, class: 'chart-tick' }, shortDate(start)));
    g.append(svg('text', { x: right, y: 278, 'text-anchor': 'end', class: 'chart-tick' }, shortDate(end)));
    el.append(g);
    el.querySelector('desc').textContent = histories.map(h => { const a = data.accounts.find(a => a.id === h.account); return `${numbers[a.id]} ${names[a.id]}: ${signedMoney(a.equity - data.policy.starting_usd)} change, total ${money(a.equity)}${a.fresh ? '' : ', indicative only'}.`; }).join(' ') + ' Cash baseline: zero change.';
    const [one, two, three] = data.accounts.map(a => a.id);
    const first = data.history.find(h => h.account === one).points;
    const second = data.history.find(h => h.account === two).points;
    const overlap = first.length > 0 && first.length === second.length && first.every((p, i) => p.at === second[i].at && p.fresh === second[i].fresh && Math.abs(p.equity - second[i].equity) < .005);
    const allOverlap = overlap && data.history.every(h => h.points.length === first.length && h.points.every((p, i) => p.at === first[i].at && p.fresh === first[i].fresh && Math.abs(p.equity - first[i].equity) < .005));
    text('chart-explanation', chartMode === 'selected' ? `Showing ${numbers[selected]} · ${names[selected]} on its own, against the cash baseline. The scale stays the same so you can compare fairly.` : allOverlap ? 'All three portfolios have identical recorded values, so their lines overlap. Select a portfolio and choose “Selected portfolio” to inspect its line.' : overlap ? `${names[one]} and ${names[two]} have identical recorded values, so their lines overlap. Choose a portfolio above, then “Selected portfolio” to see its line on its own.` : `Blue circles: ${names[one]}. Orange squares: ${names[two]}. Purple triangles: ${names[three]}. The grey zero line shows what keeping all $10,000 in cash would return.`);
    text('chart-period', `${shortDate(start)} – ${shortDate(end)} UTC · ${Math.max(...data.history.map(h => h.points.length))} observations per portfolio`);
    root.querySelectorAll('[data-legend]').forEach(n => { const a = data.accounts.find(v => slot(v.id) === n.dataset.legend); n.lastChild.textContent = `${numbers[a.id]} · ${names[a.id]}`; n.hidden = chartMode !== 'all' && n.dataset.legend !== slot(selected); });
    root.querySelectorAll('[data-chart-mode]').forEach(n => n.setAttribute('aria-pressed', String(n.dataset.chartMode === chartMode)));
  }
  function actionLabel(d) {
    if (d.outcome === 'fill') return d.action === 'sell' ? 'Sold' : 'Bought';
    if (d.outcome === 'cancel') return 'Not executed';
    if (d.action === 'hold') return d.reason === 'reference_hold' ? 'Hold' : 'Wait';
    if (d.action === 'blocked') return 'Blocked';
    return d.action === 'buy' ? 'Buy pending' : 'Sell pending';
  }
  function recentFor(account) {
    const records = data.decisions.filter(d => d.account === account).sort((a, b) => b.at - a.at || b.seq - a.seq);
    return ['BTC', 'ETH', 'SOL'].map(asset => records.find(d => d.asset === asset)).filter(Boolean);
  }
  function latestDecisions(a) {
    const latest = recentFor(a.id), invested = a.positions.some(p => p.quantity > 0);
    let summary = trendRun() ? (a.id === 'trend' ? invested ? 'This portfolio holds each coin in proportion to its positive trailing returns. It checks hourly and acts at most once per coin and day.' : 'In cash: the trailing returns do not support a position right now. The rule keeps checking every hour.' : a.id === 'rebalanced' ? 'This comparison keeps 20% in each coin. It trades only when the weights drift more than five points in total.' : 'This comparison buys 20% of each coin once, then holds without rebalancing.') : a.id === 'reference' ? 'This portfolio makes one initial purchase attempt per coin, then holds. It gives the AI strategies a simple market comparison.' : !latest.length ? 'The first decisions have not been published yet.' : a.braked ? 'New buys are paused because this portfolio reached its drawdown limit. Existing positions can still be reduced.' : !invested && latest.every(d => d.reason === 'below_entry') ? 'Still in cash: none of the latest forecasts cleared the entry threshold. The system checked the market and chose to wait.' : invested ? 'This portfolio holds crypto. The latest checks below explain whether to keep, reduce or add to those positions.' : 'This portfolio currently holds cash. The latest checks below explain why no position was opened.';
    if (commonStart() && latest.some(setupDecision)) summary = a.fills >= 3 ? 'The shared starting allocation is complete. These three buys are experiment setup, not AI-generated buy signals. Regular AI trades wait six hours after a fill; stops and allocation reductions can act sooner.' : 'The common starting allocation is not complete. All three portfolios wait together for valid, executable prices.';
    if (Date.now() / 1000 - a.asof > 2100 || !a.fresh) summary = 'This snapshot is out of date or uses unreliable marks. The decisions below describe the last published state. ' + summary;
    text('latest-summary', summary);
    const cards = latest.map(d => {
      const card = node('article', undefined, 'latest-card');
      const header = node('div', undefined, 'latest-card-head'); header.append(node('h4', d.asset), node('span', actionLabel(d), `audit-pill ${d.action}`));
      card.append(header, node('strong', d.outcome === 'cancel' ? 'The order could not be filled' : titles[d.reason] || d.reason, 'decision-title'));
      if (d.outcome === 'cancel') card.append(node('p', reason[d.execution.reason], 'fine-print'));
      if (trendRun()) {
        const facts = node('dl', undefined, 'decision-facts'), t = d.signal.trend;
        pair(facts, 'Positive trailing returns', t ? `${t.lookbacks.filter(l => l.positive).length} of 4` : 'Unavailable');
        pair(facts, 'Weight now → wanted', `${pct(d.signal.weight)} → ${d.signal.target_weight === null ? 'unknown' : pct(d.signal.target_weight)}`); card.append(facts);
      } else if (d.signal && a.id !== 'reference' && !setupDecision(d)) {
        const facts = node('dl', undefined, 'decision-facts');
        pair(facts, 'Forecast move · 24h', d.signal.expected_return === null ? 'Unavailable' : signedPct(d.signal.expected_return));
        pair(facts, 'Needed to buy', `>${pct(d.signal.entry_threshold)}`); card.append(facts);
      } else card.append(node('p', setupDecision(d) ? reason[d.reason] : a.id === 'reference' ? 'No forecast needed. This comparison follows its initial buy-and-hold rule.' : reason[d.reason], 'fine-print'));
      const passed = d.quality.checks.filter(c => c.passed).length;
      card.append(node('p', `${passed}/7 market checks passed${d.account === 'news-guarded' && d.news ? d.news.veto ? ' · news veto recorded' : d.news.state === 'unavailable' ? ' · news unknown' : d.news.state === 'partial' ? ' · partial news coverage, no veto' : ' · no news veto' : ''}`, 'decision-checks'));
      const button = node('button', `Inspect ${d.asset} decision`, 'decision-link'); button.type = 'button';
      button.addEventListener('click', () => {
        $('action').value = 'all'; historyLimit = Math.max(historyLimit, data.decisions.filter(v => v.account === selected).findIndex(v => v.seq === d.seq) + 1); renderHistory();
        const detail = $('decisions').querySelector(`[data-seq="${d.seq}"]`);
        detail.open = true; detail.querySelector('summary').focus({ preventScroll: true }); detail.scrollIntoView({ behavior: 'auto', block: 'start' });
      });
      card.append(node('time', shortDate(d.at) + ' UTC', 'fine-print'), button); return card;
    });
    $('latest').replaceChildren(...cards);
  }
  function audit(d) {
    const item = node('details', undefined, 'audit-item'); item.dataset.seq = String(d.seq);
    const summary = node('summary');
    summary.append(node('strong', d.asset), node('span', actionLabel(d), `audit-pill ${d.action}`), node('span', titles[d.reason] || d.reason, 'audit-reason'), node('time', shortDate(d.at) + ' UTC'));
    item.append(summary);
    const body = node('div', undefined, 'audit-body'); body.append(node('p', explain(d.reason)));
    if (trendRun() && d.signal.trend) body.append(node('p', `${d.signal.trend.lookbacks.filter(l => l.positive).length} of 4 trailing returns are positive at the daily close of ${shortDate(d.signal.trend.origin)} UTC. Weight now ${pct(d.signal.weight)}, wanted ${d.signal.target_weight === null ? 'unknown' : pct(d.signal.target_weight)}.`, 'decision-explainer'));
    else if (d.signal && d.account !== 'reference' && !setupDecision(d)) body.append(node('p', `Forecast move: ${d.signal.expected_return === null ? 'unavailable' : signedPct(d.signal.expected_return)}. A new buy needs more than ${pct(d.signal.entry_threshold)}.`, 'decision-explainer'));
    if (d.signal && !trendRun()) { const forecastLink = node('a', 'View the frozen forecast & its outcome', 'text-link'); forecastLink.href = '/forecasts/?id=' + encodeURIComponent(d.signal.forecast_id); body.append(forecastLink); }
    const technical = node('details', undefined, 'technical-evidence'); technical.append(node('summary', trendRun() ? 'Inspect market checks and the daily closes behind the rule' : 'Inspect market checks, model inputs and news evidence'));
    const evidence = node('div', undefined, 'technical-body');
    if (d.account === 'reference' || setupDecision(d)) evidence.append(node('p', 'Forecasts and news were recorded as context. This fixed allocation does not use them to decide its initial purchases.', 'fine-print'));
    const columns = node('div', undefined, 'audit-columns');
    const left = node('div'); left.append(node('h3', '1. Inputs & price signal'));
    const dl = node('dl');
    for (const [venue, price] of Object.entries(d.quality.prices)) pair(dl, `${venue[0].toUpperCase() + venue.slice(1)} · USD`, money(price));
    pair(dl, 'USDT in USD', d.quality.fx === null ? 'Unavailable' : d.quality.fx.toFixed(6));
    pair(dl, 'Spread', d.quality.spread_bps === null ? 'Unavailable' : `${d.quality.spread_bps.toFixed(2)} bps`);
    pair(dl, 'Ask / bid depth', `${money(d.quality.ask_depth_usd)} / ${money(d.quality.bid_depth_usd)}`);
    if (trendRun()) {
      const t = d.signal.trend;
      if (t) { pair(dl, 'Daily close · USDT', `${t.close.toFixed(2)} · ${shortDate(t.origin)} UTC`); for (const l of t.lookbacks) pair(dl, `${l.days} days earlier`, `${l.close.toFixed(2)} · ${l.positive ? 'return positive' : 'return not positive'}`); }
      else pair(dl, 'Daily closes', 'Incomplete');
    } else if (d.signal) {
      pair(dl, 'Forecast gross return', d.signal.expected_return === null ? 'Unavailable' : pct(d.signal.expected_return));
      pair(dl, 'Required entry return', pct(d.signal.entry_threshold));
      pair(dl, 'Forecast issued', date(d.signal.issued_at)); pair(dl, 'Target time', date(d.signal.target));
      pair(dl, 'Raw interval · USDT', `${d.signal.lower_usdt.toFixed(2)}–${d.signal.upper_usdt.toFixed(2)}`);
    } else pair(dl, 'Eligible forecast', 'Unavailable');
    left.append(dl);
    const right = node('div'); right.append(node('h3', '2. Plausibility gates'));
    const checks = node('ul', undefined, 'audit-checks');
    for (const c of d.quality.checks) { const li = node('li'); li.append(node('span', checkNames[c.code]), node('b', c.passed ? 'PASS' : 'FAIL', c.passed ? '' : 'failed')); checks.append(li); }
    right.append(checks, node('p', `Order-book observation: ${date(d.quality.observed_at)}.`, 'fine-print'));
    columns.append(left, right); evidence.append(columns, node('h3', trendRun() ? '3. Execution' : '3. News evidence & execution'));
    const newsMessage = trendRun() ? 'This experiment uses no forecast and no news.' : d.news.state === 'unavailable' ? 'No eligible JEV evidence is available. This is unknown, not neutral; the fixed price rules may still proceed.' : `${d.news.items.length} eligible JEV annotation(s), coverage ${d.news.state}. ${d.news.veto ? 'An adverse event triggers the JEV guard.' : 'No annotation triggers the JEV guard.'}`;
    evidence.append(node('p', newsMessage + (trendRun() ? '' : setupDecision(d) ? ' This is context only for the fixed common start; the news guard applies to subsequent AI buys.' : d.account !== 'news-guarded' ? ' This portfolio does not apply the news guard.' : ''), 'fine-print'));
    if (d.news?.items.length) {
      const list = node('ul', undefined, 'audit-news');
      for (const n of d.news.items) list.append(node('li', `${n.source} · ${n.tone} ${n.event} · relevance ${pct(n.relevance)}, materiality ${pct(n.material)} · classified ${date(n.evaluated_at)} · evidence ${n.evaluation_id.slice(0, 12)}.`));
      evidence.append(list);
    }
    const e = d.execution;
    const execution = d.outcome === 'fill' ? `Filled ${e.quantity.toFixed(8)} ${d.asset} at ${money(e.price)}, fee ${money(e.fee)}. New execution book observed ${date(e.observed_at)}.` : d.outcome === 'cancel' ? `Unfilled / cancelled: ${reason[e.reason]}` : ['buy', 'sell'].includes(d.action) ? 'An order is recorded; its execution outcome has not been published yet.' : 'No order was submitted by the simulator for this decision.';
    body.append(node('p', execution)); if (!trendRun()) evidence.append(node('p', 'JEV scores classify supplied headlines; they are not calibrated probabilities of market outcomes.', 'fine-print'));
    evidence.append(node('p', `Decision #${d.seq} · SHA-256 ${d.hash}\nObservation ${d.quality.observation_id}${trendRun() ? d.signal.trend ? `\nDaily close ${d.signal.trend.hash}` : '' : d.signal ? `\nForecast ${d.signal.forecast_id}\nInputs ${d.signal.input_hash}` : ''}`, 'audit-provenance'));
    technical.append(evidence); body.append(technical); item.append(body); return item;
  }
  function renderHistory() {
    const filter = $('action').value;
    const decisions = data.decisions.filter(d => d.account === selected && (filter === 'all' || (filter === 'trades' ? ['buy', 'sell'].includes(d.action) : d.action === filter)));
    const opened = new Set([...$('decisions').querySelectorAll('.audit-item[open]')].map(n => n.dataset.seq));
    const technicalOpened = new Set([...$('decisions').querySelectorAll('.technical-evidence[open]')].map(n => n.closest('.audit-item').dataset.seq));
    $('decisions').replaceChildren(...decisions.slice(0, historyLimit).map(d => { const item = audit(d); item.open = opened.has(String(d.seq)); item.querySelector('.technical-evidence').open = technicalOpened.has(String(d.seq)); return item; }));
    if (!decisions.length) $('decisions').append(node('p', filter === 'all' ? 'No decisions have been published for this portfolio yet.' : 'No decisions match this filter. Choose “All decisions” to see its recorded checks.', 'empty-explanation'));
    $('history-more').hidden = decisions.length <= historyLimit;
    text('history-more', `Show ${Math.min(6, decisions.length - historyLimit)} more decisions`);
    text('audit-note', `Showing ${Math.min(historyLimit, decisions.length)} of ${decisions.length} matching recent decisions. Full history is retained on the research server.`);
  }
  function render() {
    if (!data) return;
    const id = selected, a = data.accounts.find(value => value.id === id), initial = data.policy.starting_usd;
    const stale = Date.now() / 1000 - a.asof > 2100 || !a.fresh;
    const invested = Math.max(0, a.equity - a.cash);
    root.querySelectorAll('[data-portfolio]').forEach(card => {
      const account = data.accounts.find(v => slot(v.id) === card.dataset.portfolio);
      card.querySelector('.strategy-number').textContent = numbers[account.id]; card.querySelector('.strategy-title').textContent = names[account.id];
      card.querySelector('.strategy-model').textContent = cards[account.id][0]; card.querySelector('.strategy-description').textContent = cards[account.id][1];
      const old = Date.now() / 1000 - account.asof > 2100 || !account.fresh;
      card.setAttribute('aria-pressed', String(account.id === id));
      card.querySelector('[data-card-value]').textContent = `${old ? '≈ ' : ''}${money(account.equity)}`;
      card.querySelector('[data-card-return]').textContent = `${signedMoney(account.equity - initial)} (${signedPct(account.equity / initial - 1)})${old ? ' · last estimate' : ' since start'}`;
      card.querySelector('[data-card-state]').textContent = old ? 'Check data timestamp' : account.braked ? 'New buys paused' : `${pct(account.equity ? Math.max(0, 1 - account.cash / account.equity) : 0)} in crypto · ${account.fills} trades`;
      card.querySelector('[data-card-choice]').textContent = account.id === id ? 'Selected' : 'Select portfolio';
    });
    text('experiment-title', trendRun() ? 'No forecast. One fixed rule.' : commonStart() ? 'Equal holdings. Different decisions.' : 'Cash first. Buy only on a signal.');
    text('experiment-note', trendRun() ? 'The trend filter holds each coin in proportion to how many of its 7-, 14-, 28- and 56-day returns are positive, up to 20% per coin; the rest is cash. It is compared with a rebalanced 20 / 20 / 20 / 40 portfolio and with buy & hold. The rule was fixed from a published backtest before this run began.' : commonStart() ? 'All three start with the same target: 20% BTC, 20% ETH, 20% SOL and 40% cash. The AI portfolios can then buy or sell under the fixed rules; the reference holds. Initial buys use identical quantities, quotes and costs.' : 'The original experiment: AI + news and Price AI start in cash and wait for eligible forecasts. Buy & hold invests up to 20% per coin immediately. Their exposure can therefore differ from the start.');
    $('download').href = '/api/paper?run=' + encodeURIComponent(data.run);
    text('trade-breakdown', trendRun() ? 'All fills since this experiment began' : commonStart() ? `${Math.min(a.fills, 3)} setup buys · ${Math.max(0, a.fills - 3)} later trades` : 'All fills since this experiment began');
    text('started', `Started ${shortDate(data.started_at)} UTC`);
    text('selection-copy', `${names[id]} is selected.`);
    text('latest-note', trendRun() ? 'The rule reads completed daily closes only. Cash is its position whenever trailing returns are not positive. It has no stop and no drawdown brake.' : 'A forecast is an estimate. The entry threshold includes trading costs and an uncertainty allowance. Cash is a valid position when a signal is too weak.');
    text('selected-number', numbers[id]); text('selected-name', names[id]);
    $('selected-name').closest('.portfolio-detail').className = `portfolio-detail ${slot(id)}`;
    text('account-note', trendRun() ? (id === 'trend' ? 'A fixed trend rule on completed daily closes. No forecast, no news, no fitted parameter. All trades must still pass the market-data checks.' : id === 'rebalanced' ? 'The fair comparison: the same 60% crypto limit, always 20% per coin, restored when the weights drift more than five points.' : 'Buys 20% of each coin once and holds. Its weights drift with the market.') : commonStart() && id === 'reference' ? 'The same initial holdings, execution quotes and costs as the AI portfolios. This reference then holds its coins and remaining cash without AI adjustments.' : id === 'news-guarded' ? 'TimesFM price forecasts with JEV as a separate news filter. All buys must also pass the market-data and risk checks.' : id === 'price-only' ? 'TimesFM price forecasts with the same costs, data checks and risk limits as AI + news. This portfolio does not apply the news veto.' : 'A simple market comparison: one initial purchase attempt of up to $2,000 each in BTC, ETH and SOL, then hold the coins and remaining cash.');
    text('equity', `${stale ? '≈ ' : ''}${money(a.equity)}`); text('return', stale ? 'Last estimate · check timestamp' : `${signedMoney(a.equity - initial)} (${signedPct(a.equity / initial - 1)}) since start`);
    text('cash', money(a.cash)); text('exposure', `${pct(a.equity ? invested / a.equity : 0)} held in crypto`);
    text('fills', String(a.fills)); text('fees', `${money(a.fees)} in simulated fees`);
    text('drawdown', pct(a.max_drawdown)); text('brake', id === 'reference' || trendRun() ? 'Measured from its highest value' : a.braked ? '8% limit reached · new buys paused' : '8% fall pauses new buys');
    text('holdings-asof', `${stale ? 'Last available values' : 'Valued'} · ${shortDate(a.asof)} UTC`);
    const positions = a.positions.filter(p => p.quantity > 0);
    $('holdings-empty').hidden = positions.length > 0; $('holdings-table').hidden = positions.length === 0; $('holdings-footnote').hidden = positions.length === 0;
    text('holdings-empty', `All ${money(a.cash)} is in virtual cash. No coins are currently held. The latest decisions above explain why.`);
    rows($('holdings'), positions.map(p => [p.asset, p.quantity.toFixed(8), money(p.mark), money(p.quantity * (p.mark || 0)), pct(a.equity ? p.quantity * (p.mark || 0) / a.equity : 0), signedMoney(p.quantity * (p.mark || 0) - p.cost)]));
    const allocations = [{ name: 'Cash', value: a.cash, cls: 'cash' }, ...positions.map(p => ({ name: p.asset, value: p.quantity * (p.mark || 0), cls: p.asset.toLowerCase() }))];
    $('allocation').replaceChildren(...allocations.map(v => { const n = node('span', undefined, `allocation-${v.cls}`); n.style.flexGrow = String(v.value); return n; }));
    $('allocation').setAttribute('aria-label', allocations.map(v => `${v.name} ${pct(a.equity ? v.value / a.equity : 0)}`).join(', '));
    $('allocation-labels').replaceChildren(...allocations.map(v => node('span', `${v.name} ${money(v.value)} · ${pct(a.equity ? v.value / a.equity : 0)}`, `allocation-${v.cls}`)));
    rows($('comparison'), [...data.accounts.map(p => [`${numbers[p.id]} · ${names[p.id]}`, `${p.fresh && Date.now() / 1000 - p.asof <= 2100 ? '' : '≈ '}${money(p.equity)}`, signedMoney(p.equity - initial), pct(p.equity ? Math.max(0, 1 - p.cash / p.equity) : 0), p.fills]), ['Cash baseline', money(initial), '$0.00', '0.00%', 0]]);
    const trades = data.trades.filter(t => t.account === id);
    $('trade-empty').hidden = trades.length > 0; $('trade-table').hidden = trades.length === 0;
    text('trade-empty-note', a.fills > 0 ? 'Older trades exist in the full journal but are outside this public snapshot’s recent trade window.' : id === 'reference' ? 'The reference has not completed a purchase. Its recorded decisions explain any blocked or unfilled attempts.' : 'A completed trade appears here only after the signal, data and risk checks allow it and the simulator can execute it.');
    $('trade-empty').querySelector('strong').textContent = a.fills > 0 ? 'No trades in this recent snapshot.' : 'No trades completed yet.';
    rows($('trades'), trades.map(t => [shortDate(t.at), `${t.side === 'buy' ? 'Bought' : 'Sold'} ${t.asset}`, why[t.reason] || 'Not part of this snapshot', t.quantity.toFixed(8), money(t.price), money(t.gross), money(t.fee)]));
    // One line per action: trades with the same reason inside ten minutes belong to one decision round.
    const story = [];
    for (const t of trades.filter(t => t.reason)) {
      const last = story.at(-1);
      if (last && last.side === t.side && last.reason === t.reason && Math.abs(last.at - t.at) < 600) last.assets.unshift(t.asset);
      else story.push({ at: t.at, side: t.side, reason: t.reason, assets: [t.asset] });
    }
    $('trade-story').hidden = story.length === 0;
    $('trade-story').replaceChildren(...story.slice(0, 6).map(s => { const li = node('li'); li.append(node('time', shortDate(s.at) + ' UTC'), node('span', `${s.side === 'buy' ? 'Bought' : 'Sold'} ${s.assets.join(', ')}`), node('small', why[s.reason])); return li; }));
    latestDecisions(a); renderHistory();
    text('journal', `${data.journal.events} immutable journal entries. Server hash-chain check passed. Started ${date(data.started_at)}. Published ${date(data.generated_at)}. Experiment ${data.run}. This verifies the recorded chain, not the truth of market inputs.`);
    text('status', !$('error').hidden ? 'Update unavailable' : stale ? 'Data needs attention' : 'Latest snapshot available');
    $('status').dataset.state = stale || !$('error').hidden ? 'warning' : 'fresh';
    text('freshness', `Values: ${shortDate(a.asof)} UTC · updates about every 15 min`);
    $('freshness').title = `Valuation: ${date(a.asof)}. Published: ${date(data.generated_at)}.`;
    $('live').hidden = false; chart();
  }
  async function load() {
    if (loading) return;
    loading = true; $('refresh').disabled = true; $('run').disabled = true;
    const requestedRun = selectedRun;
    try {
      const response = await fetch('/api/paper' + (requestedRun ? '?run=' + encodeURIComponent(requestedRun) : ''), { cache: 'no-store', credentials: 'omit', signal: AbortSignal.timeout(12000) });
      if (!response.ok) throw new Error('unavailable');
      const next = await response.json();
      if (next.mode !== 'paper' || !Array.isArray(next.accounts)) throw new Error('invalid');
      if (requestedRun && next.run !== requestedRun) throw new Error('wrong_run');
      const changed = data?.run !== next.run;
      data = next; selectedRun = next.run;
      // Each experiment has its own accounts; keep the same visual slot when switching between them.
      if (!data.accounts.some(a => a.id === selected)) selected = (data.accounts.find(a => slot(a.id) === slot(selected)) || data.accounts[0]).id;
      if (changed) { historyLimit = 6; $('action').value = 'all'; $('decisions').replaceChildren(); }
      if (![...$('run').options].some(o => o.value === next.run)) $('run').replaceChildren(new Option(runName(next.run), next.run));
      $('run').value = next.run;
      const pageUrl = new URL(window.location.href); pageUrl.searchParams.set('run', next.run); history.replaceState(null, '', pageUrl);
      $('error').hidden = true; render();
      try {
        const listing = await fetch('/api/paper/runs', { cache: 'no-store', credentials: 'omit', signal: AbortSignal.timeout(6000) });
        if (listing.ok) {
          const list = await listing.json();
          if (Array.isArray(list.runs) && list.runs.some(r => r.run === data.run)) {
            $('run').replaceChildren(...list.runs.map(r => new Option(`${runName(r.run)} · ${shortDate(r.started_at)} UTC`, r.run)));
            $('run').value = data.run;
          }
        }
      } catch { /* The loaded snapshot remains usable when the experiment listing is unavailable. */ }
    } catch {
      if (data) { selectedRun = data.run; $('run').value = data.run; }
      $('error').hidden = false;
      text('error', data ? 'The requested update could not be loaded. The previous experiment and snapshot remain selected below; check their timestamps.' : 'The public snapshot is temporarily unavailable. No balance or trades have been invented. Please try again shortly.');
      text('status', 'UPDATE UNAVAILABLE');
      $('status').dataset.state = 'warning';
    } finally { loading = false; $('refresh').disabled = false; $('run').disabled = !data; }
  }
  root.querySelectorAll('[data-portfolio]').forEach(button => button.addEventListener('click', () => { selected = data.accounts.find(a => slot(a.id) === button.dataset.portfolio).id; historyLimit = 6; $('action').value = 'all'; render(); }));
  root.querySelectorAll('[data-chart-mode]').forEach(button => button.addEventListener('click', () => { chartMode = button.dataset.chartMode; chart(); }));
  $('run').addEventListener('change', () => { selectedRun = $('run').value; load(); });
  $('action').addEventListener('change', () => { historyLimit = 6; renderHistory(); });
  $('history-more').addEventListener('click', () => { historyLimit += 6; renderHistory(); });
  new ResizeObserver(() => { if (data && !$('live').hidden) chart(); }).observe($('equity-chart').parentElement);
  $('refresh').addEventListener('click', load);
  setInterval(() => { if (!document.hidden) load(); }, 60000);
  load();
}
