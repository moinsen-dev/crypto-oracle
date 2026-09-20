import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { validateIssue, normalizeEmail, renderIssue, renderConfirmation, issueView, headline, lead, CONSENT_TEXT, CONSENT_VERSION, PROMO } from '../src/lib/newsletter.mjs';

// Produced by the real Python issue builder from a synthetic week. No subscriber data exists on that side.
const issue = JSON.parse(readFileSync(new URL('./fixtures/newsletter-issue.json', import.meta.url)));
const operator = JSON.parse(readFileSync(new URL('../src/data/operator.json', import.meta.url)));
const links = { unsubscribeUrl: 'https://cryptooracle.moinsen.dev/api/newsletter/unsubscribe?token=abc.def', archiveUrl: 'https://cryptooracle.moinsen.dev/newsletter/?issue=2026-W38', operator };

test('the real exporter output crosses the newsletter boundary', () => {
  assert.equal(validateIssue(issue), issue);
  assert.equal(issue.portfolios.length, 1);
  assert.ok(issue.outlook.length === 3 && issue.bands.length === 2 && issue.market.every(m => m.compared_weeks === 12 && m.change_30d !== null && m.largest_move));
});
test('free text, private fields, foreign links and a different week shape are rejected', () => {
  for (const mutate of [
    d => { d.subscribers = ['a@example.org']; }, d => { d.news.items[0].body = 'full article text'; }, d => { d.news.items[0].url = 'https://evil.example/phish'; },
    d => { d.news.items[0].url = 'http://www.coindesk.com/x'; }, d => { d.news.items[0].url = 'https://user:pw@www.coindesk.com/x'; }, d => { d.news.items[0].title = 'x'.repeat(161); },
    d => { d.news.items[0].title = 'line\nbreak'; }, d => { d.news.items.push(...Array(5).fill(d.news.items[0])); }, d => { d.changes[0].url = 'https://example.org/'; },
    d => { d.end += 86400; }, d => { d.start += 3600; d.end += 3600; }, d => { d.market[0].change = Infinity; }, d => { d.market[0].close = d.market[0].high * 2; },
    d => { d.forecasts.assets[0].inside_band = d.forecasts.assets[0].scored + 1; }, d => { d.portfolios[0].accounts[0].id = 'price-only'; }, d => { d.portfolios[0].trades[0].reason = 'positive_forecast'; },
    d => { d.portfolios[0].trades[0].at = d.end + 1; }, d => { d.id = 'week-38'; }, d => { d.generated_at = d.end - 1; },
    // The added sections are held to the same standard: open claims only, consistent tallies, our own links.
    d => { d.schema = 1; }, d => { delete d.outlook; }, d => { d.outlook[0].target = d.generated_at - 1; }, d => { d.outlook[0].origin = d.generated_at + 3600; d.outlook[0].target = d.outlook[0].origin + 86400; },
    d => { d.outlook[0].id = '../../evil'; }, d => { d.outlook[0].model_band = [0.05, -0.05]; }, d => { d.outlook[0].trend_positive = 5; }, d => { d.outlook.push(d.outlook[0]); },
    d => { d.bands[0].volatility_band.inside = d.bands[0].n + 1; }, d => { d.bands[0].horizon = 2; }, d => { d.bands[0].note = 'free text'; },
    d => { d.market[0].calmer_weeks = 13; d.market[0].compared_weeks = 13; }, d => { d.market[0].largest_move.at = d.end + 3600; }, d => { d.market[0].comment = 'x'; },
    d => { d.news.mix.events.rumour = 1; }, d => { d.news.mix.tones.negative += 1; }, d => { d.news.mix.events.security = d.news.classified + 1; d.news.mix.tones = { negative: d.news.classified + 1 }; },
    d => { d.explainer.url = 'https://evil.example/'; }, d => { d.explainer.text = 'x'.repeat(601); }, d => { d.explainer.html = '<b>x</b>'; },
    d => { d.id = 'preview-2026-09-23'; },
  ]) { const d = structuredClone(issue); mutate(d); assert.throws(() => validateIssue(d)); }
});
test('addresses are normalised and doubtful input is refused', () => {
  assert.equal(normalizeEmail('  Uli@Moinsen.DEV '), 'uli@moinsen.dev');
  for (const bad of ['', 'no-at-sign', 'a@b', 'a@@b.de', 'a b@c.de', 'a@b..de', '"x"@b.de', 'a@-b.de', 'a@b.de\r\nBcc: x@y.z', `${'a'.repeat(65)}@b.de`, 'a@' + 'b'.repeat(250) + '.de', null, 42, ['a@b.de']]) assert.equal(normalizeEmail(bad), null);
});
test('the rendered issue carries every legally required part and no tracking', () => {
  const mail = renderIssue(issue, links);
  assert.match(mail.subject, /^CryptoOracle field notes · (Bitcoin|Ethereum|Solana) (rose|fell) \d+\.\d% this week$/);
  assert.ok(mail.subject.includes(headline(issue)));
  for (const body of [mail.html, mail.text]) {
    for (const needle of [links.unsubscribeUrl.replace('&', body === mail.html ? '&amp;' : '&'), operator.name, operator.street, operator.postalCode, operator.email, PROMO.url, 'No investment advice', 'No tracking of opens or clicks']) assert.ok(body.includes(needle), needle);
  }
  assert.ok(mail.html.includes(PROMO.headline.toUpperCase()) && mail.text.includes(PROMO.body));
  // No pixels, no remote images, no scripts, no redirect links: every href is a plain destination we list ourselves.
  assert.ok(!/<img|<script|<iframe|<link|<form/i.test(mail.html));
  const hrefs = [...mail.html.matchAll(/href="([^"]+)"/g)].map(m => m[1].replace(/&amp;/g, '&'));
  const allowed = new Set([links.unsubscribeUrl, links.archiveUrl, PROMO.url, `mailto:${operator.email}`, issue.explainer.url, ...issue.outlook.map(o => `https://cryptooracle.moinsen.dev/forecasts/?id=${o.id}`), ...issue.news.items.map(n => n.url), ...issue.changes.map(c => c.url)]);
  assert.ok(hrefs.length > 5 && hrefs.every(h => allowed.has(h)), hrefs.filter(h => !allowed.has(h)).join(' '));
});
test('the issue says what happened, what is claimed next and what it means, in both formats', () => {
  const mail = renderIssue(issue, links), intro = lead(issue);
  assert.match(intro, /^Bitcoin (gained|lost) \d+\.\d% to \$[\d,.]+, Ethereum .* and Solana .*\. For Bitcoin the week was (busier|calmer) than (all|\d+) of the previous 12 weeks\. Across \d+ scored 24-hour forecasts the model missed by \d+\.\d\d points on average; assuming no change at all missed by \d+\.\d\d\. This week (the model|doing nothing) was closer\.$/);
  for (const body of [mail.html, mail.text]) {
    for (const needle of [intro.replace(/&/g, '&amp;'), 'over 30 days', 'largest hourly move', 'trend portfolio aims for', 'Open the locked forecast', 'volatility band held', 'distinct stories by topic: network 67%, security 33%. By tone: negative 67%, positive 33%.', issue.explainer.title, 'not a recommendation']) assert.ok(body.includes(needle) || body.toLowerCase().includes(needle.toLowerCase()), needle);
  }
  assert.ok(mail.text.includes('WHAT THE SYSTEM EXPECTS NEXT') && mail.text.includes('THE RANGE EXPERIMENT') && mail.text.includes('ONE IDEA FROM THE NOTEBOOK'));
  // Solana has no volatility band in this fixture: its row must say so by omission, not with a made-up range.
  const sol = issueView(issue).blocks.find(b => b.title === 'What the system expects next').rows.find(r => r.label === 'Solana');
  assert.ok(!sol.subs.join(' ').includes('volatility band') && sol.link.url.endsWith(issue.outlook.find(o => o.asset === 'SOL').id));
  const view = issueView(issue);
  assert.deepEqual(Object.keys(view), ['id', 'title', 'period', 'lead', 'blocks', 'news', 'changes', 'explainer']);
  assert.ok(view.blocks.every(b => b.rows.every(r => typeof r.label === 'string' && typeof r.main === 'string' && Array.isArray(r.subs))));
});
test('a rolling operator preview is accepted only where it is asked for', () => {
  const rolling = structuredClone(issue);
  rolling.id = 'preview-2026-09-23'; rolling.start += 2 * 86400 + 10 * 3600; rolling.end = rolling.start + 604800; rolling.generated_at = rolling.end + 600;
  rolling.outlook = []; rolling.portfolios.forEach(p => { p.trades = p.trades.filter(t => t.at >= rolling.start); });
  rolling.market.forEach(m => { m.largest_move = null; });
  assert.throws(() => validateIssue(rolling));
  assert.equal(validateIssue(rolling, { preview: true }), rolling);
  assert.throws(() => validateIssue(issue, { preview: true }));
  const off = structuredClone(rolling); off.start += 60; off.end += 60;
  assert.throws(() => validateIssue(off, { preview: true }));
  assert.match(renderIssue(rolling, links).text, /\d+ Sep(t)?, \d\d:00 – \d+ Sep(t)?, \d\d:00 UTC/);
});
test('headline text from the outside world cannot inject markup', () => {
  const hostile = structuredClone(issue);
  hostile.news.items[0].title = 'Bitcoin "soars" <img src=x onerror=alert(1)> & more';
  hostile.changes[0].summary = '</p><script>alert(1)</script>';
  const mail = renderIssue(validateIssue(hostile), links);
  assert.ok(!mail.html.includes('<img') && !mail.html.includes('<script') && mail.html.includes('&lt;img src=x onerror=alert(1)&gt; &amp; more'));
  assert.ok(renderIssue(issue, links).html.includes('outage &amp; recovery &lt;update&gt;'));
});
test('an empty week still renders honestly', () => {
  const quiet = structuredClone(issue);
  quiet.news.items = []; quiet.news.mix = { events: {}, tones: {} }; quiet.changes = []; quiet.portfolios[0].trades = []; quiet.forecasts.assets = []; quiet.outlook = []; quiet.bands = [];
  quiet.market.forEach(m => { m.change_30d = null; m.largest_move = null; m.calmer_weeks = 0; m.compared_weeks = 0; });
  const mail = renderIssue(validateIssue(quiet), links);
  assert.ok(mail.text.includes('None passed the relevance and materiality checks this week.') && mail.text.includes('every decision was to wait or hold') && mail.text.includes('None reached its deadline'));
  assert.ok(!mail.text.includes('WHAT CHANGED IN THE SYSTEM') && !mail.text.includes('WHAT THE SYSTEM EXPECTS NEXT') && !mail.text.includes('THE RANGE EXPERIMENT') && !mail.text.includes('distinct stories'));
  assert.ok(!/undefined|null|NaN/.test(mail.text) && !/undefined|null|NaN/.test(mail.html.replace(/<[^>]+>/g, ' ')));
});
test('the confirmation mail states the consent and is the only mail an unconfirmed address ever gets', () => {
  const mail = renderConfirmation({ confirmUrl: 'https://cryptooracle.moinsen.dev/api/newsletter/confirm?token=abc', operator });
  for (const body of [mail.html, mail.text]) assert.ok(body.includes('confirm?token=abc') && body.includes('deleted after seven days') && body.includes(operator.street));
  assert.ok(mail.text.includes(CONSENT_TEXT) && !mail.html.includes(PROMO.url) && !/<img|<script/i.test(mail.html));
});
test('the consent wording cannot change without a new version', () => {
  // Every stored consent names a version; this pins each version to the exact words a subscriber saw.
  const known = { '2026-09-19.1': '92fcaad3a44c' };
  assert.ok(CONSENT_TEXT.includes('products and services by Moinsen') && CONSENT_TEXT.includes('unsubscribe at any time'));
  assert.equal(createHash('sha256').update(CONSENT_TEXT).digest('hex').slice(0, 12), known[CONSENT_VERSION], 'New wording needs a new CONSENT_VERSION and its hash here');
});
