// Newsletter boundary and rendering. The research server supplies numbers and already-public headlines only;
// subscriber addresses exist solely in the site's own database and never travel back.
import { reasons, trendReasons } from './paper-schema.mjs';

export const assets = ['BTC', 'ETH', 'SOL'];
const names = { BTC: 'Bitcoin', ETH: 'Ethereum', SOL: 'Solana' };
const accountNames = { 'news-guarded': 'AI + news', 'price-only': 'Price AI', reference: 'Buy & hold', trend: 'Trend filter', rebalanced: 'Rebalanced' };
const runNames = { 'paper-v1': 'Cash start', 'paper-v2': 'Common start', 'paper-v3': 'Trend filter' };
const why = { initial_allocation: 'shared starting allocation', reference_entry: 'initial comparison purchase', positive_forecast: 'the forecast cleared the entry hurdle', negative_forecast: 'the forecast turned negative', position_stop: 'stop after a 6% fall below cost', allocation_limit: 'back within the allocation limits', trend_up: 'trailing returns support a larger position', trend_down: 'trailing returns support a smaller position', rebalance: 'weights drifted more than five points' };
const newsHosts = ['www.coindesk.com', 'coindesk.com', 'blog.ethereum.org'];
const changeHosts = ['cryptooracle.moinsen.dev', 'github.com', 'www.moinsen.dev'];

// The exact wording a subscriber agrees to. Changing it needs a new version; both are stored with every consent.
export const CONSENT_VERSION = '2026-09-19.1';
export const CONSENT_TEXT = 'Yes, send me the CryptoOracle field notes by email, about once a week: project updates, market and forecast summaries, news, and information about products and services by Moinsen (Ulrich Diedrichsen). I can unsubscribe at any time through the link in every email. No tracking of opens or clicks.';
// The standing note about who makes this. Wording follows the operator's own site.
export const PROMO = { headline: 'Made by Moinsen', body: 'CryptoOracle comes out of Uli Diedrichsen’s workshop in Hamburg: one human, an AI orchestra, real products. Stuck software project, or an idea you want to test before you build it?', cta: 'See what else we are building', url: 'https://www.moinsen.dev/en' };

function ensure(value) { if (!value) throw new Error('Invalid newsletter issue'); }
function keys(o, fields) { ensure(o && typeof o === 'object' && !Array.isArray(o)); ensure(Object.keys(o).sort().join(',') === [...fields].sort().join(',')); }
function num(n, min = 0, max = 1e15) { ensure(typeof n === 'number' && Number.isFinite(n) && n >= min && n <= max); }
function whole(n, max = 1e9) { num(n, 0, max); ensure(Number.isInteger(n)); }
function one(v, values) { ensure(values.includes(v)); }
function list(v, max) { ensure(Array.isArray(v) && v.length <= max); }
function words(v, max) { ensure(typeof v === 'string' && v.trim().length > 0 && v.length <= max && !/[\u0000-\u001f\u007f]/.test(v)); }
function link(v, hosts) { words(v, 300); const url = new URL(v); ensure(url.protocol === 'https:' && hosts.includes(url.hostname) && !url.username && !url.password); }

