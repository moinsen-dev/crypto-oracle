import os
import time
from functools import lru_cache

import numpy as np

from . import config
from .db import connect

FINBERT_REVISION = "4556d13015211d73dccd3fdd39d39232506f3e43"
CLASSIFIER = "ProsusAI/finbert@" + FINBERT_REVISION


def configure_torch():
    import torch

    torch.set_num_threads(int(os.getenv("ORACLE_TORCH_THREADS", "4")))


@lru_cache(maxsize=1)
def forecaster():
    import timesfm

    configure_torch()
    model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
        config.MODEL_ID,
        revision=config.MODEL_REVISION,
        torch_compile=False,
    )
    model.compile(
        timesfm.ForecastConfig(
            max_context=config.CONTEXT,
            max_horizon=128,
            per_core_batch_size=1,
            normalize_inputs=True,
            use_continuous_quantile_head=True,
            force_flip_invariance=True,
            infer_is_positive=False,
            fix_quantile_crossing=True,
        )
    )
    return model


def predict(prices, horizon=72):
    values = np.asarray(prices, dtype=np.float64)
    if len(values) < config.CONTEXT or not np.all(np.isfinite(values)) or np.any(values <= 0):
        raise ValueError("Invalid or insufficient model input")
    model = forecaster()
    started = time.monotonic()
    _, quantiles = model.forecast(horizon=horizon, inputs=[np.log(values[-config.CONTEXT :])])
    # Channel 0 is the mean; 1..9 are q10..q90. Use q50 as the point forecast.
    log_outputs = quantiles[0, :horizon, [1, 5, 9]].T
    if log_outputs.shape != (horizon, 3) or not np.isfinite(log_outputs).all():
        raise ValueError("Invalid TimesFM output")
    with np.errstate(over="raise", invalid="raise"):
        outputs = np.exp(log_outputs)
    if np.any(outputs[:, 0] > outputs[:, 1]) or np.any(outputs[:, 1] > outputs[:, 2]):
        raise ValueError("Crossing forecast quantiles")
    return outputs, (time.monotonic() - started) * 1000


@lru_cache(maxsize=1)
def sentiment_pipeline():
    from transformers import pipeline

    configure_torch()
    return pipeline(
        "text-classification",
        model="ProsusAI/finbert",
        revision=FINBERT_REVISION,
        tokenizer="ProsusAI/finbert",
        device=-1,
    )


def classify_news():
    with connect() as db:
        rows = db.execute(
            "SELECT id,title FROM news WHERE sentiment IS NULL "
            "ORDER BY published_at DESC,first_seen DESC LIMIT 128"
        ).fetchall()
    if not rows:
        return {"classified": 0}
    pipe = sentiment_pipeline()
    outputs = pipe([r["title"] for r in rows], top_k=None, truncation=True, max_length=256, batch_size=8)
    now = int(time.time())
    with connect() as db:
        for row, scores in zip(rows, outputs, strict=True):
            scores = {x["label"].lower(): float(x["score"]) for x in scores}
            db.execute(
                "UPDATE news SET sentiment=?,confidence=?,classifier=?,classified_at=? "
                "WHERE id=? AND sentiment IS NULL",
                (scores["positive"] - scores["negative"], max(scores.values()), CLASSIFIER, now, row["id"]),
            )
    return {"classified": len(rows), "classifier": CLASSIFIER}
