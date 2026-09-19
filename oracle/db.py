import contextlib
import hashlib
import json
import sqlite3
import time

from . import config


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(packed(value).encode()).hexdigest()


@contextlib.contextmanager
def connect():
    config.DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(config.DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def init():
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS candles (
            asset TEXT NOT NULL, ts INTEGER NOT NULL, close REAL NOT NULL CHECK(close>0),
            volume REAL NOT NULL, source TEXT NOT NULL, observed_at INTEGER NOT NULL,
            payload_hash TEXT NOT NULL, PRIMARY KEY(asset, ts)
        );
        CREATE TABLE IF NOT EXISTS candle_revisions (
            asset TEXT, ts INTEGER, observed_at INTEGER, close REAL, volume REAL, payload_hash TEXT,
            PRIMARY KEY(asset,ts,payload_hash)
        );
        CREATE TABLE IF NOT EXISTS news (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, url TEXT NOT NULL, title TEXT NOT NULL,
            published_at INTEGER, first_seen INTEGER NOT NULL, content_hash TEXT NOT NULL,
            cluster TEXT NOT NULL, assets TEXT NOT NULL, event_type TEXT NOT NULL,
            sentiment REAL, confidence REAL, classifier TEXT, classified_at INTEGER
        );
        CREATE INDEX IF NOT EXISTS news_seen ON news(first_seen);
        CREATE TABLE IF NOT EXISTS forecasts (
            id TEXT PRIMARY KEY, experiment TEXT NOT NULL, scope TEXT NOT NULL,
            asset TEXT NOT NULL, model TEXT NOT NULL, origin INTEGER NOT NULL,
            issued_at INTEGER NOT NULL, horizon INTEGER NOT NULL, target INTEGER NOT NULL,
            base REAL NOT NULL, prediction REAL NOT NULL, lower REAL, upper REAL,
            path TEXT NOT NULL, features TEXT NOT NULL, provenance TEXT NOT NULL,
            latency_ms REAL NOT NULL,
            UNIQUE(experiment, scope, asset, model, origin, horizon)
        );
        CREATE INDEX IF NOT EXISTS forecast_target ON forecasts(target);
        CREATE INDEX IF NOT EXISTS forecast_scope ON forecasts(experiment,scope,horizon,asset,origin);
        CREATE TRIGGER IF NOT EXISTS immutable_forecasts BEFORE UPDATE ON forecasts
            BEGIN SELECT RAISE(ABORT, 'Forecasts are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS no_delete_forecasts BEFORE DELETE ON forecasts
            BEGIN SELECT RAISE(ABORT, 'Forecasts are immutable'); END;
        CREATE TABLE IF NOT EXISTS evaluations (
            forecast_id TEXT PRIMARY KEY REFERENCES forecasts(id), actual REAL NOT NULL,
            evaluated_at INTEGER NOT NULL, absolute_log_error REAL NOT NULL,
            direction_correct INTEGER NOT NULL, covered INTEGER, pinball REAL,
            actual_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS holdings (
            asset TEXT PRIMARY KEY, quantity REAL NOT NULL CHECK(quantity>=0),
            average_cost REAL CHECK(average_cost>=0), updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
            name TEXT PRIMARY KEY, last_started INTEGER, last_success INTEGER,
            last_error TEXT, detail TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS source_polls (
            source TEXT NOT NULL, polled_at INTEGER NOT NULL, ok INTEGER NOT NULL,
            entries INTEGER NOT NULL, PRIMARY KEY(source,polled_at)
        );
        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY, created_at INTEGER NOT NULL, payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS news_evaluations (
            id TEXT PRIMARY KEY, news_id TEXT NOT NULL REFERENCES news(id),
            model TEXT NOT NULL, version TEXT NOT NULL, evaluated_at INTEGER NOT NULL,
            input_hash TEXT NOT NULL, input TEXT NOT NULL, answers TEXT NOT NULL,
            response TEXT NOT NULL, latency_ms REAL NOT NULL, sdk TEXT NOT NULL,
            UNIQUE(news_id,version)
        );
        CREATE TRIGGER IF NOT EXISTS immutable_news_evaluations BEFORE UPDATE ON news_evaluations
            BEGIN SELECT RAISE(ABORT, 'News evaluations are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS no_delete_news_evaluations BEFORE DELETE ON news_evaluations
            BEGIN SELECT RAISE(ABORT, 'News evaluations are immutable'); END;
        CREATE TABLE IF NOT EXISTS jev_attempts (
            id TEXT PRIMARY KEY, news_id TEXT NOT NULL REFERENCES news(id), version TEXT NOT NULL,
            started_at INTEGER NOT NULL, state TEXT NOT NULL, error TEXT
        );
        CREATE INDEX IF NOT EXISTS jev_attempt_time ON jev_attempts(started_at);
        CREATE INDEX IF NOT EXISTS jev_attempt_news ON jev_attempts(news_id,version);
        CREATE TABLE IF NOT EXISTS jev_backoff (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), retry_at INTEGER NOT NULL
        );
        """)
        for table in ("evaluations", "artifacts", "candle_revisions"):
            for action in ("UPDATE", "DELETE"):
                db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action} BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'Research evidence is immutable'); END"
                )


def job_start(name):
    with connect() as db:
        db.execute(
            "INSERT INTO jobs(name,last_started) VALUES(?,?) ON CONFLICT(name) "
            "DO UPDATE SET last_started=excluded.last_started",
            (name, int(time.time())),
        )


def job_end(name, detail=None, error=None):
    with connect() as db:
        if error:
            db.execute("UPDATE jobs SET last_error=? WHERE name=?", (str(error)[:400], name))
        else:
            db.execute(
                "UPDATE jobs SET last_success=?,last_error=NULL,detail=? WHERE name=?",
                (int(time.time()), packed(detail or {}), name),
            )
