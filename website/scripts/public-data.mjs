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

export function validateStudy(data) {
  exactKeys(data, ['schema', 'created_at', 'kind', 'experiment', 'horizon_skill', 'bands', 'trend']);
  assert.equal(data.schema, 1);
  assert.ok(Number.isInteger(data.created_at) && data.created_at > 1_700_000_000);
  assert.match(data.kind, /^exploratory historical study/, 'A backtest must not be relabelled as a forward result');
  const share = value => Number.isFinite(value) && value >= 0 && value <= 1;
  assert.ok(data.horizon_skill.length > 0 && data.bands.length > 0);
  for (const row of data.horizon_skill) {
    exactKeys(row, ['horizon', 'n', 'model_mae', 'persistence_mae', 'skill', 'direction', 'coverage', 'width']);
    assert.ok(Number.isInteger(row.horizon) && row.horizon > 0 && Number.isInteger(row.n) && row.n > 0);
    for (const field of ['model_mae', 'persistence_mae', 'width']) assert.ok(Number.isFinite(row[field]) && row[field] > 0);
    assert.ok(Number.isFinite(row.skill) && share(row.direction) && share(row.coverage));
  }
  for (const row of data.bands) {
    exactKeys(row, ['horizon', 'n', 'first_test_origin', 'point_skill', 'timesfm_raw', 'volatility_band']);
    assert.ok(Number.isInteger(row.n) && row.n > 0 && Number.isFinite(row.point_skill));
    for (const band of [row.timesfm_raw, row.volatility_band]) {
      exactKeys(band, ['coverage', 'width', 'interval_score']);
      assert.ok(share(band.coverage) && band.width > 0 && Number.isFinite(band.interval_score) && band.interval_score > 0);
    }
  }
  exactKeys(data.trend, ['lookbacks_days', 'max_crypto', 'universes']);
  assert.deepEqual(data.trend.lookbacks_days, [7, 14, 28, 56], 'Changing the frozen rule needs a new reviewed study');
  assert.deepEqual(Object.keys(data.trend.universes).sort(), ['october-2020-large-caps', 'project']);
  for (const universe of Object.values(data.trend.universes)) {
    exactKeys(universe, ['assets', 'first_day', 'last_day', 'days', 'scenarios', 'weekly_curves', 'next_week_mean_log_return']);
    assert.ok(universe.assets.every(asset => /^[A-Z]{2,5}$/.test(asset)) && universe.first_day < universe.last_day);
    assert.deepEqual(Object.keys(universe.scenarios).sort(), ['base', 'delay-and-double-costs', 'double-costs', 'one-day-delay'], 'Every variant must be reported');
    for (const scenario of Object.values(universe.scenarios)) {
      exactKeys(scenario, ['cost', 'lag', 'rebalanced', 'trend_filter', 'sharpe_gap_ci95']);
      for (const stats of [scenario.rebalanced, scenario.trend_filter]) {
        exactKeys(stats, ['cagr', 'sharpe', 'max_drawdown']);
        assert.ok(Number.isFinite(stats.cagr) && Number.isFinite(stats.sharpe) && share(stats.max_drawdown));
      }
      assert.ok(scenario.sharpe_gap_ci95.length === 2 && scenario.sharpe_gap_ci95.every(Number.isFinite) && scenario.sharpe_gap_ci95[0] <= scenario.sharpe_gap_ci95[1]);
    }
    let previous = 0;
    for (const point of universe.weekly_curves) {
      exactKeys(point, ['t', 'rebalanced', 'trend_filter']);
      assert.ok(point.t > previous && point.rebalanced > 0 && point.trend_filter > 0);
      previous = point.t;
    }
    for (const states of Object.values(universe.next_week_mean_log_return)) {
      exactKeys(states, ['up', 'down']);
      assert.ok(Number.isFinite(states.up) && Number.isFinite(states.down));
    }
  }
}

export function assertPublicText(text, filename) {
  for (const pattern of [/\b(?:\d{1,3}\.){3}\d{1,3}\b/, /\/Users\//, /\/home\/[^/]+\//, /AI_GATEWAY_API_KEY/, /ORACLE_AUTH_PASSWORD/, /BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY/, /(?:sk|vck)_[a-zA-Z0-9_-]{20,}/, /sourceMappingURL/]) {
    assert.ok(!pattern.test(text), `Private or development material found in ${filename}`);
  }
  if (filename.endsWith('.html')) {
    // One reviewed form exists on the whole site: the newsletter sign-up. It posts nowhere by itself (form-action 'none').
    const forms = text.match(/<form\b[^>]*>/gi) || [];
    assert.ok(!/<iframe\b/i.test(text) && (filename === 'newsletter/index.html' ? forms.length === 1 && /data-newsletter-form/.test(forms[0]) && !/\baction=/i.test(forms[0]) : forms.length === 0), `Unexpected data collection surface in ${filename}`);
    for (const match of text.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
      assert.match(match[1], /\bsrc="\/scripts\/(?:benchmark|home|paper|forecasts|newsletter)\.js"/, `Unapproved script in ${filename}`);
      assert.equal(match[2].trim(), '', `Inline script in ${filename}`);
    }
    assert.ok(!/\son[a-z]+\s*=/i.test(text), `Inline event handler in ${filename}`);
    assert.ok(!/<(?:img|script|iframe|video|audio)[^>]+src=["'](?:https?:)?\/\//i.test(text), `External embedded asset in ${filename}`);
    assert.ok(!/<link[^>]+rel=["'](?:stylesheet|preconnect|dns-prefetch|prefetch)["'][^>]+href=["']https?:/i.test(text), `External automatic connection in ${filename}`);
  }
}
