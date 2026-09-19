"""Read-only experimental report with paired, time-block uncertainty."""

import time

import numpy as np

from . import config
from .db import connect
from .forecast import metrics


def block_interval(pairs, block_days=7, repeats=1000):
    """Pairs contain calendar-day means: model error, reference error."""
    values = np.asarray(pairs, dtype=float)
    if len(values) < 28:
        return None
    random = np.random.default_rng(42)
    estimates = []
    for _ in range(repeats):
        starts = random.integers(0, len(values), size=(len(values) + block_days - 1) // block_days)
        indices = ((starts[:, None] + np.arange(block_days)) % len(values)).ravel()[: len(values)]
        means = values[indices].mean(axis=0)
        if means[1] > 0:
            estimates.append(1 - means[0] / means[1])
    if not estimates:
        return None
    return np.quantile(estimates, [0.025, 0.975]).tolist()


def comparison_intervals(scope, horizon):
    with connect() as db:
        rows = db.execute(
            "SELECT f.asset,f.model,f.origin,e.absolute_log_error AS error FROM forecasts f "
            "JOIN evaluations e ON e.forecast_id=f.id WHERE f.experiment=? "
            "AND f.scope=? AND f.horizon=? ORDER BY f.origin",
            (config.EXPERIMENT, scope, horizon),
        ).fetchall()
    groups = {}
    for r in rows:
        groups.setdefault((r["asset"], r["model"]), {})[r["origin"]] = r["error"]
    results = []
    for (asset, model), entries in groups.items():
        if model == "persistence":
            continue
        reference_name = "fusion_market" if model == "fusion_news" else "persistence"
        reference = groups.get((asset, reference_name), {})
        days = {}
        for origin in sorted(entries):
            if origin in reference:
                days.setdefault(origin // 86400, []).append([entries[origin], reference[origin]])
        # Require a contiguous daily series for circular moving-block bootstrap.
        ordered_days = sorted(days)
        continuous = bool(days) and ordered_days[-1] - ordered_days[0] + 1 == len(days)
        pairs = [np.mean(days[day], axis=0).tolist() for day in ordered_days]
        ci = block_interval(pairs) if continuous else None
        results.append(
            {
                "asset": asset,
                "model": model,
                "reference": reference_name,
                "calendar_days": len(days),
                "relative_error_reduction_ci95": ci,
                "method": "paired daily means; circular 7-day blocks; 1000 draws; seed 42",
                "status": "insufficient_contiguous_history"
                if ci is None
                else "lower_error"
                if ci[0] > 0
                else "higher_error"
                if ci[1] < 0
                else "inconclusive",
            }
        )
    return results


def build_report(scope="backtest"):
    return {
        "created_at": int(time.time()),
        "experiment": config.EXPERIMENT,
        "scope": scope,
        "interpretation": "Exploratory; neither a trading-profit test nor proof of future performance. "
        "Bootstrap intervals assume time blocks represent the observed regime.",
        "metrics": {h: metrics(scope, h) for h in config.HORIZONS},
        "comparisons": {h: comparison_intervals(scope, h) for h in config.HORIZONS},
    }
