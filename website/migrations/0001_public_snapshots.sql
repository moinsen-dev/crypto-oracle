CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY CHECK(id=1),
  generated_at REAL NOT NULL,
  started_at REAL NOT NULL,
  payload TEXT NOT NULL CHECK(json_valid(payload))
);