export function validateIssue(data) {
  keys(data, ['schema', 'id', 'start', 'end', 'generated_at', 'market', 'forecasts', 'portfolios', 'news', 'changes']);
  ensure(data.schema === 1 && typeof data.id === 'string' && /^\d{4}-W\d{2}$/.test(data.id));
  whole(data.start, 1e11); whole(data.end, 1e11); num(data.generated_at, data.end);
  // One completed week, Monday to Monday in UTC (1 January 1970 was a Thursday).
  ensure(data.end - data.start === 604800 && data.start % 86400 === 0 && (data.start / 86400 + 3) % 7 === 0);
  list(data.market, 3); ensure(data.market.length > 0 && new Set(data.market.map(m => m.asset)).size === data.market.length);
  for (const m of data.market) {
    keys(m, ['asset', 'close', 'change', 'low', 'high']); one(m.asset, assets);
    num(m.close, 1e-9); num(m.low, 1e-9); num(m.high, 1e-9); num(m.change, -0.99, 50); ensure(m.low <= m.close && m.close <= m.high);
  }
  keys(data.forecasts, ['issued', 'assets']); whole(data.forecasts.issued); list(data.forecasts.assets, 3);
  for (const f of data.forecasts.assets) {
    keys(f, ['asset', 'scored', 'miss', 'last_price_miss', 'inside_band', 'days', 'best', 'worst']); one(f.asset, assets);
    whole(f.scored); whole(f.inside_band); whole(f.days, 7); num(f.miss, 0, 10); num(f.last_price_miss, 0, 10);
    ensure(f.scored > 0 && f.inside_band <= f.scored && f.days >= 1);
    for (const call of [f.best, f.worst]) { keys(call, ['id', 'predicted', 'actual']); ensure(/^[a-f0-9]{64}$/.test(call.id)); num(call.predicted, -0.99, 50); num(call.actual, -0.99, 50); }
  }
  list(data.portfolios, 3); ensure(new Set(data.portfolios.map(p => p.run)).size === data.portfolios.length);
  for (const p of data.portfolios) {
    keys(p, ['run', 'started_at', 'accounts', 'trades']); ensure(/^paper-v[123]-[a-f0-9]{12}$/.test(p.run)); num(p.started_at, 1, data.end);
    const ids = p.run.startsWith('paper-v3-') ? ['trend', 'rebalanced', 'reference'] : ['news-guarded', 'price-only', 'reference'];
    const allowed = p.run.startsWith('paper-v3-') ? trendReasons : reasons;
    list(p.accounts, 3); ensure(p.accounts.length > 0 && new Set(p.accounts.map(a => a.id)).size === p.accounts.length);
    for (const a of p.accounts) { keys(a, ['id', 'equity', 'change', 'since_start']); one(a.id, ids); num(a.equity); num(a.change, -1, 50); num(a.since_start, -1, 50); }
    list(p.trades, 12);
    for (const t of p.trades) { keys(t, ['at', 'account', 'asset', 'side', 'reason']); num(t.at, data.start, data.end); one(t.account, ids); one(t.asset, assets); one(t.side, ['buy', 'sell']); one(t.reason, allowed); }
  }
  keys(data.news, ['collected', 'classified', 'items']); whole(data.news.collected); whole(data.news.classified); list(data.news.items, 5);
  for (const n of data.news.items) {
    keys(n, ['title', 'source', 'url', 'published_at', 'assets', 'tone', 'event']); words(n.title, 160); one(n.source, ['CoinDesk', 'Ethereum Blog']); link(n.url, newsHosts);
    if (n.published_at !== null) num(n.published_at, 1, data.end);
    list(n.assets, 3); ensure(n.assets.length > 0); n.assets.forEach(a => one(a, assets));
    one(n.tone, ['positive', 'negative', 'neutral', 'unclear']); one(n.event, ['security', 'regulation', 'network', 'exchange', 'market', 'other']);
  }
  list(data.changes, 6);
  for (const c of data.changes) { keys(c, ['date', 'title', 'summary', 'url']); ensure(/^\d{4}-\d{2}-\d{2}$/.test(c.date)); words(c.title, 120); words(c.summary, 400); link(c.url, changeHosts); }
  return data;
}

export function normalizeEmail(input) {
  if (typeof input !== 'string') return null;
  const email = input.trim().toLowerCase();
  // Deliberately plain: one @, a dotted domain, no spaces, quotes or control characters. The confirmation mail is the real test.
  return email.length <= 254 && /^[a-z0-9._%+-]{1,64}@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/.test(email) ? email : null;
}

