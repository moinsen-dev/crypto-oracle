CREATE TABLE IF NOT EXISTS experiment_snapshots (
  run TEXT PRIMARY KEY,
  generated_at REAL NOT NULL,
  started_at REAL NOT NULL,
  payload TEXT NOT NULL CHECK(json_valid(payload))
);
INSERT OR IGNORE INTO experiment_snapshots(run, generated_at, started_at, payload)
SELECT json_extract(payload, '$.run'), generated_at, started_at, payload FROM snapshots;
