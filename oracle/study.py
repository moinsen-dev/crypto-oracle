"""Exploratory historical studies behind the public field notes. Evidence about the past, never a forward claim."""

import json
import math
import time

import httpx
import numpy as np

from . import config
from .db import connect
from .ingest import HEADERS, get

# Fixed from the trend-following literature before any result was seen; all are reported, none is selected.
LOOKBACKS = (7, 14, 28, 56)
UNIVERSES = {
    "project": ("BTC", "ETH", "SOL"),
    # Large caps already listed on Binance in October 2020, so later winners are not picked with hindsight.
    "october-2020-large-caps": ("BTC", "ETH", "XRP", "BCH", "BNB", "LINK", "DOT", "ADA", "LTC", "SOL"),
}
SCENARIOS = {
    "base": {"cost": 0.0015, "lag": 0},
    "one-day-delay": {"cost": 0.0015, "lag": 1},
    "double-costs": {"cost": 0.003, "lag": 0},
    "delay-and-double-costs": {"cost": 0.003, "lag": 1},
}
STEPS = (1, 2, 4, 8, 12, 24, 48, 72)
MAX_CRYPTO = 0.6  # the paper policy's allocation cap
START = max(LOOKBACKS) + 4  # first simulated day: every lookback exists, also after a one-day delay
STUDY_START = 1598918400  # 2020-09-01


def hourly_series():
    with connect() as db:
        rows = db.execute("SELECT asset,ts,close FROM candles ORDER BY ts").fetchall()
    series = {}
    for r in rows:
        series.setdefault(r["asset"], []).append((r["ts"], r["close"]))
    return {a: (np.array([t for t, _ in v]), np.log([c for _, c in v])) for a, v in series.items()}


def backtest_paths():
    with connect() as db:
        return [
            {**dict(r), "path": json.loads(r["path"])}
            for r in db.execute(
                "SELECT asset,origin,base,path FROM forecasts WHERE experiment=? AND scope='backtest' "
                "AND model='timesfm' AND horizon=? ORDER BY origin",
                (config.EXPERIMENT, max(config.HORIZONS)),
            )
        ]


def horizon_skill(steps=STEPS):
    """Score every stored step of the frozen TimesFM backtest paths. No model calls."""
    series, rows = hourly_series(), backtest_paths()
    closes = {a: dict(zip(ts.tolist(), lp.tolist(), strict=True)) for a, (ts, lp) in series.items()}
    result = []
    for h in steps:
        model, reference, direction, covered, width = [], [], [], [], []
        for r in rows:
            point = r["path"][h - 1]
            actual = closes[r["asset"]].get(point["t"])
            if actual is None:
                continue
            predicted, realized = math.log(point["p"] / r["base"]), actual - math.log(r["base"])
            model.append(abs(predicted - realized))
            reference.append(abs(realized))
            if predicted and realized:
                direction.append(np.sign(predicted) == np.sign(realized))
            covered.append(point["lo"] <= math.exp(actual) <= point["hi"])
            width.append(math.log(point["hi"] / point["lo"]))
        if model:
            result.append(
                {
                    "horizon": h,
                    "n": len(model),
                    "model_mae": float(np.mean(model)),
                    "persistence_mae": float(np.mean(reference)),
                    "skill": float(1 - np.mean(model) / np.mean(reference)),
                    "direction": float(np.mean(direction)) if direction else None,
                    "coverage": float(np.mean(covered)),
                    "width": float(np.mean(width)),
                }
            )
    return result


def trailing_volatility(log_prices, span):
    """Root mean squared hourly log return over the trailing span; entry i uses closes up to i only."""
    squares = np.cumsum(np.r_[0, np.diff(log_prices) ** 2])
    out = np.full(len(log_prices), np.nan)
    out[span:] = np.sqrt((squares[span:] - squares[:-span]) / span)
    return out


def interval_score(lo, hi, actual):
    return hi - lo + 10 * max(0, lo - actual) + 10 * max(0, actual - hi)


