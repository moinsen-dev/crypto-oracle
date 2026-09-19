import math
import time
from itertools import pairwise

import numpy as np

from . import config
from .db import connect, digest, packed
from .models import predict


def history(asset, origin=None, limit=config.CONTEXT):
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM candles WHERE asset=? AND ts<=? ORDER BY ts DESC LIMIT ?",
            (asset, origin or int(time.time()), limit),
        ).fetchall()
    rows = [dict(r) for r in reversed(rows)]
    if len(rows) < limit or any(b["ts"] - a["ts"] != 3600 for a, b in pairwise(rows)):
        raise ValueError(f"{asset}: need {limit} consecutive closed hourly candles")
    return rows


def news_features(asset, origin):
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM news WHERE first_seen<=? AND first_seen>? AND classified_at<=? "
            "AND (published_at IS NULL OR published_at<=?) ORDER BY first_seen",
            (origin, origin - 86400, origin, origin),
        ).fetchall()
        polls = db.execute(
            "SELECT source,COUNT(DISTINCT CAST(polled_at/3600 AS INTEGER)) AS hours "
            "FROM source_polls WHERE ok=1 AND polled_at>? AND polled_at<=? GROUP BY source",
            (origin - 86400, origin),
        ).fetchall()
    # Same URL or normalized headline is counted once. Near-syndicated copies are clustered at feature time.
    selected, urls, clusters, tokens_seen = [], set(), set(), []
    for r in rows:
        if asset not in r["assets"].split(",") or r["url"] in urls or r["cluster"] in clusters:
            continue
        # Do not let a newly encountered old article masquerade as a new event.
        if r["published_at"] and r["published_at"] < origin - 86400:
            continue
        tokens = set(r["title"].lower().split())
        duplicate = any(len(tokens & prev) / max(1, len(tokens | prev)) >= 0.8 for prev in tokens_seen)
        urls.add(r["url"])
        clusters.add(r["cluster"])
        tokens_seen.append(tokens)
        if not duplicate:
            selected.append(r)
    scores = [r["sentiment"] for r in selected]
    # Complete enough for training only after >=18 of 24 hours were successfully observed on every feed.
    coverage = {r["source"]: r["hours"] for r in polls}
    covered = all(coverage.get(source, 0) >= 18 for source in config.FEEDS)
    with connect() as db:
        latest = [
            db.execute(
                "SELECT ok,polled_at FROM source_polls WHERE source=? AND polled_at<=? "
                "ORDER BY polled_at DESC LIMIT 1",
                (s, origin),
            ).fetchone()
            for s in config.FEEDS
        ]
        recent_success = all(r and r["ok"] and origin - r["polled_at"] <= 3600 for r in latest)
    return {
        "news_count": len(scores),
        "sentiment": float(np.mean(scores)) if scores else 0.0,
        "negative_count": sum(s < -0.3 for s in scores),
        "news_available": covered and recent_success,
        "news_ids": [r["id"] for r in selected],
        "coverage_hours": coverage,
    }


def store_forecast(
    asset, model, origin, horizon, base, path, features, provenance, latency, scope="live", issued_at=None,
    experiment=None,
):
    prediction = path[-1]["p"]
    experiment = experiment or config.EXPERIMENT
    ident = digest([experiment, scope, asset, model, origin, horizon])
    if not all(math.isfinite(v) and v > 0 for p in path for k, v in p.items() if k != "t" and v is not None):
        raise ValueError("Forecast contains invalid prices")
    with connect() as db:
        db.execute(
            "INSERT OR IGNORE INTO forecasts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ident,
                experiment,
                scope,
                asset,
                model,
                origin,
                issued_at or int(time.time()),
                horizon,
                origin + horizon * 3600,
                base,
                prediction,
                path[-1].get("lo"),
                path[-1].get("hi"),
                packed(path),
                packed(features),
                packed(provenance),
                latency,
            ),
        )
    return ident


