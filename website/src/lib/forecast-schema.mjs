// Explicit public boundary: prices, hashes and numeric scores only, never raw model/news input.
import { createHash } from 'node:crypto';
export const models = ['timesfm', 'calibrated', 'fusion_market', 'fusion_news', 'volband', 'timesfm_path'];
export const assets = ['BTC', 'ETH', 'SOL'];
export const horizons = [1, 4, 12, 24, 72];
export const pairedModel = { volband: 'timesfm_path', timesfm_path: 'volband' };
export const policy = { version: 'calibration-shadow-v1', parent: 'v1-log512-h24-72-hourly', min_samples: 120, min_days: 21, window_days: 90, train_fraction: .75, min_train: 60, min_calibration: 30, shrinkage: 24, max_log_adjustment: .1, outcome_policy: 'outcome-three-venues-1pct-v1', review_days: 28, required_gain: .05, min_coverage: .70, min_availability: .90, auto_promote: false };
const canonical = o => JSON.stringify(Object.fromEntries(Object.entries(o).sort(([a], [b]) => a.localeCompare(b))));
export const experiment = 'learning-v1-' + createHash('sha256').update(canonical(policy)).digest('hex').slice(0, 12);
export const volbandPolicy = { version: 'volatility-band-v1', parent: 'v1-log512-h24-72-hourly', horizons: [1, 4, 12, 24, 72], spans: [24, 168, 720], history_days: 365, stride_hours: 6, min_fit_samples: 1000, quantiles: [.1, .9], review_days: 28, required_interval_gain: .03, coverage_range: [.72, .88], min_availability: .90, auto_promote: false };
export const volbandExperiment = 'volband-v1-' + createHash('sha256').update(canonical(volbandPolicy)).digest('hex').slice(0, 12);
function ensure(v) { if (!v) throw new Error('invalid_forecast_snapshot'); }
function keys(o, list) { ensure(o && typeof o === 'object' && !Array.isArray(o)); ensure(Object.keys(o).sort().join(',') === list.split(' ').sort().join(',')); }
function num(x, min = 0, max = 1e12) { ensure(typeof x === 'number' && Number.isFinite(x) && x >= min && x <= max); }
function integer(x, min = 0, max = 1e9) { num(x, min, max); ensure(Number.isInteger(x)); }
function nullable(x, min = 0, max = 1e12) { if (x !== null) num(x, min, max); }
function stamp(x) { integer(x, 1e9, 5e9); }
function hash(x) { ensure(typeof x === 'string' && /^[a-f0-9]{64}$/.test(x)); }
function member(x, values) { ensure(values.includes(x)); }
function bool(x) { ensure(typeof x === 'boolean'); }
function close(x, y) { ensure(Math.abs(x - y) <= 1e-8 * Math.max(1, Math.abs(y))); }
function list(a, max) { ensure(Array.isArray(a) && a.length <= max); }
function assetHorizon(o) { member(o.asset, assets); member(o.horizon, horizons); }

