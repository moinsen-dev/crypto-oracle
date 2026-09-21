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

// The later field notes. Each file is the unedited output of one study command; these checks make sure it still
// says what it is, reports every class or variant it tested, and keeps the rule that was fixed in advance.
const finite = (...values) => values.every(v => Number.isFinite(v));
const span = v => Array.isArray(v) && v.length === 2 && finite(...v) && v[0] <= v[1];
function labelled(data, keys) {
  exactKeys(data, keys);
  assert.equal(data.schema, 1);
  assert.match(data.kind, /^exploratory historical/, 'A backtest must not be relabelled as a forward result');
  assert.match(data.kind, /not a forward claim$/, 'A backtest must not be relabelled as a forward result');
  assert.ok(Number.isInteger(data.created_at) && data.created_at > 1_700_000_000 && data.split === 1672531200);
}

export function validateNewsStudy(data) {
  labelled(data, ['schema', 'kind', 'created_at', 'corpus', 'delay_seconds', 'split', 'headlines', 'tests', 'expected_false_positives', 'table', 'rules']);
  assert.equal(data.corpus, 'https://huggingface.co/datasets/edaschau/bitcoin_news/resolve/main/BTC_match_title.csv');
  assert.ok(data.delay_seconds >= 900, 'A headline must not count before the live feed could have seen it');
  exactKeys(data.headlines, ['fit', 'test']);
  assert.equal(data.table.length, data.tests, 'Every class must be reported');
  assert.ok(data.tests >= 200 && data.rules.length === 6);
  for (const row of data.table) {
    exactKeys(row, ['class', 'horizon', 'fit', 'test', 'holds', 'size_holds', 'extra_holds']);
    assert.ok([1, 4, 24, 72].includes(row.horizon) && typeof row.class === 'string' && row.class.length < 80);
    for (const part of [row.fit, row.test]) {
      exactKeys(part, ['n', 'days', 'mean', 'ci95', 'clear', 'size', 'size_ci95', 'size_clear', 'extra', 'extra_ci95', 'extra_clear', 'before_24h']);
      assert.ok(Number.isInteger(part.n) && part.n >= 40 && part.days <= part.n && finite(part.mean, part.size, part.extra, part.before_24h) && span(part.ci95) && span(part.size_ci95) && span(part.extra_ci95));
      assert.equal(part.clear, part.ci95[0] > 0 || part.ci95[1] < 0);
    }
    // An effect counts only when both periods are clear of zero and agree in sign.
    assert.equal(row.holds, row.fit.clear && row.test.clear && (row.fit.mean > 0) === (row.test.mean > 0), 'The both-periods rule must not be relaxed');
  }
  for (const rule of data.rules) {
    exactKeys(rule, ['class', 'horizon', 'fit_mean', 'action', 'hours', 'hours_held', 'switches', 'return', 'max_drawdown', 'hold_return', 'hold_max_drawdown']);
    assert.ok(['step aside', 'hold only then'].includes(rule.action) && finite(rule.return, rule.hold_return, rule.max_drawdown));
  }
}

