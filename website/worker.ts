import { validatePaper } from './src/lib/paper-schema.mjs';
import { validateForecasts, assets, models } from './src/lib/forecast-schema.mjs';
import { timingSafeEqual } from 'node:crypto';

const headers = {
  'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store',
  'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
  'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'",
  'Strict-Transport-Security': 'max-age=31536000',
};
function json(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status, headers }); }

async function boundedBody(request: Request) {
  if (!request.body) throw new Error('missing body');
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > 900_000) { await reader.cancel(); throw new Error('too large'); }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return new TextDecoder().decode(bytes);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    if (!path.startsWith('/api/')) return env.ASSETS.fetch(request);
    try {
      if (path === '/api/learning' && request.method === 'GET') {
        const row = await env.PUBLIC_DB.prepare('SELECT payload FROM learning_snapshot WHERE id=1').first<{ payload: string }>();
        return row ? new Response(row.payload, { headers }) : json({ error: 'waiting_for_first_publication' }, 503);
      }
      if (path === '/api/forecasts' && request.method === 'GET') {
        const id = url.searchParams.get('id');
        if (id) {
          if (!/^[a-f0-9]{64}$/.test(id)) return json({ error: 'invalid_id' }, 400);
          const row = await env.PUBLIC_DB.prepare('SELECT payload,generated_at FROM forecast_journal WHERE id=?').bind(id).first<{ payload: string; generated_at: number }>();
          return row ? json({ record: JSON.parse(row.payload), generated_at: row.generated_at }) : json({ error: 'forecast_not_found' }, 404);
        }
        const asset = url.searchParams.get('asset') || 'BTC';
        const horizon = Number(url.searchParams.get('horizon') || 24);
        const model = url.searchParams.get('model') || 'timesfm';
        const status = url.searchParams.get('status') || 'all';
        const page = Number(url.searchParams.get('page') || 0);
        if (!assets.includes(asset) || ![24, 72].includes(horizon) || !models.includes(model) || !['all', 'pending', 'scored', 'awaiting'].includes(status) || !Number.isInteger(page) || page < 0 || page > 10000) return json({ error: 'invalid_filter' }, 400);
        const now = Math.floor(Date.now()/1000);
        const clauses: Record<string, string> = { all: '', scored: " AND json_extract(payload,'$.outcome') IS NOT NULL", pending: ` AND json_extract(payload,'$.outcome') IS NULL AND target>${now}`, awaiting: ` AND json_extract(payload,'$.outcome') IS NULL AND target<=${now}` };
        const where = 'WHERE asset=? AND horizon=? AND model=?' + clauses[status];
        const [rows, count, stamp] = await env.PUBLIC_DB.batch<{ payload: string; total: number; generated_at: number }>([
          env.PUBLIC_DB.prepare('SELECT payload,generated_at FROM forecast_journal ' + where + ' ORDER BY origin DESC,id DESC LIMIT 12 OFFSET ?').bind(asset, horizon, model, page*12),
          env.PUBLIC_DB.prepare('SELECT COUNT(*) AS total FROM forecast_journal ' + where).bind(asset, horizon, model),
          env.PUBLIC_DB.prepare('SELECT generated_at FROM learning_snapshot WHERE id=1'),
        ]);
        return json({ records: rows.results.map(r => JSON.parse(String(r.payload))), total: count.results[0].total, page, generated_at: stamp.results[0]?.generated_at ?? null });
      }
      if (path === '/api/paper/runs' && request.method === 'GET') {
        const rows = await env.PUBLIC_DB.prepare('SELECT run,started_at,generated_at FROM experiment_snapshots ORDER BY started_at DESC LIMIT 10').all();
        return json({ runs: rows.results });
      }
      if (path === '/api/paper' && request.method === 'GET') {
        const run = url.searchParams.get('run');
        if (run && !/^paper-v[12]-[a-f0-9]{12}$/.test(run)) return json({ error: 'invalid_run' }, 400);
        const query = run
          ? env.PUBLIC_DB.prepare('SELECT payload FROM experiment_snapshots WHERE run=?').bind(run)
          : env.PUBLIC_DB.prepare('SELECT payload FROM experiment_snapshots ORDER BY started_at DESC LIMIT 1');
        const row = await query.first<{ payload: string }>();
        if (run && !row) return json({ error: 'run_not_found' }, 404);
        return row ? new Response(row.payload, { headers }) : json({ mode: 'paper', state: 'waiting_for_first_publication' }, 503);
      }
      if (!['/api/publish', '/api/publish-forecasts'].includes(path) || request.method !== 'POST') return json({ error: 'not_found' }, 404);
      const supplied = new TextEncoder().encode(request.headers.get('Authorization') || '');
      const expected = new TextEncoder().encode(`Bearer ${env.PUBLISH_TOKEN}`);
      if (!env.PUBLISH_TOKEN || supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) return json({ error: 'unauthorized' }, 401);
      if (!request.headers.get('Content-Type')?.startsWith('application/json')) return json({ error: 'json_required' }, 415);
      if (path === '/api/publish-forecasts') {
        let snapshot;
        try { snapshot = validateForecasts(JSON.parse(await boundedBody(request))); }
        catch { return json({ error: 'invalid_forecast_snapshot' }, 400); }
        if (Math.abs(snapshot.generated_at-Date.now()/1000) > 180) return json({ error: 'stale_publication' }, 409);
        const { records, ...summary } = snapshot;
        const writes = records.map((r: { id: string; claim: { asset: string; horizon: number; model: string; origin: number; target: number } }) => env.PUBLIC_DB.prepare(
          'INSERT INTO forecast_journal(id,asset,horizon,model,origin,target,generated_at,payload) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET generated_at=excluded.generated_at,payload=excluded.payload WHERE excluded.generated_at>=forecast_journal.generated_at'
        ).bind(r.id, r.claim.asset, r.claim.horizon, r.claim.model, r.claim.origin, r.claim.target, snapshot.generated_at, JSON.stringify(r)));
        writes.push(env.PUBLIC_DB.prepare('INSERT INTO learning_snapshot(id,generated_at,payload) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET generated_at=excluded.generated_at,payload=excluded.payload WHERE excluded.generated_at>=learning_snapshot.generated_at').bind(snapshot.generated_at, JSON.stringify(summary)));
        try { await env.PUBLIC_DB.batch(writes); }
        catch (error) { if (String(error).includes('immutable_forecast')) return json({ error: 'immutable_forecast' }, 409); throw error; }
        return json({ ok: true, records: records.length });
      }
      let data;
      try { data = validatePaper(JSON.parse(await boundedBody(request))); }
      catch { return json({ error: 'invalid_public_snapshot' }, 400); }
      if (Math.abs(data.generated_at - Date.now() / 1000) > 180) return json({ error: 'stale_publication' }, 409);
      const results = await env.PUBLIC_DB.batch([
        env.PUBLIC_DB.prepare(
          'INSERT INTO experiment_snapshots(run,generated_at,started_at,payload) VALUES(?,?,?,?) ON CONFLICT(run) DO UPDATE SET generated_at=excluded.generated_at,payload=excluded.payload WHERE excluded.generated_at>experiment_snapshots.generated_at AND excluded.started_at=experiment_snapshots.started_at AND json_extract(excluded.payload,\'$.journal.events\')>=json_extract(experiment_snapshots.payload,\'$.journal.events\')'
        ).bind(data.run, data.generated_at, data.started_at, JSON.stringify(data)),
        // Retain the latest-run slot so rolling back the website never discards prior data.
        env.PUBLIC_DB.prepare(
        'INSERT INTO snapshots(id,generated_at,started_at,payload) SELECT 1,generated_at,started_at,payload FROM experiment_snapshots WHERE run=? ON CONFLICT(id) DO UPDATE SET generated_at=excluded.generated_at,started_at=excluded.started_at,payload=excluded.payload WHERE excluded.generated_at>snapshots.generated_at AND excluded.started_at>=snapshots.started_at'
        ).bind(data.run),
      ]);
      return results[0].meta.changes ? json({ ok: true, events: data.journal.events }) : json({ error: 'older_snapshot' }, 409);
    } catch {
      // No request bodies, authorization values or visitor metadata are logged.
      return json({ error: 'temporarily_unavailable' }, 503);
    }
  },
} satisfies ExportedHandler<Env>;