export function validateRecord(r, now) {
  keys(r, 'id claim outcome quality actual_path baselines'); hash(r.id);
  const c = r.claim;
  keys(c, 'experiment model asset origin issued_at target horizon base prediction lower upper revision input_hash artifact_id parent_id path');
  assetHorizon(c); member(c.model, models); member(c.experiment, [policy.parent, experiment, volbandExperiment]);
  ensure((c.model === 'calibrated') === (c.experiment === experiment));
  ensure((c.model in pairedModel) === (c.experiment === volbandExperiment));
  ensure(c.revision === '1d952420fba87f3c6dee4f240de0f1a0fbc790e3');
  for (const k of ['origin', 'issued_at', 'target']) stamp(c[k]);
  ensure(c.origin % 3600 === 0 && c.target === c.origin + c.horizon * 3600 && c.origin <= c.issued_at && c.issued_at < c.target && c.issued_at <= now);
  for (const k of ['base', 'prediction']) num(c[k], 1e-12);
  nullable(c.lower, 1e-12); nullable(c.upper, 1e-12);
  ensure((c.lower === null) === (c.upper === null));
  if (c.lower !== null) ensure(c.lower <= c.prediction && c.prediction <= c.upper);
  hash(c.input_hash); if (c.artifact_id !== null) hash(c.artifact_id); if (c.parent_id !== null) hash(c.parent_id);
  ensure(c.model !== 'calibrated' || (c.artifact_id && c.parent_id));
  ensure(c.model !== 'volband' || (c.artifact_id && c.parent_id));
  ensure(c.model !== 'timesfm_path' || (c.artifact_id === null && c.parent_id));
  // volband issues a single endpoint band with no opinion on the hours in between; every other model
  // (including its paired timesfm_path) keeps one point per hour, exactly like the original TimesFM path.
  const pathLength = c.model === 'volband' ? 1 : c.horizon;
  list(c.path, 72); ensure(c.path.length === pathLength);
  c.path.forEach((p, i) => { keys(p, 't p'); ensure(p.t === (c.model === 'volband' ? c.target : c.origin + (i + 1) * 3600)); num(p.p, 1e-12); });
  close(c.path.at(-1).p, c.prediction);
  const e = r.outcome;
  if (e !== null) {
    keys(e, 'actual evaluated_at actual_hash absolute_log_error pinball direction_correct covered interval_score');
    num(e.actual, 1e-12); stamp(e.evaluated_at); ensure(c.target <= e.evaluated_at && e.evaluated_at <= now); hash(e.actual_hash);
    num(e.absolute_log_error); close(e.absolute_log_error, Math.abs(Math.log(c.prediction / e.actual)));
    bool(e.direction_correct); ensure(e.direction_correct === (Math.sign(c.prediction - c.base) === Math.sign(e.actual - c.base)));
    nullable(e.pinball); nullable(e.interval_score); if (e.covered !== null) bool(e.covered);
    ensure((e.covered === null) === (c.lower === null));
    if (c.lower !== null) {
      ensure(e.covered === (c.lower <= e.actual && e.actual <= c.upper));
      const lo = Math.log(c.lower), hi = Math.log(c.upper), actual = Math.log(e.actual);
      close(e.interval_score, hi - lo + 10 * Math.max(0, lo - actual) + 10 * Math.max(0, actual - hi));
      const pin = (q, p) => Math.max(q * Math.log(e.actual / p), (q - 1) * Math.log(e.actual / p));
      close(e.pinball, (pin(.1, c.lower) + pin(.9, c.upper)) / 2);
    }
  }
  const q = r.quality;
  if (q !== null) {
    ensure(e !== null); keys(q, 'id at version status actual_observed_at divergence fx input_verified references');
    hash(q.id); stamp(q.at); ensure(q.at >= e.evaluated_at && q.at <= now);
    ensure(q.version === policy.outcome_policy);
    member(q.status, ['qualified', 'input_unverified', 'outcome_unverified', 'source_revised', 'reference_missing', 'fx_divergence', 'venue_divergence']);
    bool(q.input_verified); nullable(q.actual_observed_at, c.target, q.at); nullable(q.divergence); nullable(q.fx, 1e-12);
    list(q.references, 3); const seen = new Set();
    for (const v of q.references) {
      keys(v, 'source asset ts close observed_at payload_hash'); member(v.source, ['coinbase', 'kraken']);
      member(v.asset, [c.asset, 'USDT']); ensure(v.asset !== 'USDT' || v.source === 'coinbase');
      ensure(!seen.has(v.source + v.asset)); seen.add(v.source + v.asset);
      ensure(v.ts === c.target); num(v.close, 1e-12); stamp(v.observed_at); ensure(v.observed_at >= c.target && v.observed_at <= q.at); hash(v.payload_hash);
    }
    if (q.status === 'qualified') {
      ensure(q.input_verified && q.actual_observed_at !== null && q.actual_observed_at <= e.evaluated_at && q.references.length === 3 && q.fx !== null && Math.abs(q.fx - 1) <= .01 && q.divergence !== null && q.divergence <= .01);
      const fx = q.references.find(v => v.asset === 'USDT'); ensure(fx); close(fx.close, q.fx);
      const prices = [e.actual * q.fx, ...q.references.filter(v => v.asset === c.asset).map(v => v.close)];
      close(q.divergence, Math.max(...prices) / Math.min(...prices) - 1);
    }
  }
  list(r.actual_path, 72); let previous = c.origin;
  for (const p of r.actual_path) { keys(p, 't p'); ensure(p.t > previous && p.t % 3600 === 0 && p.t <= c.target && p.t <= now); num(p.p, 1e-12); previous = p.t; }
  if (e) { ensure(r.actual_path.at(-1)?.t === c.target); close(r.actual_path.at(-1).p, e.actual); }
  list(r.baselines, 4); const names = new Set();
  for (const b of r.baselines) { keys(b, 'model prediction error'); member(b.model, ['timesfm', 'persistence', 'momentum', 'volband', 'timesfm_path']); ensure(!names.has(b.model)); names.add(b.model); num(b.prediction, 1e-12); nullable(b.error); if (b.error !== null) { ensure(e); close(b.error, Math.abs(Math.log(b.prediction / e.actual))); } }
  return r;
}

