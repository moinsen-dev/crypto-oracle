"""Prospective shadow experiment: a pooled volatility band against TimesFM's own raw band. No trading opinion."""

import json
import math
import os
import time

import numpy as np

from . import config, learning, study
from .db import connect, digest, packed
from .forecast import store_forecast
from .report import block_interval

POLICY = {
    "version": "volatility-band-v1",
    "parent": config.EXPERIMENT,
    "horizons": [1, 4, 12, 24, 72],
    "spans": [24, 168, 720],
    "history_days": 365,
    "stride_hours": 6,
    "min_fit_samples": 1000,
    "quantiles": [0.1, 0.9],
    "review_days": 28,
    "required_interval_gain": 0.03,
    "coverage_range": [0.72, 0.88],
    "min_availability": 0.90,
    "auto_promote": False,
}
EXPERIMENT = "volband-v1-" + digest(POLICY)[:12]
MODELS = ("volband", "timesfm_path")


def init_schema():
    learning.init_schema()
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS volband_reviews (
          id TEXT PRIMARY KEY, experiment TEXT NOT NULL, asset TEXT NOT NULL,
          horizon INTEGER NOT NULL, window_start INTEGER NOT NULL, reviewed_at INTEGER NOT NULL,
          payload TEXT NOT NULL, UNIQUE(experiment,asset,horizon,window_start)
        );
        """)
        for action in ("UPDATE", "DELETE"):
            db.execute(
                f"CREATE TRIGGER IF NOT EXISTS immutable_volband_reviews_{action} BEFORE {action} "
                "ON volband_reviews BEGIN SELECT RAISE(ABORT, 'Learning evidence is immutable'); END"
            )
        db.execute(
            "INSERT OR IGNORE INTO learning_experiments VALUES(?,?,?)",
            (EXPERIMENT, int(time.time()), packed(POLICY)),
        )


def features_at(ts, lp, origin):
    """[1, log rv24, log rv168, log rv720] at the exact origin candle, or None if unavailable."""
    if len(ts) == 0:
        return None
    i = {int(t): idx for idx, t in enumerate(ts)}.get(origin)
    span = max(POLICY["spans"])
    # The same rule as for training samples: a gap would turn a multi-hour move into one "hourly" return.
    if i is None or i < span or ts[i] - ts[i - span] != span * 3600:
        return None
    vols = [study.trailing_volatility(lp, s)[i] for s in POLICY["spans"]]
    if any(not (v > 0) for v in vols):
        return None
    return [1.0, *(math.log(v) for v in vols)]


def fit(origin, horizon):
    """Pooled, chronological, no-look-ahead fit. Pure function of stored candles up to origin."""
    series = study.hourly_series()
    span = max(POLICY["spans"])
    cutoff = origin - POLICY["history_days"] * 86400
    design, moves, sample_ts = [], [], []
    for asset in config.ASSETS:
        ts, lp = series.get(asset, (np.array([]), np.array([])))
        if len(lp) <= span:
            continue
        vols = [study.trailing_volatility(lp, s) for s in POLICY["spans"]]
        for i in range(span, len(lp) - horizon, POLICY["stride_hours"]):
            t = int(ts[i])
            if not (cutoff <= t <= origin) or t + horizon * 3600 > origin:
                continue
            if ts[i] - ts[i - span] != span * 3600 or ts[i + horizon] - t != horizon * 3600:
                continue
            vol_vals = [v[i] for v in vols]
            if any(not (v > 0) for v in vol_vals):
                continue
            design.append([1.0, *(math.log(v) for v in vol_vals)])
            moves.append(lp[i + horizon] - lp[i])
            sample_ts.append(t)
    if len(design) < POLICY["min_fit_samples"]:
        return None
    x, moves = np.array(design), np.array(moves)
    beta = np.linalg.lstsq(x, np.log(np.abs(moves) + 1e-5), rcond=None)[0]
    z_lo, z_hi = np.quantile(moves / np.exp(x @ beta), POLICY["quantiles"])
    return {
        "method": "pooled-volatility-band-lstsq-v1",
        "horizon": horizon,
        "beta": beta.tolist(),
        "z_lo": float(z_lo),
        "z_hi": float(z_hi),
        "n": len(design),
        "first_sample_ts": min(sample_ts),
        "last_sample_ts": max(sample_ts),
        "policy": POLICY,
    }


def interval_score(row):
    return study.interval_score(math.log(row["lower"]), math.log(row["upper"]), math.log(row["actual"]))


def cycle():
    if os.getenv("ORACLE_VOLBAND_ENABLED") != "1":
        return {"state": "disabled"}
    init_schema()
    now = int(time.time())
    origin = now // 3600 * 3600
    with connect() as db:
        parents = {
            r["asset"]: r
            for r in db.execute(
                "SELECT * FROM forecasts WHERE experiment=? AND scope='live' AND model='timesfm' "
                "AND horizon=? AND origin=?",
                (config.EXPERIMENT, max(config.HORIZONS), origin),
            )
        }
    added = 0
    if parents:
        series = study.hourly_series()
        for horizon in POLICY["horizons"]:
            with connect() as db:
                have = {
                    (r[0], r[1])
                    for r in db.execute(
                        "SELECT asset,model FROM forecasts WHERE experiment=? AND horizon=? AND origin=? "
                        "AND model IN ('volband','timesfm_path')",
                        (EXPERIMENT, horizon, origin),
                    )
                }
            pending = [a for a in parents if (a, "volband") not in have or (a, "timesfm_path") not in have]
            if not pending:
                continue
            artifact = fit(origin, horizon)
            if artifact is None:
                continue
            artifact_id = digest(artifact)
            with connect() as db:
                db.execute(
                    "INSERT OR IGNORE INTO artifacts VALUES(?,?,?)", (artifact_id, now, packed(artifact))
                )
            for asset in pending:
                started = time.monotonic()
                parent = parents[asset]
                ts, lp = series.get(asset, (np.array([]), np.array([])))
                vec = features_at(ts, lp, origin)
                if vec is None:
                    continue
                base = parent["base"]
                s = math.exp(float(np.dot(vec, artifact["beta"])))
                lo, hi = base * math.exp(artifact["z_lo"] * s), base * math.exp(artifact["z_hi"] * s)
                target = origin + horizon * 3600
                features = {
                    "trailing_volatility_24h": math.exp(vec[1]),
                    "trailing_volatility_168h": math.exp(vec[2]),
                    "trailing_volatility_720h": math.exp(vec[3]),
                }
                parent_provenance = json.loads(parent["provenance"])
                if (asset, "volband") not in have:
                    store_forecast(
                        asset,
                        "volband",
                        origin,
                        horizon,
                        base,
                        [{"t": target, "p": base, "lo": lo, "hi": hi}],
                        features,
                        {
                            **parent_provenance,
                            "experiment": EXPERIMENT,
                            "parent_forecast_id": parent["id"],
                            "artifact_id": artifact_id,
                            "interval": "pooled 4-parameter volatility band, empirical q10-q90; shadow; not guaranteed",
                        },
                        (time.monotonic() - started) * 1000,
                        experiment=EXPERIMENT,
                    )
                    added += 1
                if (asset, "timesfm_path") not in have:
                    store_forecast(
                        asset,
                        "timesfm_path",
                        origin,
                        horizon,
                        base,
                        json.loads(parent["path"])[:horizon],
                        features,
                        {
                            **parent_provenance,
                            "experiment": EXPERIMENT,
                            "parent_forecast_id": parent["id"],
                            "artifact_id": None,
                            "interval": "TimesFM's own raw path truncated to this horizon; paired reference",
                        },
                        0.0,
                        experiment=EXPERIMENT,
                    )
                    added += 1
    assess()
    return {"state": "observing", "experiment": EXPERIMENT, "forecasts_added": added}


def assess():
    """One immutable verdict per completed 28-day origin window per asset/horizon; volband vs timesfm_path."""
    now = int(time.time())
    with connect() as db:
        for asset in config.ASSETS:
            for horizon in POLICY["horizons"]:
                first = db.execute(
                    "SELECT MIN(origin) FROM forecasts WHERE experiment=? AND asset=? AND horizon=? "
                    "AND model='volband'",
                    (EXPERIMENT, asset, horizon),
                ).fetchone()[0]
                if first is None:
                    continue
                span = POLICY["review_days"] * 86400
                start = first
                while start + span + horizon * 3600 <= now:
                    if db.execute(
                        "SELECT 1 FROM volband_reviews WHERE experiment=? AND asset=? AND horizon=? "
                        "AND window_start=?",
                        (EXPERIMENT, asset, horizon, start),
                    ).fetchone():
                        start += span
                        continue
                    rows = [
                        dict(r)
                        for r in db.execute(
                            "SELECT f.*,e.actual,e.actual_hash,e.covered FROM forecasts f "
                            "JOIN evaluations e ON e.forecast_id=f.id WHERE f.experiment=? AND f.scope='live' "
                            "AND f.asset=? AND f.horizon=? AND f.origin>=? AND f.origin<? AND e.evaluated_at<=?",
                            (EXPERIMENT, asset, horizon, start, start + span, now),
                        )
                    ]
                    groups = {m: {r["origin"]: r for r in rows if r["model"] == m} for m in MODELS}
                    common = sorted(
                        o
                        for o in set(groups["volband"]) & set(groups["timesfm_path"])
                        if groups["volband"][o]["actual_hash"] == groups["timesfm_path"][o]["actual_hash"]
                    )
                    days = {}
                    for o in common:
                        days.setdefault((o - start) // 86400, []).append(
                            [interval_score(groups[m][o]) for m in MODELS]
                        )
                    pairs = [np.mean(days[d], axis=0).tolist() for d in sorted(days)]
                    means = np.mean(pairs, axis=0) if pairs else [0.0, 0.0]
                    gain = float(1 - means[0] / means[1]) if pairs and means[1] else None
                    ci = block_interval(pairs) if len(days) == POLICY["review_days"] else None
                    coverage = {
                        m: float(np.mean([groups[m][o]["covered"] for o in common])) if common else None
                        for m in MODELS
                    }
                    interval_scores = {m: float(means[i]) if pairs else None for i, m in enumerate(MODELS)}
                    availability = len(common) / (span // 3600)
                    supported = (
                        availability >= POLICY["min_availability"]
                        and coverage["volband"] is not None
                        and POLICY["coverage_range"][0] <= coverage["volband"] <= POLICY["coverage_range"][1]
                        and gain is not None
                        and gain >= POLICY["required_interval_gain"]
                        and ci is not None
                        and ci[0] > 0
                    )
                    payload = {
                        "status": "supported_for_review" if supported else "inconclusive",
                        "start": start,
                        "end": start + span,
                        "n": len(common),
                        "availability": availability,
                        "coverage": coverage,
                        "interval_score": interval_scores,
                        "gain": gain,
                        "ci95": ci,
                        "forecast_ids": {m: [groups[m][o]["id"] for o in common] for m in MODELS},
                        "auto_promoted": False,
                    }
                    db.execute(
                        "INSERT INTO volband_reviews VALUES(?,?,?,?,?,?,?)",
                        (
                            digest([EXPERIMENT, asset, horizon, start]),
                            EXPERIMENT,
                            asset,
                            horizon,
                            start,
                            now,
                            packed(payload),
                        ),
                    )
                    start += span


def summary():
    """Read-only, public-safe progress per asset/horizon. Used by the CLI and the public export."""
    init_schema()
    entries = []
    with connect() as db:
        for asset in config.ASSETS:
            for horizon in POLICY["horizons"]:
                rows = {
                    m: {
                        r["origin"]: dict(r)
                        for r in db.execute(
                            "SELECT f.origin,f.id,f.lower,f.upper,e.actual,e.actual_hash,e.covered "
                            "FROM forecasts f LEFT JOIN evaluations e ON e.forecast_id=f.id "
                            "WHERE f.experiment=? AND f.scope='live' AND f.asset=? AND f.horizon=? AND f.model=?",
                            (EXPERIMENT, asset, horizon, m),
                        )
                    }
                    for m in MODELS
                }
                issued = len(rows["volband"])
                scored = sum(r["actual"] is not None for r in rows["volband"].values())
                paired = [
                    o
                    for o, r in rows["volband"].items()
                    if r["actual"] is not None
                    and o in rows["timesfm_path"]
                    and r["actual_hash"] == rows["timesfm_path"][o]["actual_hash"]
                ]
                coverage = {
                    m: float(np.mean([rows[m][o]["covered"] for o in paired])) if paired else None
                    for m in MODELS
                }
                scores = {
                    m: float(np.mean([interval_score(rows[m][o]) for o in paired])) if paired else None
                    for m in MODELS
                }
                first_origin = min(rows["volband"], default=None)
                review_row = db.execute(
                    "SELECT reviewed_at,payload FROM volband_reviews WHERE experiment=? AND asset=? "
                    "AND horizon=? ORDER BY window_start DESC LIMIT 1",
                    (EXPERIMENT, asset, horizon),
                ).fetchone()
                review = None
                if review_row:
                    p = json.loads(review_row["payload"])
                    review = {
                        "at": review_row["reviewed_at"],
                        **{
                            k: p[k]
                            for k in (
                                "status",
                                "start",
                                "end",
                                "n",
                                "availability",
                                "coverage",
                                "interval_score",
                                "gain",
                                "ci95",
                                "auto_promoted",
                            )
                        },
                    }
                entries.append(
                    {
                        "asset": asset,
                        "horizon": horizon,
                        "issued": issued,
                        "scored": scored,
                        "paired": len(paired),
                        "coverage": coverage,
                        "interval_score": scores,
                        "first_origin": first_origin,
                        "review_due": first_origin + POLICY["review_days"] * 86400 + horizon * 3600
                        if first_origin
                        else None,
                        "review": review,
                    }
                )
        started = db.execute(
            "SELECT started_at FROM learning_experiments WHERE id=?", (EXPERIMENT,)
        ).fetchone()
    return {
        "experiment": EXPERIMENT,
        "started_at": started[0] if started else None,
        "policy": POLICY,
        "entries": entries,
    }