export function validateSignalsStudy(data) {
  labelled(data, ['schema', 'kind', 'created_at', 'split', 'tests', 'expected_false_positives', 'effects', 'trend_overlays']);
  assert.equal(data.effects.length, data.tests, 'Every combination must be reported');
  const signals = ['funding_7d', 'implied_vol', 'mood', 'stable_30d', 'taker_7d', 'vol_premium'];
  assert.deepEqual([...new Set(data.effects.map(e => e.signal))].sort(), signals, 'Every signal must be reported');
  for (const e of data.effects) {
    exactKeys(e, ['asset', 'signal', 'side', 'horizon', 'fit', 'test', 'holds']);
    assert.ok(['BTC', 'ETH', 'SOL'].includes(e.asset) && ['low', 'high'].includes(e.side) && [1, 3, 7, 14].includes(e.horizon));
    for (const part of [e.fit, e.test]) { exactKeys(part, ['days', 'mean', 'ci95', 'clear']); assert.ok(part.days >= 40 && finite(part.mean) && span(part.ci95)); assert.equal(part.clear, part.ci95[0] > 0 || part.ci95[1] < 0); }
    assert.equal(e.holds, e.fit.clear && e.test.clear && (e.fit.mean > 0) === (e.test.mean > 0), 'The both-periods rule must not be relaxed');
  }
  const o = data.trend_overlays;
  exactKeys(o, ['first_day', 'split_day', 'last_day', 'trend_rule', 'rebalanced', 'chosen_before_split', 'overlays']);
  assert.ok(o.first_day < o.split_day && o.split_day < o.last_day && o.chosen_before_split.length === 3);
  assert.deepEqual(o.overlays.map(x => `${x.signal}:${x.step_aside_when}`).sort(), signals.flatMap(s => [`${s}:high`, `${s}:low`]).sort(), 'Every overlay must be reported');
  // The three overlays named in advance are the three best of the years before the split, nothing else.
  assert.deepEqual([...o.overlays].sort((a, b) => b.fit.sharpe_gap - a.fit.sharpe_gap).slice(0, 3).map(x => `${x.signal}:${x.step_aside_when}`), o.chosen_before_split, 'Overlays must be chosen on the years before the split');
  for (const x of o.overlays) { exactKeys(x, ['signal', 'step_aside_when', 'fit', 'test']); exactKeys(x.test, ['cagr', 'sharpe', 'max_drawdown', 'sharpe_gap', 'sharpe_gap_ci95']); assert.ok(finite(x.fit.sharpe_gap, x.test.sharpe_gap) && span(x.test.sharpe_gap_ci95)); }
  for (const part of [o.trend_rule, o.rebalanced]) for (const period of [part.fit, part.test]) { exactKeys(period, ['cagr', 'sharpe', 'max_drawdown']); assert.ok(finite(period.cagr, period.sharpe) && period.max_drawdown > 0 && period.max_drawdown < 1); }
}

export function validateMomentumStudy(data) {
  labelled(data, ['schema', 'kind', 'created_at', 'pairs', 'pairs_no_longer_trading', 'split', 'primary', 'universes']);
  assert.deepEqual(data.primary, { weeks: 2, universe: 30, cost: 0.003, trend: false }, 'Changing the rule fixed in advance needs a new reviewed study');
  assert.ok(data.pairs > 300 && data.pairs_no_longer_trading > 50, 'The universe must include pairs that no longer trade');
  assert.deepEqual(Object.keys(data.universes).sort(), ['30', '50']);
  const rows = ['all coins equally', 'all coins equally · market trend', 'bitcoin only', ...[1, 2, 4].flatMap(w => [`strongest fifth · ${w}w`, `strongest fifth · ${w}w · market trend`])].sort();
  for (const u of Object.values(data.universes)) {
    exactKeys(u, ['first_week', 'last_week', 'weeks', 'distinct_coins', 'forced_exits', 'fifths', 'portfolios']);
    assert.ok(u.first_week < data.split && u.last_week > data.split && u.weeks.fit > 100 && u.weeks.test > 100 && Number.isInteger(u.forced_exits));
    assert.deepEqual(Object.keys(u.fifths).sort(), ['1', '2', '4'], 'Every lookback must be reported');
    for (const lookback of Object.values(u.fifths)) for (const period of [lookback.fit, lookback.test]) {
      exactKeys(period, ['weakest_to_strongest', 'strongest_minus_weakest', 'ci95', 'strongest_vs_universe_ci95']);
      assert.ok(period.weakest_to_strongest.length === 5 && finite(...period.weakest_to_strongest, period.strongest_minus_weakest) && span(period.ci95) && span(period.strongest_vs_universe_ci95));
    }
    assert.deepEqual(Object.keys(u.portfolios).sort(), ['fit · cost 0.3%', 'fit · cost 0.5%', 'test · cost 0.3%', 'test · cost 0.5%'], 'Both periods and both cost levels must be reported');
    for (const table of Object.values(u.portfolios)) {
      assert.deepEqual(Object.keys(table).sort(), rows, 'Every variant must be reported');
      for (const stats of Object.values(table)) assert.ok(finite(stats.cagr, stats.sharpe) && stats.max_drawdown >= 0 && stats.max_drawdown < 1);
    }
  }
}
