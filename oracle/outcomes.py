"""Append-only, independently checked outcome evidence for prospective learning."""

import json
import math
import time
from datetime import UTC, datetime

import httpx

from . import config
from .db import connect, digest, packed

VERSION = "outcome-three-venues-1pct-v1"
SOURCES = ("coinbase", "kraken")


def init_schema():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS outcome_candles (
          id TEXT PRIMARY KEY, source TEXT NOT NULL, asset TEXT NOT NULL, ts INTEGER NOT NULL,
          close REAL NOT NULL, observed_at INTEGER NOT NULL, payload_hash TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS outcome_lookup ON outcome_candles(source,asset,ts,observed_at);
        CREATE TABLE IF NOT EXISTS outcome_polls (
          source TEXT, asset TEXT, hour INTEGER, polled_at INTEGER, ok INTEGER,
          PRIMARY KEY(source,asset,hour)
        );
        CREATE TABLE IF NOT EXISTS outcome_reviews (
          seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
          forecast_id TEXT NOT NULL REFERENCES forecasts(id), reviewed_at INTEGER NOT NULL,
          version TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS outcome_review_forecast ON outcome_reviews(forecast_id,reviewed_at,seq);
        """)
        for table in ("outcome_candles", "outcome_reviews"):
            for action in ("UPDATE", "DELETE"):
                db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action} BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'Outcome evidence is immutable'); END"
                )


def normalize(source, asset, rows, now, start):
    result = []
    for raw in rows:
        stamp = float(raw[0])
        if not math.isfinite(stamp) or stamp != int(stamp):
            continue
        ts = int(stamp) + 3600  # Both providers label the opening of the bucket.
        if ts % 3600 or not start < ts <= now:
            continue  # In particular, Kraken always includes an uncommitted current bar.
        if source == "coinbase":
            low, high, opened, close, volume = map(float, raw[1:6])
        else:
            opened, high, low, close = map(float, raw[1:5])
            volume = float(raw[6])
        if not all(math.isfinite(v) for v in (low, high, opened, close, volume)):
            continue
        if not (0 < low <= min(opened, close) <= max(opened, close) <= high and volume > 0):
            continue
        h = digest(raw)
        result.append((digest([source, asset, ts, h]), source, asset, ts, close, now, h))
    return result


def collect():
    """At most seven public requests per hour; missing sources retry on the next worker cycle."""
    init_schema()
    now = int(time.time())
    hour = now // 3600 * 3600
    saved, failures = 0, []
    requests = [(s, a) for s in SOURCES for a in config.ASSETS] + [("coinbase", "USDT")]
    with httpx.Client(timeout=10, headers={"User-Agent": "CryptoOracle-outcomes/1"}) as client:
        for source, asset in requests:
            with connect() as db:
                poll = db.execute(
                    "SELECT * FROM outcome_polls WHERE source=? AND asset=? AND hour=?",
                    (source, asset, hour),
                ).fetchone()
                if poll and (poll["ok"] or now - poll["polled_at"] < 600):
                    continue
                last = db.execute(
                    "SELECT MAX(ts) FROM outcome_candles WHERE source=? AND asset=?", (source, asset)
                ).fetchone()[0]
            start = max(hour - 7 * 86400, last - 7200) if last else hour - 7 * 86400
            try:
                if source == "coinbase":
                    iso = lambda t: datetime.fromtimestamp(t, UTC).isoformat()
                    response = client.get(
                        f"https://api.exchange.coinbase.com/products/{asset}-USD/candles",
                        params={"granularity": 3600, "start": iso(start), "end": iso(hour)},
                    )
                    response.raise_for_status()
                    raw = response.json()
                else:
                    response = client.get(
                        "https://api.kraken.com/0/public/OHLC",
                        params={
                            "pair": ("XBT" if asset == "BTC" else asset) + "USD",
                            "interval": 60,
                            "since": start,
                        },
                    )
                    response.raise_for_status()
                    body = response.json()
                    if body.get("error"):
                        raise ValueError("provider_error")
                    raw = next(v for k, v in body["result"].items() if k != "last")
                normalized = normalize(source, asset, raw, int(time.time()), start)
                with connect() as db:
                    db.executemany("INSERT OR IGNORE INTO outcome_candles VALUES(?,?,?,?,?,?,?)", normalized)
                ok = any(r[3] == hour for r in normalized)
                saved += len(normalized)
            except (
                httpx.HTTPError,
                ValueError,
                TypeError,
                KeyError,
                IndexError,
                StopIteration,
                OverflowError,
            ):
                ok = False
            if not ok:
                failures.append(source + ":" + asset)
            with connect() as db:
                db.execute(
                    "INSERT OR REPLACE INTO outcome_polls VALUES(?,?,?,?,?)",
                    (source, asset, hour, now, int(ok)),
                )
    return {"bars_observed": saved, "unavailable": failures}


def input_verified(db, row):
    p = json.loads(row["provenance"])
    artifact = db.execute("SELECT * FROM artifacts WHERE id=?", (p.get("input_artifact_id"),)).fetchone()
    if not artifact or artifact["created_at"] > row["issued_at"]:
        return False
    data = json.loads(artifact["payload"])
    candles = data.get("candles", [])
    return bool(
        digest(data) == p.get("input_artifact_id")
        and p.get("model_revision") == config.MODEL_REVISION
        and p.get("quote") == "USDT"
        and row["origin"] <= row["issued_at"] < row["target"]
        and len(candles) == config.CONTEXT
        and candles[-1]["ts"] == row["origin"]
        and candles[-1]["close"] == row["base"]
        and all(
            c["observed_at"] <= row["issued_at"]
            and c["ts"] <= row["origin"]
            and math.isfinite(c["close"])
            and c["close"] > 0
            and (i == 0 or c["ts"] - candles[i - 1]["ts"] == 3600)
            for i, c in enumerate(candles)
        )
    )


def latest_review(db, forecast_id, cutoff):
    r = db.execute(
        "SELECT * FROM outcome_reviews WHERE forecast_id=? AND version=? AND reviewed_at<=? "
        "ORDER BY reviewed_at DESC,seq DESC LIMIT 1",
        (forecast_id, VERSION, cutoff),
    ).fetchone()
    return {**dict(r), "payload": json.loads(r["payload"])} if r else None


def review():
    init_schema()
    now = int(time.time())
    added = 0
    with connect() as db:
        rows = db.execute(
            "SELECT f.*,e.actual,e.actual_hash,e.evaluated_at FROM forecasts f "
            "JOIN evaluations e ON e.forecast_id=f.id WHERE f.scope='live' "
            "AND f.model IN ('timesfm','calibrated') AND f.target<=? "
            "AND (f.target>=? OR NOT EXISTS (SELECT 1 FROM outcome_reviews r WHERE r.forecast_id=f.id))",
            (now, now - 8 * 86400),
        ).fetchall()
        for row in rows:
            refs = []
            for source, asset in (("coinbase", row["asset"]), ("kraken", row["asset"]), ("coinbase", "USDT")):
                r = db.execute(
                    "SELECT * FROM outcome_candles WHERE source=? AND asset=? AND ts=? AND observed_at<=? "
                    "ORDER BY observed_at DESC,rowid DESC LIMIT 1",
                    (source, asset, row["target"], now),
                ).fetchone()
                refs.append(dict(r) if r else None)
            candle = db.execute(
                "SELECT * FROM candles WHERE asset=? AND ts=?", (row["asset"], row["target"])
            ).fetchone()
            revision = db.execute(
                "SELECT MIN(observed_at) FROM candle_revisions WHERE asset=? AND ts=? AND payload_hash=?",
                (row["asset"], row["target"], row["actual_hash"]),
            ).fetchone()[0]
            reason, divergence, fx = "qualified", None, refs[2]["close"] if refs[2] else None
            valid_input = input_verified(db, row)
            if not valid_input:
                reason = "input_unverified"
            elif revision is None or not row["target"] <= revision <= row["evaluated_at"]:
                reason = "outcome_unverified"
            elif not candle or candle["payload_hash"] != row["actual_hash"]:
                reason = "source_revised"
            elif not all(refs):
                reason = "reference_missing"
            elif abs(fx - 1) > 0.01:
                reason = "fx_divergence"
            else:
                prices = [row["actual"] * fx, refs[0]["close"], refs[1]["close"]]
                divergence = max(prices) / min(prices) - 1
                if divergence > 0.01:
                    reason = "venue_divergence"
            evidence = {
                "actual_hash": row["actual_hash"],
                "actual_observed_at": revision,
                "current_hash": candle["payload_hash"] if candle else None,
                "input_verified": valid_input,
                "references": refs,
                "reason": reason,
                "divergence": divergence,
                "fx": fx,
            }
            previous = latest_review(db, row["id"], now)
            if previous and previous["payload"] == evidence:
                continue
            ident = digest([row["id"], VERSION, evidence, previous["id"] if previous else None])
            added += db.execute(
                "INSERT OR IGNORE INTO outcome_reviews(id,forecast_id,reviewed_at,version,status,payload) "
                "VALUES(?,?,?,?,?,?)",
                (ident, row["id"], now, VERSION, reason, packed(evidence)),
            ).rowcount
    return {"reviews_added": added}