def band_study(steps=(1, 4, 12, 24, 72), train_fraction=0.6):
    """Raw TimesFM q10-q90 against a four-parameter volatility band centred on the last price.

    Chronological split; the band is fitted on hourly origins whose targets precede the first test origin.
    """
    series, rows = hourly_series(), backtest_paths()
    origins = sorted({r["origin"] for r in rows})
    if len(origins) < 50:
        return []
    cut = origins[int(len(origins) * train_fraction)]
    spans = (24, 168, 720)
    vols = {a: [trailing_volatility(lp, s) for s in spans] for a, (_, lp) in series.items()}
    index = {a: {int(t): i for i, t in enumerate(ts)} for a, (ts, _) in series.items()}
    result = []
    for h in steps:
        design, target, moves = [], [], []
        for a, (ts, lp) in series.items():
            for i in range(spans[-1], len(lp) - h, 6):
                if ts[i] + h * 3600 >= cut:
                    break
                design.append([1, *(math.log(v[i]) for v in vols[a])])
                moves.append(lp[i + h] - lp[i])
                target.append(math.log(abs(moves[-1]) + 1e-5))
        beta = np.linalg.lstsq(np.array(design), np.array(target), rcond=None)[0]
        scale = np.exp(np.array(design) @ beta)
        z_lo, z_hi = np.quantile(np.array(moves) / scale, [0.1, 0.9])
        scores = {"timesfm_raw": [], "volatility_band": []}
        errors = []
        for r in rows:
            i = index[r["asset"]].get(r["origin"])
            lp = series[r["asset"]][1]
            if r["origin"] < cut or i is None or i + h >= len(lp) or i < spans[-1]:
                continue
            actual, point = lp[i + h] - lp[i], r["path"][h - 1]
            errors.append((abs(math.log(point["p"] / r["base"]) - actual), abs(actual)))
            s = math.exp(float(np.array([1, *(math.log(v[i]) for v in vols[r["asset"]])]) @ beta))
            for name, lo, hi in (
                ("timesfm_raw", math.log(point["lo"] / r["base"]), math.log(point["hi"] / r["base"])),
                ("volatility_band", z_lo * s, z_hi * s),
            ):
                scores[name].append((lo <= actual <= hi, hi - lo, interval_score(lo, hi, actual)))
        if not scores["timesfm_raw"]:
            continue
        model_mae, persistence_mae = np.mean(errors, axis=0)
        entry = {
            "horizon": h,
            "n": len(errors),
            "first_test_origin": cut,
            "point_skill": float(1 - model_mae / persistence_mae),
        }
        for name, values in scores.items():
            coverage, width, score = np.mean(values, axis=0)
            entry[name] = {"coverage": float(coverage), "width": float(width), "interval_score": float(score)}
        result.append(entry)
    return result


def daily_closes(assets, refresh=False):
    """Completed Binance spot daily closes since September 2020, cached beside the research database."""
    cache = config.DATA / "study-daily.json"
    data = json.loads(cache.read_text()) if cache.exists() and not refresh else {}
    now = int(time.time())
    with httpx.Client(timeout=30, headers=HEADERS) as client:
        for asset in assets:
            if asset in data:
                continue
            rows, start = [], STUDY_START * 1000
            while True:
                page = get(
                    client,
                    "https://api.binance.com/api/v3/klines",
                    params={"symbol": asset + "USDT", "interval": "1d", "startTime": start, "limit": 1000},
                ).json()
                rows += page
                if len(page) < 1000:
                    break
                start = page[-1][0] + 86400000
                time.sleep(0.15)
            # Never treat the still-open day as closed.
            data[asset] = [[r[6] // 1000 + 1, float(r[4])] for r in rows if r[6] // 1000 < now]
    config.DATA.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data))
    return data


def trend_weights(log_prices, i, per_asset):
    """Share of lookbacks with a positive trailing return. Reads rows up to i only."""
    return per_asset * np.mean([log_prices[i] - log_prices[i - k] > 0 for k in LOOKBACKS], axis=0)