// The live server keeps publishing the pre-volband shape until it is upgraded and the flag is enabled;
// 'volband' is the only key that may be added on top of the original eight.
function keysWithOptionalVolband(d) {
  ensure(d && typeof d === 'object' && !Array.isArray(d));
  const required = 'schema generated_at experiment started_at policy groups learning news records'.split(' ');
  const extra = Object.keys(d).filter(k => !required.includes(k));
  ensure(required.every(k => k in d) && (extra.length === 0 || (extra.length === 1 && extra[0] === 'volband')));
}

function validateVolband(v, now) {
  keys(v, 'experiment started_at policy entries'); ensure(v.experiment === volbandExperiment);
  nullable(v.started_at, 1e9, now); ensure(canonical(v.policy) === canonical(volbandPolicy));
  list(v.entries, 15); ensure(v.entries.length === 15);
  for (const e of v.entries) {
    keys(e, 'asset horizon issued scored paired coverage interval_score first_origin review_due review'); member(e.asset, assets); member(e.horizon, volbandPolicy.horizons);
    for (const k of ['issued', 'scored', 'paired']) integer(e[k]);
    ensure(e.paired <= e.scored && e.scored <= e.issued);
    keys(e.coverage, 'volband timesfm_path'); keys(e.interval_score, 'volband timesfm_path');
    for (const m of ['volband', 'timesfm_path']) { nullable(e.coverage[m], 0, 1); nullable(e.interval_score[m], -1e6, 1e6); }
    ensure((e.paired === 0) === (e.coverage.volband === null));
    nullable(e.first_origin, 1e9, now); nullable(e.review_due, 1e9, 5e9);
    ensure(e.first_origin === null ? (e.issued === 0 && e.review_due === null) : e.review_due === e.first_origin + 28 * 86400 + e.horizon * 3600);
    if (e.review !== null) {
      const r = e.review;
      keys(r, 'at status start end n availability coverage interval_score gain ci95 auto_promoted');
      member(r.status, ['supported_for_review', 'inconclusive']); stamp(r.at); stamp(r.start); stamp(r.end);
      ensure(r.end - r.start === 28 * 86400 && r.at <= now && r.at >= r.end + e.horizon * 3600);
      integer(r.n); num(r.availability, 0, 1); close(r.availability, r.n / 672);
      keys(r.coverage, 'volband timesfm_path'); keys(r.interval_score, 'volband timesfm_path');
      for (const m of ['volband', 'timesfm_path']) { nullable(r.coverage[m], 0, 1); nullable(r.interval_score[m], -1e6, 1e6); }
      nullable(r.gain, -1e9, 1); ensure(r.auto_promoted === false);
      if (r.ci95 !== null) { list(r.ci95, 2); ensure(r.ci95.length === 2); r.ci95.forEach(x => num(x, -1e9, 1)); ensure(r.ci95[0] <= r.ci95[1]); }
    }
  }
}

