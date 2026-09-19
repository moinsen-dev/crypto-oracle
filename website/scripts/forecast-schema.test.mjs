import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validateForecasts, volbandExperiment, volbandPolicy } from '../src/lib/forecast-schema.mjs';

const fixture = JSON.parse(readFileSync(new URL('./fixtures/forecast-initial.json', import.meta.url)));

// A pending pair (no outcome yet) added on top of the untouched pre-volband fixture.
function volbandFixture() {
  const d = structuredClone(fixture);
  const origin = Math.floor(d.generated_at / 3600 - 5) * 3600, horizon = 4, parentId = 'd'.repeat(64);
  const record = model => ({
    id: (model === 'volband' ? 'a' : 'b').repeat(64),
    claim: {
      experiment: volbandExperiment, model, asset: 'BTC', origin, issued_at: origin + 2,
      target: origin + horizon * 3600, horizon, base: 100, prediction: 100, lower: 92, upper: 108,
      revision: '1d952420fba87f3c6dee4f240de0f1a0fbc790e3', input_hash: 'c'.repeat(64),
      artifact_id: model === 'volband' ? 'e'.repeat(64) : null, parent_id: parentId,
      // The public claim.path only ever carries {t,p}; the band itself lives in claim.lower/upper.
      path: model === 'volband'
        ? [{ t: origin + horizon * 3600, p: 100 }]
        : Array.from({ length: horizon }, (_, i) => ({ t: origin + (i + 1) * 3600, p: 100 })),
    },
    outcome: null, quality: null, actual_path: [], baselines: [],
  });
  d.records.push(record('volband'), record('timesfm_path'));
  const empty = { coverage: { volband: null, timesfm_path: null }, interval_score: { volband: null, timesfm_path: null } };
  d.volband = {
    experiment: volbandExperiment, started_at: origin, policy: volbandPolicy,
    entries: ['BTC', 'ETH', 'SOL'].flatMap(asset => volbandPolicy.horizons.map(h => asset === 'BTC' && h === horizon
      ? { asset, horizon: h, issued: 1, scored: 0, paired: 0, ...empty, first_origin: origin, review_due: origin + 28 * 86400 + h * 3600, review: null }
      : { asset, horizon: h, issued: 0, scored: 0, paired: 0, ...empty, first_origin: null, review_due: null, review: null })),
  };
  return d;
}
test('a pre-volband snapshot remains valid exactly as-is once the schema is upgraded', () => {
  const d = structuredClone(fixture);
  assert.ok(!('volband' in d));
  validateForecasts(d);
});
test('a volband snapshot with its paired band models and summary block validates once the flag is enabled', () => {
  const d = volbandFixture();
  validateForecasts(d);
  assert.ok(d.records.some(r => r.claim.model === 'volband') && d.records.some(r => r.claim.model === 'timesfm_path'));
});
test('unknown models, horizons or an unlisted top-level field are rejected in the volband shape too', () => {
  for (const mutate of [
    d => d.records.at(-2).claim.model = 'unknown_model',
    d => d.records.at(-2).claim.horizon = 2,
    d => d.volband.entries[0].horizon = 2,
    d => d.extra_top_level_field = 1,
  ]) { const d = volbandFixture(); mutate(d); assert.throws(() => validateForecasts(d)); }
});
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
