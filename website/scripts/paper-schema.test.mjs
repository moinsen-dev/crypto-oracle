import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validatePaper } from '../src/lib/paper-schema.mjs';

// Recorded first server run, kept outside public assets. No private data or credentials.
const fixture = JSON.parse(readFileSync(new URL('./fixtures/paper-initial.json', import.meta.url)));
test('the real server snapshot crosses the public boundary with balanced accounts', () => {
  assert.equal(validatePaper(fixture).trades.length, 3);
});
test('private holdings, raw headlines and extra nested fields are rejected', () => {
  for (const mutate of [d => { d.holdings = []; }, d => { d.accounts[0].email = 'private@example.com'; }, d => { d.decisions[0].news.title = 'private text'; }]) {
    const d = structuredClone(fixture); mutate(d); assert.throws(() => validatePaper(d));
  }
});
test('non-finite values, inconsistent balances and future decision inputs are rejected', () => {
  for (const mutate of [d => { d.accounts[0].equity += 100; }, d => { d.accounts[0].cash = -1; }, d => { d.accounts[0].positions[0].mark = Infinity; }, d => { d.decisions[0].signal.issued_at = d.generated_at + 3600; }, d => { d.decisions[0].quality.observed_at = d.decisions[0].at + 1; }]) {
    const d = structuredClone(fixture); mutate(d); assert.throws(() => validatePaper(d));
  }
});
test('a failed check cannot be presented as an all-clear', () => {
  const d = structuredClone(fixture); d.decisions[0].quality.checks[0].passed = false;
  assert.throws(() => validatePaper(d));
});

test('common-start policy requires an explicit new version and fixed initial weights', () => {
  const d = structuredClone(fixture);
  d.run = 'paper-v2-123456abcdef'; d.policy.version = 'paper-v2';
  d.policy.initial_weights = [.2, .2, .2];
  d.decisions[0].reason = 'initial_allocation';
  assert.equal(validatePaper(d), d);
  for (const mutate of [x => { x.policy.initial_weights = [.4, .4, .2]; }, x => { x.policy.version = 'paper-v1'; }, x => { x.decisions[0].at = x.started_at - 1; }, x => { x.policy.private_key = 'not-allowed'; }]) {
    const invalid = structuredClone(d); mutate(invalid); assert.throws(() => validatePaper(invalid));
  }
  const old = structuredClone(fixture); old.decisions[0].reason = 'initial_allocation';
  assert.throws(() => validatePaper(old));
});

test('a trade reason must match the recorded decision it points to', () => {
  const d = structuredClone(fixture);
  const filled = d.decisions.find(v => v.outcome === 'fill');
  const trade = d.trades.find(v => v.account === filled.account && v.asset === filled.asset);
  Object.assign(trade, { reason: filled.reason, decision: filled.seq });
  assert.equal(validatePaper(d), d);
  for (const mutate of [v => { v.reason = 'negative_forecast'; }, v => { v.reason = 'because I said so'; }, v => { delete v.decision; }, v => { v.decision = v.seq + 1; }, v => { v.note = 'free text'; }]) {
    const invalid = structuredClone(d); mutate(invalid.trades.find(v => v.seq === trade.seq)); assert.throws(() => validatePaper(invalid));
  }
  const many = structuredClone(d); many.decisions = Array.from({ length: 131 }, () => many.decisions[0]);
  assert.throws(() => validatePaper(many));
});

test('the exporter keeps every listed trade explained after many later holds', () => {
  // Produced by the real Python exporter from a synthetic ledger: buys, stop-loss sells, then 38 hours of holds.
  const explained = validatePaper(JSON.parse(readFileSync(new URL('./fixtures/paper-explained.json', import.meta.url))));
  assert.ok(explained.decisions.length > 90 && explained.trades.length === 15);
  const seen = new Map(explained.decisions.map(d => [d.seq, d]));
  assert.ok(explained.trades.every(t => seen.get(t.decision)?.outcome === 'fill'));
});

test('the trend run crosses the boundary only with its frozen rule, its own accounts and no news', () => {
  // Produced by the real Python exporter: uptrend entry, next-day reversal, then quiet hours.
  const trend = JSON.parse(readFileSync(new URL('./fixtures/paper-trend.json', import.meta.url)));
  assert.deepEqual(validatePaper(trend).accounts.map(a => a.id), ['trend', 'rebalanced', 'reference']);
  assert.ok(trend.trades.some(t => t.reason === 'trend_down') && trend.decisions.every(d => d.news === null));
  const entry = trend.decisions.find(d => d.account === 'trend' && d.signal.trend);
  for (const mutate of [
    d => { d.policy.lookback_days = [7, 14, 28]; }, d => { d.policy.rebalance_band = 0.2; }, d => { d.policy.news_hours = 6; },
    d => { d.accounts[0].id = 'price-only'; }, d => { d.decisions[0].news = { state: 'available', veto: false, version: 'jev-headlines-v1-000000000000', items: [] }; },
    d => { d.decisions.find(v => v.seq === entry.seq).signal.trend.share = 1 - entry.signal.trend.share; },
    d => { d.decisions.find(v => v.seq === entry.seq).signal.trend.lookbacks[0].positive = !entry.signal.trend.lookbacks[0].positive; },
    d => { d.decisions.find(v => v.seq === entry.seq).signal.target_weight = 0.15; },
    d => { d.decisions.find(v => v.account === 'rebalanced').reason = 'trend_up'; }, d => { d.decisions[0].reason = 'positive_forecast'; },
    d => { d.decisions.find(v => v.seq === entry.seq).signal.trend.origin += 3600; }, d => { d.run = 'paper-v4-123456abcdef'; },
  ]) { const invalid = structuredClone(trend); mutate(invalid); assert.throws(() => validatePaper(invalid)); }
  // The earlier runs cannot borrow the new vocabulary.
  const old = structuredClone(fixture); old.decisions[0].reason = 'trend_up'; assert.throws(() => validatePaper(old));
});
