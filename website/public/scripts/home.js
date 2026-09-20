(() => {
  const root = document.querySelector('[data-live-now]');
  if (!root) return;
  const names = { BTC: 'Bitcoin', ETH: 'Ethereum', SOL: 'Solana' };
  const node = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const signed = v => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v * 100).toFixed(2)}%`;
  const stamp = t => new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }).format(t * 1000) + ' UTC';
  const ago = seconds => seconds < 90 ? 'a minute ago' : seconds < 5400 ? `${Math.round(seconds / 60)} minutes ago` : `${Math.round(seconds / 3600)} hours ago`;
  function card(entry) {
    const box = node('article', undefined, 'live-card'), head = node('div', undefined, 'live-card-head');
    head.append(node('span', entry.asset[0], 'coin-mark'), node('h3', names[entry.asset]));
    box.append(head);
    const o = entry.open, s = entry.scored;
    if (o) {
      const move = o.prediction / o.base - 1, line = node('p', undefined, 'live-claim');
      line.append(node('strong', signed(move), move < 0 ? 'down' : 'up'), node('span', ` expected by ${stamp(o.target)}`));
      box.append(line, node('p', `The model’s own 80% range: ${signed(o.lower / o.base - 1)} to ${signed(o.upper / o.base - 1)}. Locked ${stamp(o.origin)}.`, 'live-detail'));
    } else box.append(node('p', 'No open 24-hour forecast at the moment. Missing forecasts stay missing; nothing is filled in.', 'live-detail'));
    if (s) box.append(node('p', `Last scored: expected ${signed(s.prediction / s.base - 1)}, happened ${signed(s.actual / s.base - 1)}.`, 'live-detail'));
    const record = o || s;
    if (record) { const a = node('a', 'Open the record', 'text-link'); a.href = '/forecasts/?id=' + record.id; a.append(node('span', ' →')); a.lastChild.setAttribute('aria-hidden', 'true'); box.append(a); }
    return box;
  }
  (async () => {
    const cards = root.querySelector('[data-live-cards]');
    try {
      const response = await fetch('/api/forecasts?latest=1', { cache: 'no-store', credentials: 'omit', signal: AbortSignal.timeout(10000) });
      if (!response.ok) return;
      const data = await response.json();
      if (!Array.isArray(data.latest) || !data.latest.some(e => e.open || e.scored)) return;
      cards.replaceChildren(...data.latest.map(card));
      if (data.generated_at) root.querySelector('[data-live-note]').textContent += ` Journal published ${ago(Date.now() / 1000 - data.generated_at)}.`;
    } catch { /* The static sentence with the link to the journal stays in place. */ } finally { cards.dataset.loaded = ''; }
  })();
})();
