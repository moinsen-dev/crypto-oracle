import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { validateResearch, validateStudy, assertPublicText } from './public-data.mjs';
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
