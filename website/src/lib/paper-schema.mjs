// Shared publication boundary. Arbitrary database fields and free-form text are never accepted.
const forecastAccounts = ['news-guarded', 'price-only', 'reference'];
const trendAccounts = ['trend', 'rebalanced', 'reference'];
const assets = ['BTC', 'ETH', 'SOL'];
export const reasons = ['below_entry', 'reference_hold', 'execution_invalid', 'position_stop', 'allocation_limit', 'negative_forecast', 'data_quality', 'drawdown_brake', 'forecast_missing', 'forecast_stale', 'input_invalid', 'cooldown', 'news_veto', 'reference_entry', 'positive_forecast', 'pending_order', 'initial_allocation', 'initial_allocation_wait'];
// Third run: a fixed trend rule, no forecasts and no news.
export const trendReasons = ['within_band', 'trend_up', 'trend_down', 'rebalance', 'reference_entry', 'reference_hold', 'cooldown', 'data_quality', 'execution_invalid', 'allocation_limit', 'trend_input_missing', 'pending_order'];
const trendPolicyKeys = ['version', 'starting_usd', 'execution', 'fee_rate', 'slippage_rate', 'max_order_age', 'asset_weight', 'asset_cap', 'total_cap', 'lookback_days', 'rebalance_band', 'min_order_usd', 'max_book_age', 'max_spread_bps', 'max_divergence'];
const cancelReasons = ['order_expired', 'quote_before_decision', 'execution_invalid', 'insufficient_depth', 'execution_risk_limit', 'insufficient_position', 'initial_allocation_cancelled'];
const checkCodes = ['coinbase_fresh', 'kraken_fresh', 'binance_fresh', 'usd_pair_agreement', 'usdt_conversion', 'three_venue_agreement', 'spread'];
const policyKeys = ['version', 'starting_usd', 'execution', 'fee_rate', 'slippage_rate', 'max_order_age', 'entry_fraction', 'asset_cap', 'total_cap', 'cooldown_hours', 'drawdown_brake', 'position_stop', 'daily_vol_target', 'min_margin', 'vol_margin', 'band_margin', 'news_probability', 'news_hours', 'max_forecast_age', 'max_book_age', 'max_spread_bps', 'max_divergence', 'min_order_usd', 'reference_weights'];
function ensure(value) { if (!value) throw new Error('Invalid public paper snapshot'); }
function keys(o, fields) { ensure(o && typeof o === 'object' && !Array.isArray(o)); ensure(Object.keys(o).sort().join(',') === [...fields].sort().join(',')); }
function num(n, min = 0, max = 1e15) { ensure(typeof n === 'number' && Number.isFinite(n) && n >= min && n <= max); }
function nullable(n, min = 0) { if (n !== null) num(n, min); }
function one(v, values) { ensure(values.includes(v)); }
function bool(v) { ensure(typeof v === 'boolean'); }
function hash(v) { ensure(typeof v === 'string' && /^[a-f0-9]{64}$/.test(v)); }
function list(v, max) { ensure(Array.isArray(v) && v.length <= max); }
function stamp(v, end) { num(v, 1, end); }
function orderKey(v) { ensure(typeof v === 'string' && /^(order:)?decision:\d+:(news-guarded|price-only|reference|trend|rebalanced):(BTC|ETH|SOL)$/.test(v)); }