const escape = v => String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const signed = (v, digits = 1) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v * 100).toFixed(digits)}%`;
const points = v => (v * 100).toFixed(2);
const money = v => `$${v.toLocaleString('en-US', { minimumFractionDigits: v < 1000 ? 2 : 0, maximumFractionDigits: v < 1000 ? 2 : 0 })}`;
const day = t => new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(t * 1000);
const stamp = t => new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }).format(t * 1000);

export function headline(issue) {
  const lead = issue.market.find(m => m.asset === 'BTC') || issue.market[0];
  return `${names[lead.asset]} ${lead.change >= 0 ? 'rose' : 'fell'} ${Math.abs(lead.change * 100).toFixed(1)}% this week`;
}

// One line per decision round: the same account, side and reason within ten minutes.
function rounds(trades) {
  const out = [];
  for (const t of trades) {
    const last = out.at(-1);
    if (last && last.account === t.account && last.side === t.side && last.reason === t.reason && Math.abs(t.at - last.at) < 600) last.assets.push(t.asset);
    else out.push({ at: t.at, account: t.account, side: t.side, reason: t.reason, assets: [t.asset] });
  }
  return out;
}

function sections(issue) {
  const out = [];
  out.push({ title: 'The market week', note: 'Binance spot, hourly closes in USDT.', rows: issue.market.map(m => [names[m.asset], `${money(m.close)} · ${signed(m.change)}`, `closes between ${money(m.low)} and ${money(m.high)}`]) });
  const f = issue.forecasts;
  out.push({ title: 'Forecasts meet reality', note: f.assets.length ? `${f.issued} 24-hour forecasts were locked this week. A miss is the absolute log-return error × 100, in percentage points; lower is better. Hourly forecasts overlap, so ${Math.max(...f.assets.map(a => a.days))} days of market are not ${Math.max(...f.assets.map(a => a.scored))} independent tests.` : `${f.issued} 24-hour forecasts were locked this week. None reached its deadline with a paired comparison yet.`,
    rows: f.assets.map(a => [names[a.asset], `model missed by ${points(a.miss)} pts · “price stays the same” by ${points(a.last_price_miss)} pts`, `${a.inside_band} of ${a.scored} inside the model’s own 80% range · closest call ${signed(a.best.predicted, 2)} vs ${signed(a.best.actual, 2)} · widest miss ${signed(a.worst.predicted, 2)} vs ${signed(a.worst.actual, 2)}`]) });
  for (const p of issue.portfolios) {
    const version = p.run.slice(0, 8);
    out.push({ title: `Paper portfolios · ${runNames[version]}`, note: p.trades.length ? 'Virtual money. Simulated fills with fees and slippage.' : 'Virtual money. No trades this week: every decision was to wait or hold.',
      rows: [...p.accounts.map(a => [accountNames[a.id], `${money(a.equity)} · ${signed(a.change, 2)} this week`, `${signed(a.since_start, 2)} since the start`]), ...rounds(p.trades).map(t => [stamp(t.at) + ' UTC', `${accountNames[t.account]} ${t.side === 'buy' ? 'bought' : 'sold'} ${t.assets.join(', ')}`, why[t.reason] || t.reason.replace(/_/g, ' ')])] });
  }
  return out;
}

// The archive page shows the same sections as the mail, as plain strings the page script places with textContent.
export function issueView(issue) {
  return {
    id: issue.id, title: `${headline(issue)}.`, period: `${day(issue.start)} – ${day(issue.end - 86400)} ${new Date(issue.end * 1000 - 86400000).getUTCFullYear()}`,
    blocks: sections(issue),
    news: { note: issue.news.items.length ? `${issue.news.collected} headlines collected, ${issue.news.classified} classified. A classification describes the headline; it is not a price forecast.` : `${issue.news.collected} headlines collected. None passed the relevance and materiality checks this week.`, items: issue.news.items.map(n => ({ title: n.title, url: n.url, meta: `${n.source} · ${n.event}, ${n.tone} · ${n.assets.join(', ')}` })) },
    changes: issue.changes.map(c => ({ title: c.title, url: c.url, summary: c.summary })),
  };
}

export function renderIssue(issue, { unsubscribeUrl, archiveUrl, operator }) {
  const period = `${day(issue.start)} – ${day(issue.end - 86400)} ${new Date(issue.end * 1000 - 86400000).getUTCFullYear()}`;
  const subject = `CryptoOracle field notes · ${headline(issue)}`;
  const blocks = sections(issue);
  const address = `${operator.name}, ${operator.street}, ${operator.postalCode} ${operator.city}, ${operator.country}`;
  const newsNote = issue.news.items.length ? `${issue.news.collected} headlines collected, ${issue.news.classified} classified. A classification describes the headline; it is not a price forecast.` : `${issue.news.collected} headlines collected. None passed the relevance and materiality checks this week.`;

  const text = [
    `CRYPTOORACLE · FIELD NOTES ${issue.id}`, period, '', `${headline(issue)}.`, '',
    ...blocks.flatMap(b => [b.title.toUpperCase(), ...b.rows.map(r => `- ${r[0]}: ${r[1]}${r[2] ? ` (${r[2]})` : ''}`), b.note, '']),
    'NEWS RADAR', ...issue.news.items.map(n => `- ${n.title} — ${n.source} · ${n.event}, ${n.tone} · ${n.assets.join(', ')}\n  ${n.url}`), newsNote, '',
    ...(issue.changes.length ? ['WHAT CHANGED IN THE SYSTEM', ...issue.changes.map(c => `- ${c.title}. ${c.summary}\n  ${c.url}`), ''] : []),
    PROMO.headline.toUpperCase(), PROMO.body, `${PROMO.cta}: ${PROMO.url}`, '',
    `Read this issue on the web: ${archiveUrl}`, 'Research information. No investment advice. No tracking of opens or clicks.',
    `You receive this because you confirmed your subscription at cryptooracle.moinsen.dev. Unsubscribe: ${unsubscribeUrl}`, address, operator.email,
  ].join('\n');

  const cell = 'padding:10px 0;border-top:1px solid #d8ddd0;vertical-align:top;font-size:14px;line-height:1.5';
  const block = b => `<h2 style="font:400 24px/1.2 Georgia,'Times New Roman',serif;letter-spacing:-.03em;margin:34px 0 10px;color:#203b34">${escape(b.title)}</h2><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">${b.rows.map(r => `<tr><td style="${cell};width:32%;font-weight:600;color:#203b34">${escape(r[0])}</td><td style="${cell};color:#203b34">${escape(r[1])}${r[2] ? `<br><span style="color:#5d6b62;font-size:13px">${escape(r[2])}</span>` : ''}</td></tr>`).join('')}</table><p style="font-size:12px;line-height:1.6;color:#5d6b62;margin:10px 0 0">${escape(b.note)}</p>`;
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>${escape(subject)}</title></head><body style="margin:0;padding:0;background:#f5f4ee;color:#203b34;font-family:Inter,-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"><div style="display:none;max-height:0;overflow:hidden">${escape(headline(issue))}. Forecasts scored, portfolios, headlines and what changed.</div><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f5f4ee"><tr><td align="center" style="padding:28px 16px"><table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%"><tr><td>
<p style="font:500 11px/1.6 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.13em;margin:0;color:#5d6b62">CRYPTOORACLE · FIELD NOTES ${escape(issue.id)} · ${escape(period.toUpperCase())}</p>
<h1 style="font:400 38px/1.05 Georgia,'Times New Roman',serif;letter-spacing:-.045em;margin:14px 0 6px;color:#203b34">${escape(headline(issue))}.</h1>
<p style="font-size:15px;line-height:1.6;color:#5d6b62;margin:0">Every forecast is locked, then scored in public. Here is the week, misses included.</p>
${blocks.map(block).join('')}
<h2 style="font:400 24px/1.2 Georgia,'Times New Roman',serif;letter-spacing:-.03em;margin:34px 0 10px;color:#203b34">News radar</h2>
${issue.news.items.map(n => `<p style="${cell};margin:0"><a href="${escape(n.url)}" style="color:#203b34;font-weight:600">${escape(n.title)}</a><br><span style="color:#5d6b62;font-size:13px">${escape(n.source)} · ${escape(n.event)}, ${escape(n.tone)} · ${escape(n.assets.join(', '))}</span></p>`).join('')}
<p style="font-size:12px;line-height:1.6;color:#5d6b62;margin:10px 0 0">${escape(newsNote)}</p>
${issue.changes.length ? `<h2 style="font:400 24px/1.2 Georgia,'Times New Roman',serif;letter-spacing:-.03em;margin:34px 0 10px;color:#203b34">What changed in the system</h2>${issue.changes.map(c => `<p style="${cell};margin:0"><a href="${escape(c.url)}" style="color:#203b34;font-weight:600">${escape(c.title)}</a><br><span style="color:#5d6b62;font-size:13px">${escape(c.summary)}</span></p>`).join('')}` : ''}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:38px 0 0;background:#173f36;border-radius:5px"><tr><td style="padding:26px 28px"><p style="font:500 11px/1.6 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.13em;margin:0 0 8px;color:#d7e2ce">${escape(PROMO.headline.toUpperCase())}</p><p style="font-size:15px;line-height:1.6;color:#f4f4e8;margin:0 0 16px">${escape(PROMO.body)}</p><a href="${escape(PROMO.url)}" style="display:inline-block;background:#dbeab4;color:#173f36;text-decoration:none;font-size:14px;font-weight:600;padding:11px 16px;border-radius:4px">${escape(PROMO.cta)} →</a></td></tr></table>
<p style="font-size:12px;line-height:1.7;color:#5d6b62;margin:30px 0 0;border-top:1px solid #d8ddd0;padding-top:18px"><a href="${escape(archiveUrl)}" style="color:#203b34">Read this issue on the web</a> · Research information. No investment advice. No tracking of opens or clicks.<br>You receive this because you confirmed your subscription at cryptooracle.moinsen.dev. <a href="${escape(unsubscribeUrl)}" style="color:#203b34">Unsubscribe</a>.<br>${escape(address)} · <a href="mailto:${escape(operator.email)}" style="color:#203b34">${escape(operator.email)}</a></p>
</td></tr></table></td></tr></table></body></html>`;
  return { subject, html, text };
}

export function renderConfirmation({ confirmUrl, operator }) {
  const subject = 'Please confirm: CryptoOracle field notes';
  const address = `${operator.name}, ${operator.street}, ${operator.postalCode} ${operator.city}, ${operator.country}`;
  const text = ['Please confirm your subscription', '', 'Someone entered this address at cryptooracle.moinsen.dev to receive the CryptoOracle field notes, about once a week.', '', `Confirm on the site (one button there): ${confirmUrl}`, '', 'What you agree to:', CONSENT_TEXT, '', 'If this was not you, do nothing. Without confirmation the address is deleted after seven days and receives no further mail.', '', address, operator.email].join('\n');
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escape(subject)}</title></head><body style="margin:0;padding:0;background:#f5f4ee;color:#203b34;font-family:Inter,-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f5f4ee"><tr><td align="center" style="padding:28px 16px"><table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%"><tr><td>
<p style="font:500 11px/1.6 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.13em;margin:0;color:#5d6b62">CRYPTOORACLE · FIELD NOTES</p>
<h1 style="font:400 32px/1.1 Georgia,'Times New Roman',serif;letter-spacing:-.04em;margin:14px 0 14px">Please confirm your address.</h1>
<p style="font-size:15px;line-height:1.6;margin:0 0 22px">Someone entered this address at cryptooracle.moinsen.dev to receive the CryptoOracle field notes, about once a week.</p>
<a href="${escape(confirmUrl)}" style="display:inline-block;background:#173f36;color:#fffefa;text-decoration:none;font-size:15px;font-weight:600;padding:13px 20px;border-radius:4px">Confirm on cryptooracle.moinsen.dev →</a>
<p style="font-size:13px;line-height:1.6;color:#5d6b62;margin:24px 0 0"><b style="color:#203b34">What you agree to:</b> ${escape(CONSENT_TEXT)}</p>
<p style="font-size:13px;line-height:1.6;color:#5d6b62;margin:14px 0 0">If this was not you, do nothing. Without confirmation the address is deleted after seven days and receives no further mail.</p>
<p style="font-size:12px;line-height:1.7;color:#5d6b62;margin:26px 0 0;border-top:1px solid #d8ddd0;padding-top:16px">${escape(address)} · <a href="mailto:${escape(operator.email)}" style="color:#203b34">${escape(operator.email)}</a></p>
</td></tr></table></td></tr></table></body></html>`;
  return { subject, html, text };
}
