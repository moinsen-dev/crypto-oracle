import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { validateResearch, validateStudy, validateNewsStudy, validateSignalsStudy, validateMomentumStudy, assertPublicText } from './public-data.mjs';
const snapshot = JSON.parse(await readFile(new URL('../src/data/research.json', import.meta.url), 'utf8'));
const study = JSON.parse(await readFile(new URL('../src/data/study.json', import.meta.url), 'utf8'));

test('the reviewed snapshot is publishable; extra private fields are rejected', () => {
  validateResearch(snapshot);
  const copied = structuredClone(snapshot);
  copied.holdings = [{ quantity: 1 }];
  assert.throws(() => validateResearch(copied), /Unapproved/);
  delete copied.holdings;
  copied.results[0].owner = 'private account';
  assert.throws(() => validateResearch(copied), /Unapproved/);
});
test('missing or duplicate opportunities and non-finite metrics cannot masquerade as results', () => {
  const copied = structuredClone(snapshot);
  copied.results[1] = copied.results[0];
  assert.throws(() => validateResearch(copied), /Duplicate/);
  const invalid = structuredClone(snapshot);
  invalid.results[0].modelError = Infinity;
  assert.throws(() => validateResearch(invalid));
});
test('a proposed account cannot be relabelled live through the snapshot', () => {
  const copied = structuredClone(snapshot);
  copied.paperPortfolio.status = 'live';
  assert.throws(() => validateResearch(copied), /separately reviewed/);
});
test('private paths, embedded third-party scripts and forms fail the public boundary', () => {
  for (const html of ['<p>/home/example/private</p>', '<script src="https://tracker.invalid/a.js"></script>', '<script>alert(1)</script>', '<form action="/send"></form>', '<img src="https://external.invalid/pixel">']) {
    assert.throws(() => assertPublicText(html, 'index.html'));
  }
  assertPublicText('<script src="/scripts/benchmark.js" defer></script><a href="https://www.moinsen.dev">Moinsen</a>', 'index.html');
});
test('the study snapshot stays a labelled backtest with every variant reported', () => {
  validateStudy(study);
  const relabelled = structuredClone(study);
  relabelled.kind = 'live result';
  assert.throws(() => validateStudy(relabelled), /relabelled/);
  const selective = structuredClone(study);
  delete selective.trend.universes.project.scenarios['delay-and-double-costs'];
  assert.throws(() => validateStudy(selective), /Every variant/);
  const tuned = structuredClone(study);
  tuned.trend.lookbacks_days = [28];
  assert.throws(() => validateStudy(tuned), /frozen rule/);
  const extra = structuredClone(study);
  extra.bands[0].holdings = 1;
  assert.throws(() => validateStudy(extra), /Unapproved/);
});

const note = async name => JSON.parse(await readFile(new URL(`../src/data/${name}.json`, import.meta.url), 'utf8'));
test('the later field notes stay labelled backtests that report everything they tested', async () => {
  const news = await note('news-study'), signals = await note('signals-study'), momentum = await note('momentum-study');
  validateNewsStudy(news); validateSignalsStudy(signals); validateMomentumStudy(momentum);
  for (const [data, validate] of [[news, validateNewsStudy], [signals, validateSignalsStudy], [momentum, validateMomentumStudy]]) {
    const relabelled = structuredClone(data); relabelled.kind = 'live trading result';
    assert.throws(() => validate(relabelled), /relabelled/);
  }
  // Dropping the classes that did not work, or calling a one-period effect a finding, fails the build.
  const selective = structuredClone(news); selective.table = selective.table.slice(0, 50);
  assert.throws(() => validateNewsStudy(selective), /Every class/);
  const relaxed = structuredClone(news); const row = relaxed.table.find(r => r.fit.clear && !r.test.clear); row.holds = true;
  assert.throws(() => validateNewsStudy(relaxed), /both-periods rule/);
  const early = structuredClone(news); early.delay_seconds = 0;
  assert.throws(() => validateNewsStudy(early), /before the live feed/);
  const cherry = structuredClone(signals); cherry.trend_overlays.chosen_before_split = ['stable_30d:low', 'taker_7d:low', 'mood:low'];
  assert.throws(() => validateSignalsStudy(cherry), /before the split/);
  const fewer = structuredClone(signals); fewer.effects = fewer.effects.filter(e => e.signal !== 'mood'); fewer.tests = fewer.effects.length;
  assert.throws(() => validateSignalsStudy(fewer), /Every signal/);
  const tuned = structuredClone(momentum); tuned.primary.weeks = 1;
  assert.throws(() => validateMomentumStudy(tuned), /fixed in advance/);
  const survivors = structuredClone(momentum); survivors.pairs_no_longer_trading = 0;
  assert.throws(() => validateMomentumStudy(survivors), /no longer trade/);
  const hidden = structuredClone(momentum); delete hidden.universes['30'].portfolios['test · cost 0.5%'];
  assert.throws(() => validateMomentumStudy(hidden), /Both periods/);
});