export function validateForecasts(d) {
  keysWithOptionalVolband(d); ensure(d.schema === 1 && d.experiment === experiment);
  stamp(d.generated_at); nullable(d.started_at, 1e9, d.generated_at); ensure(canonical(d.policy) === canonical(policy));
  list(d.records, 50); const ids = new Set(); d.records.forEach(r => { validateRecord(r, d.generated_at); ensure(!ids.has(r.id)); ids.add(r.id); });
  list(d.groups, 54);
  for (const g of d.groups) {
    keys(g, 'asset horizon model issued scored paired mae baseline_mae direction coverage calendar_days'); assetHorizon(g); member(g.model, models);
    for (const k of ['issued', 'scored', 'paired', 'calendar_days']) integer(g[k]);
    ensure(g.paired <= g.scored && g.scored <= g.issued); nullable(g.mae); nullable(g.baseline_mae); nullable(g.direction, 0, 1); nullable(g.coverage, 0, 1);
    ensure((g.paired === 0) === (g.mae === null));
  }
  list(d.learning, 6); ensure(d.learning.length === 6);
  for (const l of d.learning) {
    keys(l, 'asset horizon samples span_days training calibration ready issued evaluated first_origin review_due review'); assetHorizon(l);
    for (const k of ['samples', 'training', 'calibration', 'issued', 'evaluated']) integer(l[k]);
    num(l.span_days); bool(l.ready); ensure(l.training + l.calibration <= l.samples && l.evaluated <= l.issued);
    ensure(l.ready === (l.samples >= 120 && l.span_days >= 21 && l.training >= 60 && l.calibration >= 30));
    nullable(l.first_origin, 1e9, d.generated_at); nullable(l.review_due, 1e9, 5e9);
    ensure(l.first_origin === null ? l.review_due === null : l.review_due === l.first_origin + 28 * 86400 + l.horizon * 3600);
    if (l.review !== null) {
      const r = l.review; keys(r, 'at status start end n availability coverage interval_score_gain comparisons auto_promoted');
      member(r.status, ['supported_for_review', 'inconclusive']); stamp(r.at); stamp(r.start); stamp(r.end); ensure(r.end-r.start === 28*86400 && r.at <= d.generated_at && r.at >= r.end+l.horizon*3600);
      integer(r.n); num(r.availability, 0, 1); close(r.availability, r.n/672); nullable(r.coverage, 0, 1); nullable(r.interval_score_gain, -1e6, 1e6); ensure(r.auto_promoted === false);
      list(r.comparisons, 3); ensure(r.comparisons.length === 3);
      for (const c of r.comparisons) { keys(c, 'model gain ci95'); member(c.model, ['timesfm', 'persistence', 'momentum']); nullable(c.gain, -1e9, 1); if (c.ci95 !== null) { list(c.ci95, 2); ensure(c.ci95.length === 2); c.ci95.forEach(x => num(x, -1e9, 1)); ensure(c.ci95[0] <= c.ci95[1]); } }
    }
  }
  list(d.news, 6); ensure(d.news.length === 6);
  for (const n of d.news) { keys(n, 'asset horizon samples span_days news_ids issued'); assetHorizon(n); for (const k of ['samples', 'news_ids', 'issued']) integer(n[k]); num(n.span_days); }
  if ('volband' in d) validateVolband(d.volband, d.generated_at);
  return d;
}
