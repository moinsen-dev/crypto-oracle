import assert from 'node:assert/strict';

function exactKeys(value, keys) {
  assert.ok(value && typeof value === 'object' && !Array.isArray(value), 'Expected an object');
  assert.deepEqual(Object.keys(value).sort(), [...keys].sort(), 'Unapproved public data fields');
}

export function validateResearch(data) {
  exactKeys(data, ['schemaVersion', 'publishedOn', 'measuredOn', 'scope', 'experiment', 'model', 'revision', 'contextHours', 'originsPerAsset', 'quote', 'metric', 'results', 'conclusion', 'paperPortfolio']);
  assert.equal(data.schemaVersion, 1);
  assert.equal(data.scope, 'exploratory-backtest');
  assert.equal(data.quote, 'USDT');
  assert.equal(data.contextHours, 512);
  assert.equal(data.originsPerAsset, 365);
  for (const field of ['publishedOn', 'measuredOn']) assert.match(data[field], /^\d{4}-\d{2}-\d{2}$/);
  assert.ok(data.measuredOn <= data.publishedOn, 'Cannot publish a measurement before its recorded date');
  assert.match(data.revision, /^[a-f0-9]{40}$/);
  assert.equal(data.results.length, 6);
  const seen = new Set();
  for (const row of data.results) {
    exactKeys(row, ['asset', 'horizon', 'modelError', 'baselineError', 'coverage']);
    assert.ok(['BTC', 'ETH', 'SOL'].includes(row.asset));
    assert.ok([24, 72].includes(row.horizon));
    const id = `${row.asset}/${row.horizon}`;
    assert.ok(!seen.has(id), 'Duplicate benchmark opportunity');
    seen.add(id);
    for (const field of ['modelError', 'baselineError']) assert.ok(Number.isFinite(row[field]) && row[field] > 0);
    assert.ok(Number.isFinite(row.coverage) && row.coverage >= 0 && row.coverage <= 100);
  }
  exactKeys(data.paperPortfolio, ['status', 'startingUsd']);
  assert.equal(data.paperPortfolio.status, 'proposed', 'A real portfolio needs a separately reviewed public schema');
  assert.equal(data.paperPortfolio.startingUsd, 10000);
}

export function assertPublicText(text, filename) {
  for (const pattern of [/\b(?:\d{1,3}\.){3}\d{1,3}\b/, /\/Users\//, /\/home\/[^/]+\//, /AI_GATEWAY_API_KEY/, /ORACLE_AUTH_PASSWORD/, /BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY/, /(?:sk|vck)_[a-zA-Z0-9_-]{20,}/, /sourceMappingURL/]) {
    assert.ok(!pattern.test(text), `Private or development material found in ${filename}`);
  }
  if (filename.endsWith('.html')) {
    assert.ok(!/<(?:iframe|form)\b/i.test(text), `Unexpected data collection surface in ${filename}`);
    for (const match of text.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
      assert.match(match[1], /\bsrc="\/scripts\/(?:benchmark|paper|forecasts)\.js"/, `Unapproved script in ${filename}`);
      assert.equal(match[2].trim(), '', `Inline script in ${filename}`);
    }
    assert.ok(!/\son[a-z]+\s*=/i.test(text), `Inline event handler in ${filename}`);
    assert.ok(!/<(?:img|script|iframe|video|audio)[^>]+src=["'](?:https?:)?\/\//i.test(text), `External embedded asset in ${filename}`);
    assert.ok(!/<link[^>]+rel=["'](?:stylesheet|preconnect|dns-prefetch|prefetch)["'][^>]+href=["']https?:/i.test(text), `External automatic connection in ${filename}`);
  }
}
