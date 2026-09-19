"""Frozen, delayed-feedback calibration experiment. Never selects a paper policy."""

import json
import math
import os
import time

import numpy as np

from . import config, outcomes
from .db import connect, digest, packed
from .forecast import store_forecast
from .report import block_interval

POLICY = {
    "version": "calibration-shadow-v1",
    "parent": config.EXPERIMENT,
    "min_samples": 120,
    "min_days": 21,
    "window_days": 90,
    "train_fraction": 0.75,
    "min_train": 60,
    "min_calibration": 30,
    "shrinkage": 24,
    "max_log_adjustment": 0.1,
    "outcome_policy": outcomes.VERSION,
    "review_days": 28,
    "required_gain": 0.05,
    "min_coverage": 0.70,
    "min_availability": 0.90,
    "auto_promote": False,
}
EXPERIMENT = "learning-v1-" + digest(POLICY)[:12]


def init_schema():
    outcomes.init_schema()
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS learning_experiments (
          id TEXT PRIMARY KEY, started_at INTEGER NOT NULL, policy TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS learning_reviews (
          id TEXT PRIMARY KEY, experiment TEXT NOT NULL, asset TEXT NOT NULL,
          horizon INTEGER NOT NULL, window_start INTEGER NOT NULL, reviewed_at INTEGER NOT NULL,
          payload TEXT NOT NULL, UNIQUE(experiment,asset,horizon,window_start)
        );
        CREATE TABLE IF NOT EXISTS forecast_publications (id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL);
        """)
        for table in ("learning_experiments", "learning_reviews"):
            for action in ("UPDATE", "DELETE"):
                db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action} BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'Learning evidence is immutable'); END"
                )


def training_rows(db, asset, horizon, cutoff):
    candidates = db.execute(
        "SELECT f.*,e.actual,e.actual_hash,e.evaluated_at FROM forecasts f JOIN evaluations e ON e.forecast_id=f.id "
        "WHERE f.experiment=? AND f.scope='live' AND f.model='timesfm' AND f.asset=? AND f.horizon=? "
        "AND f.origin>=? AND f.target<? AND f.issued_at<? AND e.evaluated_at<=? ORDER BY f.origin",
        (config.EXPERIMENT, asset, horizon, cutoff - POLICY["window_days"] * 86400, cutoff, cutoff, cutoff),
    ).fetchall()
    eligible = []
    for r in candidates:
        review = outcomes.latest_review(db, r["id"], cutoff)
        if (
            review
            and review["status"] == "qualified"
            and review["payload"]["actual_hash"] == r["actual_hash"]
        ):
            eligible.append({**dict(r), "review_id": review["id"]})
    return eligible


def readiness(rows):
    span = (rows[-1]["origin"] - rows[0]["origin"]) / 86400 if rows else 0
    split = int(len(rows) * POLICY["train_fraction"])
    calibration = rows[split:]
    train = [r for r in rows[:split] if calibration and r["target"] < calibration[0]["origin"]]
    ready = (
        len(rows) >= POLICY["min_samples"]
        and span >= POLICY["min_days"]
        and len(train) >= POLICY["min_train"]
        and len(calibration) >= POLICY["min_calibration"]
    )
    return {
        "samples": len(rows),
        "span_days": span,
        "training": len(train),
        "calibration": len(calibration),
        "ready": ready,
    }


def fit(rows):
    if not readiness(rows)["ready"]:
        return None
    split = int(len(rows) * POLICY["train_fraction"])
    calibration = rows[split:]
    train = [r for r in rows[:split] if r["target"] < calibration[0]["origin"]]
    residuals = [math.log(r["actual"] / r["prediction"]) for r in train]
    bias = float(
        np.clip(
            sum(residuals) / (len(train) + POLICY["shrinkage"]),
            -POLICY["max_log_adjustment"],
            POLICY["max_log_adjustment"],
        )
    )
    errors = [math.log(r["actual"] / r["prediction"]) - bias for r in calibration]
    return {
        "experiment": EXPERIMENT,
        "method": "shrunk-log-bias-purged75-25-v1",
        "bias": bias,
        "lower_residual": min(0.0, float(np.quantile(errors, 0.1))),
        "upper_residual": max(0.0, float(np.quantile(errors, 0.9))),
        "training_ids": [r["id"] for r in train],
        "calibration_ids": [r["id"] for r in calibration],
        "review_ids": [r["review_id"] for r in train + calibration],
        "policy": POLICY,
    }


def generate():
    now = int(time.time())
    origin = now // 3600 * 3600
    count = 0
    with connect() as db:
        parents = db.execute(
            "SELECT * FROM forecasts WHERE experiment=? AND scope='live' AND model='timesfm' AND origin=?",
            (config.EXPERIMENT, origin),
        ).fetchall()
    for parent in parents:
        with connect() as db:
            if db.execute(
                "SELECT 1 FROM forecasts WHERE experiment=? AND asset=? AND horizon=? AND origin=?",
                (EXPERIMENT, parent["asset"], parent["horizon"], origin),
            ).fetchone():
                continue
            if not outcomes.input_verified(db, parent):
                continue
            rows = training_rows(db, parent["asset"], parent["horizon"], origin)
        started = time.monotonic()
        artifact = fit(rows)
        if artifact is None:
            continue
        artifact_id = digest(artifact)
        with connect() as db:
            db.execute("INSERT OR IGNORE INTO artifacts VALUES(?,?,?)", (artifact_id, now, packed(artifact)))
        path = [
            {"t": p["t"], "p": p["p"] * math.exp(artifact["bias"] * (i + 1) / parent["horizon"])}
            for i, p in enumerate(json.loads(parent["path"]))
        ]
        path[-1].update(
            lo=path[-1]["p"] * math.exp(artifact["lower_residual"]),
            hi=path[-1]["p"] * math.exp(artifact["upper_residual"]),
        )
        provenance = {
            **json.loads(parent["provenance"]),
            "experiment": EXPERIMENT,
            "parent_forecast_id": parent["id"],
            "artifact_id": artifact_id,
            "interval": "endpoint residual q10-q90 expanded to include point; not guaranteed",
        }
        store_forecast(
            parent["asset"],
            "calibrated",
            origin,
            parent["horizon"],
            parent["base"],
            path,
            json.loads(parent["features"]),
            provenance,
            (time.monotonic() - started) * 1000,
            experiment=EXPERIMENT,
        )
        count += 1
    return {"forecasts_added": count}


def interval_score(row):
    lo, hi, actual = [math.log(row[k]) for k in ("lower", "upper", "actual")]
    return hi - lo + 10 * max(0, lo - actual) + 10 * max(0, actual - hi)


def assess():
    """One immutable verdict per completed 28-day origin window, never hourly winner selection."""
    now = int(time.time())
    with connect() as db:
        for asset in config.ASSETS:
            for horizon in config.HORIZONS:
                first = db.execute(
                    "SELECT MIN(origin) FROM forecasts WHERE experiment=? AND asset=? AND horizon=?",
                    (EXPERIMENT, asset, horizon),
                ).fetchone()[0]
                if first is None:
                    continue
                span = POLICY["review_days"] * 86400
                start = first
                while start + span + horizon * 3600 <= now:
                    if db.execute(
                        "SELECT 1 FROM learning_reviews WHERE experiment=? AND asset=? AND horizon=? AND window_start=?",
                        (EXPERIMENT, asset, horizon, start),
                    ).fetchone():
                        start += span
                        continue
                    rows = [
                        dict(r)
                        for r in db.execute(
                            "SELECT f.*,e.actual,e.actual_hash,e.absolute_log_error,e.covered FROM forecasts f "
                            "JOIN evaluations e ON e.forecast_id=f.id WHERE f.scope='live' AND f.asset=? AND f.horizon=? "
                            "AND f.origin>=? AND f.origin<? AND f.experiment IN (?,?) AND e.evaluated_at<=?",
                            (asset, horizon, start, start + span, config.EXPERIMENT, EXPERIMENT, now),
                        )
                    ]
                    groups = {
                        m: {r["origin"]: r for r in rows if r["model"] == m}
                        for m in ("calibrated", "timesfm", "persistence", "momentum")
                    }
                    common = sorted(set.intersection(*(set(g) for g in groups.values())))
                    # Reviews used for the verdict are pinned by ID in the record.
                    kept, review_ids = [], []
                    for o in common:
                        review = outcomes.latest_review(db, groups["timesfm"][o]["id"], now)
                        if (
                            review
                            and review["status"] == "qualified"
                            and len({groups[m][o]["actual_hash"] for m in groups}) == 1
                        ):
                            kept.append(o)
                            review_ids.append(review["id"])
                    pairs = []
                    comparisons = []
                    for model in ("timesfm", "persistence", "momentum"):
                        days = {}
                        for o in kept:
                            days.setdefault((o - start) // 86400, []).append(
                                [
                                    groups["calibrated"][o]["absolute_log_error"],
                                    groups[model][o]["absolute_log_error"],
                                ]
                            )
                        pairs = [np.mean(days[d], axis=0).tolist() for d in sorted(days)]
                        means = np.mean(pairs, axis=0) if pairs else [0, 0]
                        ci = block_interval(pairs) if len(days) == POLICY["review_days"] else None
                        comparisons.append(
                            {
                                "model": model,
                                "gain": float(1 - means[0] / means[1]) if means[1] else None,
                                "ci95": ci,
                            }
                        )
                    coverage = (
                        float(np.mean([groups["calibrated"][o]["covered"] for o in kept])) if kept else None
                    )
                    interval_gain = (
                        float(
                            np.mean(
                                [
                                    interval_score(groups["timesfm"][o])
                                    - interval_score(groups["calibrated"][o])
                                    for o in kept
                                ]
                            )
                        )
                        if kept
                        else None
                    )
                    availability = len(kept) / (span // 3600)
                    supported = (
                        availability >= POLICY["min_availability"]
                        and coverage is not None
                        and coverage >= POLICY["min_coverage"]
                        and interval_gain is not None
                        and interval_gain >= 0
                        and all(
                            c["gain"] is not None
                            and c["gain"] >= POLICY["required_gain"]
                            and c["ci95"]
                            and c["ci95"][0] > 0
                            for c in comparisons
                        )
                    )
                    payload = {
                        "status": "supported_for_review" if supported else "inconclusive",
                        "start": start,
                        "end": start + span,
                        "n": len(kept),
                        "availability": availability,
                        "coverage": coverage,
                        "interval_score_gain": interval_gain,
                        "comparisons": comparisons,
                        "review_ids": review_ids,
                        "forecast_ids": [groups["calibrated"][o]["id"] for o in kept],
                        "auto_promoted": False,
                    }
                    db.execute(
                        "INSERT INTO learning_reviews VALUES(?,?,?,?,?,?,?)",
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


def cycle():
    if os.getenv("ORACLE_LEARNING_ENABLED") != "1":
        return {"state": "disabled"}
    init_schema()
    with connect() as db:
        db.execute(
            "INSERT OR IGNORE INTO learning_experiments VALUES(?,?,?)",
            (EXPERIMENT, int(time.time()), packed(POLICY)),
        )
    collected = outcomes.collect()
    reviewed = outcomes.review()
    generated = generate()
    assess()
    return {"state": "observing", "experiment": EXPERIMENT, **collected, **reviewed, **generated}
