CREATE TABLE forecast_journal (
  id TEXT PRIMARY KEY, asset TEXT NOT NULL, horizon INTEGER NOT NULL, model TEXT NOT NULL,
  origin INTEGER NOT NULL, target INTEGER NOT NULL, generated_at INTEGER NOT NULL,
  payload TEXT NOT NULL CHECK(json_valid(payload))
);
CREATE INDEX forecast_filter ON forecast_journal(asset,horizon,model,origin DESC);
CREATE TRIGGER frozen_public_forecast BEFORE UPDATE ON forecast_journal
WHEN json_extract(OLD.payload,'$.claim') != json_extract(NEW.payload,'$.claim')
 OR (json_extract(OLD.payload,'$.outcome') IS NOT NULL
     AND (json_extract(NEW.payload,'$.outcome') IS NULL
          OR json_extract(OLD.payload,'$.outcome') != json_extract(NEW.payload,'$.outcome')))
 OR (json_extract(OLD.payload,'$.quality') IS NOT NULL
     AND (json_extract(NEW.payload,'$.quality') IS NULL
          OR json_extract(NEW.payload,'$.quality.at') < json_extract(OLD.payload,'$.quality.at')))
BEGIN SELECT RAISE(ABORT, 'immutable_forecast'); END;
CREATE TABLE learning_snapshot (
  id INTEGER PRIMARY KEY CHECK(id=1), generated_at INTEGER NOT NULL,
  payload TEXT NOT NULL CHECK(json_valid(payload))
);
