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
