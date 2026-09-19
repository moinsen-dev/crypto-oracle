import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validateForecasts } from '../src/lib/forecast-schema.mjs';

const fixture = JSON.parse(readFileSync(new URL('./fixtures/forecast-initial.json', import.meta.url)));
test('Python journal export preserves both pending claims and qualified outcomes', () => {
  const d = validateForecasts(structuredClone(fixture));
  assert.ok(d.records.some(r => r.outcome === null));
  assert.ok(d.records.some(r => r.quality?.status === 'qualified'));
});
test('forecast publication excludes arbitrary private fields at every boundary', () => {
  for (const mutate of [d => d.holdings = [], d => d.records[0].claim.headline = 'private', d => d.records[0].quality.references[0].response = 'private', d => d.learning[0].prompt = 'private']) {
    const d = structuredClone(fixture); mutate(d); assert.throws(() => validateForecasts(d));
  }
});
test('outcomes cannot arrive early, claim false scores or approve divergent labels', () => {
  for (const mutate of [
    d => d.records[0].outcome.evaluated_at = d.records[0].claim.target-1,
    d => d.records[0].outcome.actual *= 2,
    d => d.records[0].outcome.direction_correct = !d.records[0].outcome.direction_correct,
    d => d.records[0].quality.divergence = .1,
    d => d.records[0].quality.references[0].ts += 3600,
    d => d.records[0].quality.references[0].observed_at = d.generated_at+1,
    d => d.records[0].quality.actual_observed_at = null,
  ]) { const d = structuredClone(fixture); mutate(d); assert.throws(() => validateForecasts(d)); }
});
test('experiment identity, learning gates and original reference remain explicit', () => {
  for (const mutate of [
    d => d.experiment = 'learning-v1-000000000000', d => d.policy.min_samples = 1,
    d => d.learning[0].ready = true, d => d.records[0].claim.base = Infinity,
    d => d.records[0].claim.path[0].t += 3600, d => d.records[0].claim.horizon = 1,
    d => d.records[0].claim.model = 'calibrated', d => d.records[0].claim.issued_at = d.records[0].claim.target,
  ]) { const d = structuredClone(fixture); mutate(d); assert.throws(() => validateForecasts(d)); }
});