export function validatePaper(data) {
  keys(data, ['schema', 'mode', 'run', 'started_at', 'generated_at', 'policy', 'accounts', 'history', 'decisions', 'trades', 'reasons', 'journal']);
  ensure(data.schema === 1 && data.mode === 'paper' && /^paper-v[123]-[a-f0-9]{12}$/.test(data.run));
  num(data.generated_at); stamp(data.started_at, data.generated_at);
  const commonStart = data.run.startsWith('paper-v2-'), trendRun = data.run.startsWith('paper-v3-');
  const accounts = trendRun ? trendAccounts : forecastAccounts, allowed = trendRun ? trendReasons : reasons;
  ensure(data.policy?.execution === 'coinbase-usd' && data.policy.starting_usd === 10000);
  if (trendRun) {
    keys(data.policy, trendPolicyKeys);
    for (const key of trendPolicyKeys.filter(k => !['version', 'execution', 'lookback_days'].includes(k))) num(data.policy[key]);
    // The rule was frozen before the run; a different rule is a different experiment, not an update.
    ensure(data.policy.version === 'paper-v3' && JSON.stringify(data.policy.lookback_days) === '[7,14,28,56]' && data.policy.asset_weight === 0.2 && data.policy.total_cap === 0.6 && data.policy.rebalance_band === 0.05);
  } else {
    keys(data.policy, commonStart ? [...policyKeys, 'initial_weights'] : policyKeys);
    ensure(data.policy.version === (commonStart ? 'paper-v2' : 'paper-v1'));
    if (commonStart) ensure(JSON.stringify(data.policy.initial_weights) === '[0.2,0.2,0.2]');
    for (const key of policyKeys.filter(k => !['version', 'execution', 'reference_weights'].includes(k))) num(data.policy[key]);
    ensure(JSON.stringify(data.policy.reference_weights) === '[0.2,0.2,0.2]');
  }
  list(data.accounts, 3); ensure(data.accounts.length === 3);
  ensure(new Set(data.accounts.map(a => a.id)).size === 3);
  for (const a of data.accounts) {
    keys(a, ['id', 'cash', 'equity', 'asof', 'fresh', 'fees', 'turnover', 'realized', 'fills', 'braked', 'max_drawdown', 'positions']);
    one(a.id, accounts); stamp(a.asof, data.generated_at); bool(a.fresh); bool(a.braked);
    for (const k of ['cash', 'equity', 'fees', 'turnover', 'fills']) num(a[k]);
    num(a.realized, -1e15); num(a.max_drawdown, 0, 1);
    list(a.positions, 3); ensure(a.positions.length === 3 && new Set(a.positions.map(p => p.asset)).size === 3);
    for (const p of a.positions) {
      keys(p, ['asset', 'quantity', 'cost', 'mark']); one(p.asset, assets); num(p.quantity); num(p.cost); nullable(p.mark);
    }
    const identity = a.cash + a.positions.reduce((total, p) => total + p.quantity * (p.mark || 0), 0);
    ensure(Math.abs(identity - a.equity) < 0.01);
  }
  list(data.history, 3); ensure(data.history.length === 3 && new Set(data.history.map(h => h.account)).size === 3);
  for (const h of data.history) {
    keys(h, ['account', 'points']); one(h.account, accounts); list(h.points, 721);
    let previous = data.started_at;
    for (const p of h.points) {
      keys(p, ['at', 'equity', 'fresh']); stamp(p.at, data.generated_at); num(p.equity); bool(p.fresh);
      ensure(p.at >= previous); previous = p.at;
    }
  }
  // The 90 most recent decisions plus up to 40 older ones that ended in a fill, so listed trades stay explained.
  list(data.decisions, 130);
  for (const d of data.decisions) {
    keys(d, ['seq', 'at', 'account', 'asset', 'action', 'reason', 'hash', 'quality', 'signal', 'news', 'outcome', 'execution']);
    num(d.seq, 1); stamp(d.at, data.generated_at); one(d.account, accounts); one(d.asset, assets); hash(d.hash);
    one(d.action, ['hold', 'blocked', 'buy', 'sell']); one(d.reason, allowed); one(d.outcome, ['none', 'fill', 'cancel']);
    ensure(d.at >= data.started_at);
    if (d.reason.startsWith('initial_allocation')) ensure(commonStart);
    const q = d.quality;
    keys(q, ['checks', 'buy_ok', 'execution_ok', 'mark', 'fx', 'spread_bps', 'divergence', 'prices', 'ask_depth_usd', 'bid_depth_usd', 'observed_at', 'observation_id']);
    bool(q.buy_ok); bool(q.execution_ok); stamp(q.observed_at, d.at); hash(q.observation_id);
    for (const k of ['mark', 'fx', 'spread_bps', 'divergence', 'ask_depth_usd', 'bid_depth_usd']) nullable(q[k]);
    keys(q.prices, ['coinbase', 'kraken', 'binance']); Object.values(q.prices).forEach(v => nullable(v));
    list(q.checks, 7); ensure(q.checks.length === 7 && new Set(q.checks.map(c => c.code)).size === 7);
    q.checks.forEach(c => { keys(c, ['code', 'passed']); one(c.code, checkCodes); bool(c.passed); });
    ensure(q.buy_ok === q.checks.every(c => c.passed));
    if (trendRun) {
      ensure(d.news === null); keys(d.signal, ['trend', 'target_weight', 'weight']);
      nullable(d.signal.target_weight); if (d.signal.target_weight !== null) num(d.signal.target_weight, 0, 0.2);
      num(d.signal.weight, 0, 1);
      const t = d.signal.trend;
      if (t === null) ensure(d.signal.target_weight === null || d.account !== 'trend');
      else {
        keys(t, ['origin', 'close', 'hash', 'lookbacks', 'share']); stamp(t.origin, d.at); ensure(t.origin % 86400 === 0 && d.at - t.origin < 86400);
        num(t.close); hash(t.hash); list(t.lookbacks, 4); ensure(t.lookbacks.length === 4);
        t.lookbacks.forEach((l, i) => { keys(l, ['days', 'close', 'hash', 'positive']); ensure(l.days === [7, 14, 28, 56][i]); num(l.close); hash(l.hash); bool(l.positive); ensure(l.positive === t.close > l.close); });
        ensure(t.share === t.lookbacks.filter(l => l.positive).length / 4);
        if (d.account === 'trend') ensure(d.signal.target_weight !== null && Math.abs(d.signal.target_weight - 0.2 * t.share) < 1e-9);
      }
      if (['trend_up', 'trend_down'].includes(d.reason)) ensure(d.account === 'trend');
      if (d.reason === 'rebalance') ensure(d.account === 'rebalanced');
    } else if (d.signal !== null) {
      const s = d.signal;
      keys(s, ['forecast_id', 'origin', 'issued_at', 'target', 'prediction_usdt', 'lower_usdt', 'upper_usdt', 'expected_return', 'entry_threshold', 'daily_volatility', 'margin', 'input_hash']);
      hash(s.forecast_id); hash(s.input_hash); stamp(s.origin, d.at); stamp(s.issued_at, d.at); num(s.target, d.at);
      for (const k of ['prediction_usdt', 'lower_usdt', 'upper_usdt', 'entry_threshold', 'daily_volatility', 'margin']) num(s[k]);
      nullable(s.expected_return, -1); ensure(s.lower_usdt <= s.prediction_usdt && s.prediction_usdt <= s.upper_usdt);
    }
    const n = trendRun ? { state: 'unavailable', veto: false, version: 'jev-headlines-v1-000000000000', items: [] } : d.news;
    keys(n, ['state', 'veto', 'version', 'items']); one(n.state, ['available', 'partial', 'unavailable']); bool(n.veto);
    ensure(/^jev-headlines-v1-[a-f0-9]{12}$/.test(n.version)); list(n.items, 12);
    for (const i of n.items) {
      keys(i, ['id', 'evaluation_id', 'source', 'published_at', 'first_seen', 'evaluated_at', 'relevance', 'material', 'tone', 'event']);
      hash(i.id); hash(i.evaluation_id); one(i.source, ['CoinDesk', 'Ethereum Blog']);
      for (const k of ['published_at', 'first_seen', 'evaluated_at']) stamp(i[k], d.at);
      num(i.relevance, 0, 1); num(i.material, 0, 1); one(i.tone, ['positive', 'negative', 'neutral', 'unclear']);
      one(i.event, ['security', 'regulation', 'network', 'exchange', 'market', 'other']);
    }
    if (d.outcome === 'none') ensure(d.execution === null);
    else {
      const e = d.execution;
      const common = ['order_key', 'decision_key', 'observation_id', 'observed_at'];
      keys(e, [...common, ...(d.outcome === 'fill' ? ['side', 'quantity', 'gross', 'fee', 'price'] : ['reason'])]);
      orderKey(e.order_key); orderKey(e.decision_key); hash(e.observation_id); stamp(e.observed_at, data.generated_at);
      if (d.outcome === 'fill') {
        ensure(e.observed_at > d.at); one(e.side, ['buy', 'sell']);
        for (const k of ['quantity', 'gross', 'fee', 'price']) num(e[k]);
      } else one(e.reason, cancelReasons);
    }
  }
  list(data.trades, 60);
  const published = new Map(data.decisions.map(d => [d.seq, d]));
  for (const t of data.trades) {
    // Snapshots from before trade reasons were exported stay valid; a reason is never accepted without its decision.
    const explained = 'reason' in t || 'decision' in t;
    keys(t, ['seq', 'at', 'account', 'asset', 'side', 'quantity', 'price', 'gross', 'fee', 'hash', ...(explained ? ['reason', 'decision'] : [])]);
    stamp(t.at, data.generated_at); one(t.account, accounts); one(t.asset, assets); one(t.side, ['buy', 'sell']); hash(t.hash);
    for (const k of ['seq', 'quantity', 'price', 'gross', 'fee']) num(t[k]);
    if (!explained) continue;
    one(t.reason, allowed); num(t.decision, 1); ensure(Number.isInteger(t.decision) && t.decision < t.seq);
    const d = published.get(t.decision);
    if (d) ensure(d.account === t.account && d.asset === t.asset && d.reason === t.reason && d.action === t.side && d.outcome === 'fill' && d.execution.price === t.price);
  }
  ensure(data.reasons && typeof data.reasons === 'object' && !Array.isArray(data.reasons));
  for (const [key, count] of Object.entries(data.reasons)) { one(key, allowed); num(count); }
  keys(data.journal, ['events', 'head', 'verified']); num(data.journal.events); hash(data.journal.head); ensure(data.journal.verified === true);
  return data;
}
