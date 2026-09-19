"""Allowlisted public forecast journal. No private dashboard or headline payloads."""

import json
import os
import time

import httpx

from . import config, fusion, learning, outcomes, volband
from .db import connect, digest, packed

MODELS = ("timesfm", "calibrated", "fusion_market", "fusion_news", "volband", "timesfm_path")
PAIRED_MODEL = {"volband": "timesfm_path", "timesfm_path": "volband"}


def record(db, r, now):
    p = json.loads(r["provenance"])
    claim = {
        k: r[k]
        for k in (
            "experiment",
            "model",
            "asset",
            "origin",
            "issued_at",
            "target",
            "horizon",
            "base",
            "prediction",
            "lower",
            "upper",
        )
    }
    claim.update(
        revision=p["model_revision"],
        input_hash=p.get("input_artifact_id") or p["input_hash"],
        artifact_id=p.get("artifact_id"),
        parent_id=p.get("parent_forecast_id"),
        path=[{"t": x["t"], "p": x["p"]} for x in json.loads(r["path"])],
    )
    result = None
    if r["actual"] is not None:
        result = {k: r[k] for k in ("actual", "evaluated_at", "actual_hash", "absolute_log_error", "pinball")}
        result.update(
            direction_correct=bool(r["direction_correct"]),
            covered=bool(r["covered"]) if r["covered"] is not None else None,
            interval_score=learning.interval_score(r) if r["lower"] is not None else None,
        )
    review = outcomes.latest_review(db, r["id"], now)
    quality = None
    if review:
        e = review["payload"]
        quality = {
            "id": review["id"],
            "at": review["reviewed_at"],
            "version": review["version"],
            "status": review["status"],
            "actual_observed_at": e["actual_observed_at"],
            "divergence": e["divergence"],
            "fx": e["fx"],
            "input_verified": e["input_verified"],
            "references": [
                {k: v[k] for k in ("source", "asset", "ts", "close", "observed_at", "payload_hash")}
                for v in e["references"]
                if v
            ],
        }
    path = [
        {"t": x["ts"], "p": x["close"]}
        for x in db.execute(
            "SELECT ts,close FROM candles WHERE asset=? AND ts>? AND ts<=? ORDER BY ts",
            (r["asset"], r["origin"], min(now, r["target"])),
        )
    ]
    # The target marker always refers to the first recorded evaluation, even after a source revision.
    if result:
        path = [x for x in path if x["t"] != r["target"]] + [{"t": r["target"], "p": r["actual"]}]
    baselines = [
        {
            "model": x["model"],
            "prediction": x["prediction"],
            "error": x["absolute_log_error"] if x["actual_hash"] == r["actual_hash"] else None,
        }
        for x in db.execute(
            "SELECT f.model,f.prediction,e.absolute_log_error,e.actual_hash FROM forecasts f LEFT JOIN evaluations e "
            "ON e.forecast_id=f.id WHERE f.experiment=? AND f.scope='live' AND f.asset=? "
            "AND f.horizon=? AND f.origin=? AND f.model IN ('persistence','momentum','timesfm') ORDER BY f.model",
            (config.EXPERIMENT, r["asset"], r["horizon"], r["origin"]),
        )
    ]
    if r["model"] in PAIRED_MODEL:
        paired = db.execute(
            "SELECT f.model,f.prediction,e.absolute_log_error,e.actual_hash FROM forecasts f LEFT JOIN evaluations e "
            "ON e.forecast_id=f.id WHERE f.experiment=? AND f.scope='live' AND f.asset=? "
            "AND f.horizon=? AND f.origin=? AND f.model=?",
            (volband.EXPERIMENT, r["asset"], r["horizon"], r["origin"], PAIRED_MODEL[r["model"]]),
        ).fetchone()
        if paired:
            baselines.append(
                {
                    "model": paired["model"],
                    "prediction": paired["prediction"],
                    "error": paired["absolute_log_error"]
                    if paired["actual_hash"] == r["actual_hash"]
                    else None,
                }
            )
    return {
        "id": r["id"],
        "claim": claim,
        "outcome": result,
        "quality": quality,
        "actual_path": path,
        "baselines": baselines,
    }