def simulate(log_prices, weights, cost, lag=0, band=0.05, start=START):
    """Long-only daily portfolio. Weights chosen from closes up to day i-lag earn the return from day i to i+1."""
    returns = np.exp(np.diff(log_prices, axis=0)) - 1
    equity, held, curve = 1.0, np.zeros(log_prices.shape[1]), []
    for i in range(start, len(returns)):
        wanted = weights(log_prices, i - lag)
        turnover = float(np.abs(wanted - held).sum())
        if turnover > band:
            equity *= 1 - turnover * cost
            held = wanted.copy()
        growth = float(held @ returns[i])
        equity *= 1 + growth
        held = held * (1 + returns[i]) / (1 + growth)
        curve.append(equity)
    return np.array(curve)


def curve_stats(curve):
    daily = np.diff(np.log(curve))
    return {
        "cagr": float(curve[-1] ** (365 / len(curve)) - 1),
        "sharpe": float(daily.mean() / daily.std() * math.sqrt(365)) if daily.std() else 0.0,
        "max_drawdown": float(np.max(1 - curve / np.maximum.accumulate(curve))),
    }


def sharpe_gap_interval(curve, reference, block=30, repeats=2000):
    """Paired circular block bootstrap of the Sharpe difference; 30-day blocks keep trends and crashes intact."""
    a, b = np.diff(np.log(curve)), np.diff(np.log(reference))
    random = np.random.default_rng(7)
    gaps = []
    for _ in range(repeats):
        starts = random.integers(0, len(a), size=len(a) // block + 1)
        rows = ((starts[:, None] + np.arange(block)) % len(a)).ravel()[: len(a)]
        x, y = a[rows], b[rows]
        gaps.append((x.mean() / x.std() - y.mean() / y.std()) * math.sqrt(365))
    return np.quantile(gaps, [0.025, 0.975]).tolist()


def trend_study(refresh=False):
    data = daily_closes(sorted({a for u in UNIVERSES.values() for a in u}), refresh)
    result = {"lookbacks_days": LOOKBACKS, "max_crypto": MAX_CRYPTO, "universes": {}}
    for label, assets in UNIVERSES.items():
        days = min(len(data[a]) for a in assets)
        times = [row[0] for row in data[assets[0]][-days:]]
        log_prices = np.log([[data[a][-days + i][1] for a in assets] for i in range(days)])
        base = np.full(len(assets), MAX_CRYPTO / len(assets))
        scenarios = {}
        for name, s in SCENARIOS.items():
            benchmark = simulate(log_prices, lambda *_, base=base: base, s["cost"])
            filtered = simulate(
                log_prices, lambda p, i, base=base: trend_weights(p, i, base), s["cost"], s["lag"]
            )
            scenarios[name] = {
                **s,
                "rebalanced": curve_stats(benchmark),
                "trend_filter": curve_stats(filtered),
                "sharpe_gap_ci95": sharpe_gap_interval(filtered, benchmark),
            }
            if name == "base":
                weekly = range(0, len(benchmark), 7)
                curves = [
                    {
                        "t": times[START + 1 + i],
                        "rebalanced": round(float(benchmark[i]), 4),
                        "trend_filter": round(float(filtered[i]), 4),
                    }
                    for i in weekly
                ]
        # What the state said about the following, non-overlapping week.
        after = {k: {"up": [], "down": []} for k in LOOKBACKS}
        for i in range(START, days - 7, 7):
            future = log_prices[i + 7] - log_prices[i]
            for k in LOOKBACKS:
                up = log_prices[i] - log_prices[i - k] > 0
                after[k]["up"] += future[up].tolist()
                after[k]["down"] += future[~up].tolist()
        result["universes"][label] = {
            "assets": assets,
            "first_day": times[START + 1],
            "last_day": times[-1],
            "days": len(benchmark),
            "scenarios": scenarios,
            "weekly_curves": curves,
            "next_week_mean_log_return": {
                k: {state: float(np.mean(v)) for state, v in states.items()} for k, states in after.items()
            },
        }
    return result


def build(refresh=False):
    return {
        "schema": 1,
        "created_at": int(time.time()),
        "kind": "exploratory historical study; rules fixed in advance, every variant reported; not a forward claim",
        "experiment": config.EXPERIMENT,
        "horizon_skill": horizon_skill(),
        "bands": band_study(),
        "trend": trend_study(refresh),
    }
