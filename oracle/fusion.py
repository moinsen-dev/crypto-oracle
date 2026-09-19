"""Prospective shadow models: ridge residual correction with chronological calibration."""

import json
import math
import time

import numpy as np

from . import config
from .db import connect, digest, packed

MIN_SAMPLES = 120
MIN_DAYS = 21
MARKET_KEYS = ("model_return", "return_24h", "volatility_24h")
NEWS_KEYS = ("news_count", "sentiment", "negative_count")


def training_rows(asset, horizon, origin):
    with connect() as db:
        candidates = db.execute(
            "SELECT f.*,e.actual FROM forecasts f JOIN evaluations e ON e.forecast_id=f.id "
            "WHERE f.asset=? AND f.model='timesfm' AND f.scope='live' AND f.experiment=? "
            "AND f.horizon=? AND f.target<? AND f.issued_at<? AND e.evaluated_at<=? "
            "ORDER BY f.origin",
            (asset, config.EXPERIMENT, horizon, origin, origin, origin),
        ).fetchall()
    rows = []
    for row in candidates:
        row = dict(row)
        row["features"] = json.loads(row["features"])
        if row["features"].get("news_available"):
            rows.append(row)
    return rows


def fit(rows, keys):
    split = int(len(rows) * 0.75)
    calibration = rows[split:]
    # Purge training targets which overlap the first calibration forecast.
    train = [r for r in rows[:split] if r["target"] < calibration[0]["origin"]]
    if len(train) < 60 or len(calibration) < 30:
        return None
    x = np.array([[r["features"][k] for k in keys] for r in train])
    y = np.array([math.log(r["actual"] / r["prediction"]) for r in train])
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale[scale < 1e-9] = 1
    design = np.column_stack([np.ones(len(x)), (x - mean) / scale])
    penalty = np.eye(design.shape[1]) * 10
    penalty[0, 0] = 0
    beta = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    errors = []
    for r in calibration:
        vec = np.r_[1, (np.array([r["features"][k] for k in keys]) - mean) / scale]
        errors.append(math.log(r["actual"] / r["prediction"]) - float(vec @ beta))
    return {
        "keys": keys,
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "beta": beta.tolist(),
        "calibration_q10": float(np.quantile(errors, 0.1)),
        "calibration_q90": float(np.quantile(errors, 0.9)),
        "training_ids": [r["id"] for r in train],
        "calibration_ids": [r["id"] for r in calibration],
        "method": "ridge10-expanding-purged75-25-v1",
    }


def generate_fusion(asset, origin, horizon, base, path, features, provenance):
    from .forecast import store_forecast

    if not features["news_available"]:
        return
    rows = training_rows(asset, horizon, origin)
    if len(rows) < MIN_SAMPLES or rows[-1]["origin"] - rows[0]["origin"] < MIN_DAYS * 86400:
        return
    event_ids = {n for r in rows for n in r["features"].get("news_ids", [])}
    if len(event_ids) < 10:
        return
    for name, keys in (("fusion_market", MARKET_KEYS), ("fusion_news", MARKET_KEYS + NEWS_KEYS)):
        started = time.monotonic()
        artifact = fit(rows, keys)
        if artifact is None:
            continue
        artifact_id = digest(artifact)
        with connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO artifacts VALUES(?,?,?)",
                (artifact_id, int(time.time()), packed(artifact)),
            )
        vec = np.r_[1, (np.array([features[k] for k in keys]) - artifact["mean"]) / artifact["scale"]]
        adjustment = float(vec @ artifact["beta"])
        adjusted = [
            {"t": p["t"], "p": p["p"] * math.exp(adjustment * (i + 1) / horizon)} for i, p in enumerate(path)
        ]
        adjusted[-1]["lo"] = adjusted[-1]["p"] * math.exp(artifact["calibration_q10"])
        adjusted[-1]["hi"] = adjusted[-1]["p"] * math.exp(artifact["calibration_q90"])
        store_forecast(
            asset,
            name,
            origin,
            horizon,
            base,
            adjusted,
            features,
            {
                **provenance,
                "artifact_id": artifact_id,
                "interval": "endpoint only; past calibration residual q10-q90; shadow experiment",
            },
            (time.monotonic() - started) * 1000,
        )