def snapshot():
    learning.init_schema()
    now = int(time.time())
    with connect() as db:
        db.execute("BEGIN")
        rows = [
            dict(r)
            for r in db.execute(
                "SELECT f.*,e.actual,e.evaluated_at,e.actual_hash,e.absolute_log_error,e.direction_correct,e.covered,e.pinball "
                "FROM forecasts f LEFT JOIN evaluations e ON e.forecast_id=f.id WHERE f.scope='live' "
                "AND f.experiment IN (?,?,?) ORDER BY f.origin,f.model",
                (config.EXPERIMENT, learning.EXPERIMENT, volband.EXPERIMENT),
            )
        ]
        published = {r[0] for r in db.execute("SELECT id FROM forecast_publications")}
        records = [
            record(db, r, now)
            for r in rows
            if r["model"] in MODELS and (r["target"] >= now - 7 * 86400 or r["id"] not in published)
        ]
        groups = []
        horizons = sorted(set(config.HORIZONS) | set(volband.POLICY["horizons"]))
        for asset in config.ASSETS:
            for horizon in horizons:
                for model in MODELS:
                    group = [
                        r
                        for r in rows
                        if r["asset"] == asset and r["horizon"] == horizon and r["model"] == model
                    ]
                    if not group:
                        continue
                    # The volband pair references each other; every other model references persistence.
                    reference_name = PAIRED_MODEL.get(model, "persistence")
                    references = {
                        r["origin"]: r
                        for r in rows
                        if r["asset"] == asset
                        and r["horizon"] == horizon
                        and r["model"] == reference_name
                        and r["actual"] is not None
                    }
                    paired = [
                        r
                        for r in group
                        if r["actual"] is not None
                        and r["origin"] in references
                        and r["actual_hash"] == references[r["origin"]]["actual_hash"]
                    ]
                    covered = [r["covered"] for r in paired if r["covered"] is not None]
                    groups.append(
                        {
                            "asset": asset,
                            "horizon": horizon,
                            "model": model,
                            "issued": len(group),
                            "scored": sum(r["actual"] is not None for r in group),
                            "paired": len(paired),
                            "mae": sum(r["absolute_log_error"] for r in paired) / len(paired)
                            if paired
                            else None,
                            "baseline_mae": sum(references[r["origin"]]["absolute_log_error"] for r in paired)
                            / len(paired)
                            if paired
                            else None,
                            # Band-only models make no directional claim; never fabricate a 0% score for it.
                            "direction": sum(r["direction_correct"] for r in paired) / len(paired)
                            if paired and model not in PAIRED_MODEL
                            else None,
                            "coverage": sum(covered) / len(covered) if covered else None,
                            "calendar_days": len({r["origin"] // 86400 for r in paired}),
                        }
                    )
        stages, news = [], []
        for asset in config.ASSETS:
            for horizon in config.HORIZONS:
                train = learning.training_rows(db, asset, horizon, now)
                issued = [
                    r
                    for r in rows
                    if r["model"] == "calibrated" and r["asset"] == asset and r["horizon"] == horizon
                ]
                first = min((r["origin"] for r in issued), default=None)
                last_review = db.execute(
                    "SELECT reviewed_at,payload FROM learning_reviews WHERE experiment=? AND asset=? AND horizon=? "
                    "ORDER BY window_start DESC LIMIT 1",
                    (learning.EXPERIMENT, asset, horizon),
                ).fetchone()
                review = None
                if last_review:
                    r = json.loads(last_review["payload"])
                    review = {
                        "at": last_review["reviewed_at"],
                        **{
                            k: r[k]
                            for k in (
                                "status",
                                "start",
                                "end",
                                "n",
                                "availability",
                                "coverage",
                                "interval_score_gain",
                                "comparisons",
                                "auto_promoted",
                            )
                        },
                    }
                stages.append(
                    {
                        "asset": asset,
                        "horizon": horizon,
                        **learning.readiness(train),
                        "issued": len(issued),
                        "evaluated": sum(r["actual"] is not None for r in issued),
                        "first_origin": first,
                        "review_due": first + 28 * 86400 + horizon * 3600 if first else None,
                        "review": review,
                    }
                )
                # Existing FinBERT fusion remains separately identified and unchanged.
                ready = fusion.training_rows(asset, horizon, now // 3600 * 3600)
                news.append(
                    {
                        "asset": asset,
                        "horizon": horizon,
                        "samples": len(ready),
                        "span_days": (ready[-1]["origin"] - ready[0]["origin"]) / 86400 if ready else 0,
                        "news_ids": len({n for r in ready for n in r["features"].get("news_ids", [])}),
                        "issued": sum(
                            r["model"] == "fusion_news" and r["asset"] == asset and r["horizon"] == horizon
                            for r in rows
                        ),
                    }
                )
        experiment = db.execute(
            "SELECT started_at FROM learning_experiments WHERE id=?", (learning.EXPERIMENT,)
        ).fetchone()
    result = {
        "schema": 1,
        "generated_at": now,
        "experiment": learning.EXPERIMENT,
        "started_at": experiment[0] if experiment else None,
        "policy": learning.POLICY,
        "groups": groups,
        "learning": stages,
        "news": news,
        "records": records,
    }
    # Additive only: the shape above stays byte-for-byte identical while the flag is off.
    if os.getenv("ORACLE_VOLBAND_ENABLED") == "1":
        result["volband"] = volband.summary()
    return result


def publish():
    if os.getenv("ORACLE_LEARNING_ENABLED") != "1":
        return {"state": "disabled"}
    token = os.getenv("ORACLE_PUBLIC_TOKEN")
    if not token:
        return {"state": "not_configured"}
    data = snapshot()
    records = data.pop("records")
    with connect() as db:
        sent = dict(db.execute("SELECT id,payload_hash FROM forecast_publications"))
    changed = [(r, digest(r)) for r in records if digest(r) != sent.get(r["id"])]
    batches = [changed[i : i + 50] for i in range(0, len(changed), 50)] or [[]]
    for batch in batches:
        body = {**data, "records": [r for r, _ in batch]}
        try:
            response = httpx.post(
                "https://crypto-oracle-public.developer-331.workers.dev/api/publish-forecasts",
                content=packed(body),
                timeout=25,
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            )
            if response.status_code != 200:
                raise RuntimeError(f"Forecast export rejected (HTTP {response.status_code})")
        except httpx.HTTPError:
            raise RuntimeError("Forecast publication unavailable") from None
        with connect() as db:
            db.executemany(
                "INSERT INTO forecast_publications VALUES(?,?) ON CONFLICT(id) "
                "DO UPDATE SET payload_hash=excluded.payload_hash",
                [(r["id"], h) for r, h in batch],
            )
    return {"state": "published", "forecasts": len(records), "updated": len(changed)}