def generate(asset, scope="live", origin=None):
    rows = history(asset, origin)
    origin = rows[-1]["ts"]
    now = int(time.time())
    if scope == "live" and now - origin > 7200:
        raise ValueError(f"{asset}: market data is stale; refusing a live forecast")
    with connect() as db:
        models_done = {
            (r[0], r[1])
            for r in db.execute(
                "SELECT model,horizon FROM forecasts WHERE experiment=? AND scope=? AND asset=? AND origin=?",
                (config.EXPERIMENT, scope, asset, origin),
            )
        }
    if all((m, h) in models_done for m in ("persistence", "momentum", "timesfm") for h in config.HORIZONS):
        return {"asset": asset, "origin": origin, "skipped": True}
    prices = np.array([r["close"] for r in rows])
    base = float(prices[-1])
    logs = np.log(prices)
    features = {
        "return_24h": float(logs[-1] - logs[-25]),
        "volatility_24h": float(np.std(np.diff(logs[-25:]))),
        **(
            news_features(asset, origin)
            if scope == "live"
            else {
                "news_available": False,
                "news_ids": [],
                "news_count": 0,
                "sentiment": 0,
                "negative_count": 0,
                "coverage_hours": {},
            }
        ),
    }
    inputs = {"kind": "input-candles-v1", "asset": asset, "candles": rows}
    input_id = digest(inputs)
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO artifacts VALUES(?,?,?)", (input_id, now, packed(inputs)))
    provenance = {
        "model_revision": config.MODEL_REVISION,
        "context": config.CONTEXT,
        "input_hash": input_id,
        "input_artifact_id": input_id,
        "input_cutoff": origin,
        "quote": "USDT",
        "venue": "Binance spot",
        "experiment": config.EXPERIMENT,
        "transform": "log-close; median-q50",
        "interval": "raw q10-q90, calibration not assumed",
    }
    # Baselines survive a TimesFM failure; failure is never disguised as a model forecast.
    for h in config.HORIZONS:
        for model in ("persistence", "momentum"):
            slope = 0.0 if model == "persistence" else features["return_24h"] / 24
            path = [{"t": origin + i * 3600, "p": base * math.exp(slope * i)} for i in range(1, h + 1)]
            store_forecast(asset, model, origin, h, base, path, features, provenance, 0, scope)
    outputs, latency = predict(prices, max(config.HORIZONS))
    for h in config.HORIZONS:
        path = [
            {"t": origin + (i + 1) * 3600, "lo": float(v[0]), "p": float(v[1]), "hi": float(v[2])}
            for i, v in enumerate(outputs[:h])
        ]
        tf_features = {**features, "model_return": math.log(path[-1]["p"] / base)}
        store_forecast(asset, "timesfm", origin, h, base, path, tf_features, provenance, latency, scope)
        if scope == "live":
            from .fusion import generate_fusion

            generate_fusion(asset, origin, h, base, path, tf_features, provenance)
    return {"asset": asset, "origin": origin, "latency_ms": round(latency, 1)}


def evaluate():
    now = int(time.time())
    with connect() as db:
        rows = db.execute(
            "SELECT f.*,c.close AS actual,c.payload_hash AS actual_hash FROM forecasts f "
            "JOIN candles c ON c.asset=f.asset AND c.ts=f.target "
            "LEFT JOIN evaluations e ON e.forecast_id=f.id "
            "WHERE e.forecast_id IS NULL AND f.target<=?",
            (now,),
        ).fetchall()
        for r in rows:
            predicted_return, actual_return = (
                math.log(r["prediction"] / r["base"]),
                math.log(r["actual"] / r["base"]),
            )
            covered, pinball = None, None
            if r["lower"] is not None:
                covered = int(r["lower"] <= r["actual"] <= r["upper"])
                losses = []
                for q, price in ((0.1, r["lower"]), (0.9, r["upper"])):
                    err = math.log(r["actual"] / price)
                    losses.append(max(q * err, (q - 1) * err))
                pinball = sum(losses) / 2
            db.execute(
                "INSERT OR IGNORE INTO evaluations VALUES(?,?,?,?,?,?,?,?)",
                (
                    r["id"],
                    r["actual"],
                    now,
                    abs(predicted_return - actual_return),
                    int(np.sign(predicted_return) == np.sign(actual_return)),
                    covered,
                    pinball,
                    r["actual_hash"],
                ),
            )
    return {"evaluated": len(rows)}


def metrics(scope="live", horizon=24):
    with connect() as db:
        rows = db.execute(
            "SELECT f.asset,f.model,f.origin,f.base,f.lower,f.upper,e.* FROM forecasts f "
            "JOIN evaluations e ON e.forecast_id=f.id WHERE f.scope=? AND f.horizon=? "
            "AND f.experiment=?",
            (scope, horizon, config.EXPERIMENT),
        ).fetchall()
    grouped = {}
    for r in rows:
        grouped.setdefault((r["asset"], r["model"]), {})[r["origin"]] = dict(r)
    result = []
    for (asset, model), entries in sorted(grouped.items()):
        baseline = grouped.get((asset, "persistence"), {})
        paired = [origin for origin in entries if origin in baseline]
        if not paired:
            continue
        values = [entries[o] for o in paired]
        mae = float(np.mean([r["absolute_log_error"] for r in values]))
        baseline_mae = float(np.mean([baseline[o]["absolute_log_error"] for o in paired]))
        coverage = [r["covered"] for r in values if r["covered"] is not None]
        quantile_loss = [r["pinball"] for r in values if r["pinball"] is not None]
        width = [math.log(r["upper"] / r["lower"]) for r in values if r["lower"] is not None]
        market = grouped.get((asset, "fusion_market"), {})
        news_pairs = [o for o in entries if o in market] if model == "fusion_news" else []
        market_mae = (
            float(np.mean([market[o]["absolute_log_error"] for o in news_pairs])) if news_pairs else 0
        )
        news_mae = float(np.mean([entries[o]["absolute_log_error"] for o in news_pairs])) if news_pairs else 0
        result.append(
            {
                "asset": asset,
                "model": model,
                "n": len(values),
                "mae": mae,
                "baseline_mae": baseline_mae,
                "improvement": 1 - mae / baseline_mae if baseline_mae else None,
                "direction": float(np.mean([r["direction_correct"] for r in values]))
                if model != "persistence"
                else None,
                "coverage": float(np.mean(coverage)) if coverage else None,
                "pinball": float(np.mean(quantile_loss)) if quantile_loss else None,
                "interval_width": float(np.mean(width)) if width else None,
                "first_origin": min(paired),
                "last_origin": max(paired),
                "news_lift_vs_market": 1 - news_mae / market_mae if market_mae else None,
                "calendar_days": len({o // 86400 for o in paired}),
            }
        )
    return result
