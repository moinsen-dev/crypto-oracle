"""Exploratory study of slow market-state signals: do they say anything about the following days?

Funding rates, option-implied volatility, stablecoin supply growth, the Fear & Greed index and taker order flow,
all from free public sources. A value counts only if it existed before the daily decision at 00:00 UTC, each
signal is ranked against its own trailing year, every combination is reported, and an overlay on the trend rule
is chosen on the years before SPLIT and run once on the years after it. Not a forward claim.
"""

import json
import math
import time
from bisect import bisect_left, bisect_right

import httpx
import numpy as np

from . import config
from .study import (
    HEADERS,
    LOOKBACKS,
    MAX_CRYPTO,
    curve_stats,
    get,
    sharpe_gap_interval,
    simulate,
    trend_weights,
)

ASSETS = ("BTC", "ETH", "SOL")
DAY = 86400
START = 1514764800  # 2018-01-01
SPLIT = 1672531200  # 2023-01-01: overlays are chosen before this day and judged after it
HORIZONS = (1, 3, 7, 14)
WINDOW, MIN_HISTORY = 365, 180
LOW, HIGH = 0.2, 0.8
MIN_DAYS = 40
COST = 0.0015
BLOCK = 30


def cached(name, fetch, refresh):
    path = config.DATA / "signals-study"
    path.mkdir(parents=True, exist_ok=True)
    file = path / f"{name}.json"
    if file.exists() and not refresh:
        return json.loads(file.read_text())
    data = fetch()
    file.write_text(json.dumps(data))
    return data


def paged(client, url, params, key, step):
    rows, start = [], START * 1000
    while True:
        page = get(client, url, params={**params, "startTime": start, "limit": 1000}).json()
        rows += page
        if len(page) < 1000:
            return rows
        start = key(page[-1]) + step
        time.sleep(0.2)


def daily(asset, refresh=False):
    """Completed daily candles: [close time, close, volume, taker buy volume]."""

    def fetch():
        now = int(time.time())
        with httpx.Client(timeout=30, headers=HEADERS) as client:
            rows = paged(
                client,
                "https://api.binance.com/api/v3/klines",
                {"symbol": asset + "USDT", "interval": "1d"},
                lambda r: r[0],
                DAY * 1000,
            )
        return [[r[6] // 1000 + 1, float(r[4]), float(r[5]), float(r[9])] for r in rows if r[6] // 1000 < now]

    return cached(f"daily-{asset}", fetch, refresh)


def funding(asset, refresh=False):
    def fetch():
        with httpx.Client(timeout=30, headers=HEADERS) as client:
            rows = paged(
                client,
                "https://fapi.binance.com/fapi/v1/fundingRate",
                {"symbol": asset + "USDT"},
                lambda r: r["fundingTime"],
                1,
            )
        return [[r["fundingTime"] // 1000, float(r["fundingRate"])] for r in rows]

    return cached(f"funding-{asset}", fetch, refresh)


def implied(currency, refresh=False):
    """Deribit's volatility index, daily candles: [day start, close]."""

    def fetch():
        rows, end = {}, int(time.time()) * 1000
        with httpx.Client(timeout=30, headers=HEADERS) as client:
            while end > START * 1000:
                result = get(
                    client,
                    "https://www.deribit.com/api/v2/public/get_volatility_index_data",
                    params={
                        "currency": currency,
                        "start_timestamp": START * 1000,
                        "end_timestamp": end,
                        "resolution": "1D",
                    },
                ).json()["result"]
                if not result["data"]:
                    break
                rows.update({r[0] // 1000: r[4] for r in result["data"]})
                if not result.get("continuation"):
                    break
                end = result["continuation"]
                time.sleep(0.3)
        return sorted([k, v] for k, v in rows.items())

    return cached(f"dvol-{currency}", fetch, refresh)


def stablecoins(refresh=False):
    def fetch():
        with httpx.Client(timeout=60, headers=HEADERS) as client:
            rows = get(client, "https://stablecoins.llama.fi/stablecoincharts/all").json()
        return [[int(r["date"]), float(r["totalCirculatingUSD"]["peggedUSD"])] for r in rows]

    return cached("stablecoins", fetch, refresh)


def fear_greed(refresh=False):
    def fetch():
        with httpx.Client(timeout=30, headers=HEADERS) as client:
            rows = get(
                client, "https://api.alternative.me/fng/", params={"limit": 0, "format": "json"}
            ).json()
        return sorted([int(r["timestamp"]), float(r["value"])] for r in rows["data"])

    return cached("fear-greed", fetch, refresh)


def before(series, t, age=0):
    """The latest value stamped at or before t - age, or None. Nothing stamped later can leak in."""
    i = bisect_right(series[0], t - age) - 1
    return series[1][i] if i >= 0 else None


def columns(rows):
    return [r[0] for r in rows], [r[1] for r in rows]


def signals(asset, refresh=False):
    """Per decision time t (a completed daily close): every signal as it was knowable at t."""
    candles = daily(asset, refresh)
    times = [c[0] for c in candles]
    closes = np.array([c[1] for c in candles])
    log_returns = np.diff(np.log(closes), prepend=np.nan)
    fund = columns(funding(asset, refresh))
    vol = columns(
        implied("ETH" if asset == "ETH" else "BTC", refresh)
    )  # Solana has no index; Bitcoin's stands in
    stable, mood = columns(stablecoins(refresh)), columns(fear_greed(refresh))
    out = {
        name: [None] * len(times)
        for name in ("funding_7d", "implied_vol", "vol_premium", "stable_30d", "mood", "taker_7d")
    }
    for i, t in enumerate(times):
        a, b = (
            bisect_left(fund[0], t - 7 * DAY),
            bisect_left(fund[0], t),
        )  # settled strictly before the decision
        if b - a >= 15:
            out["funding_7d"][i] = float(np.mean(fund[1][a:b]))
        k = bisect_right(vol[0], t - DAY) - 1  # the candle that started a day earlier has closed by t
        if k >= 0 and t - DAY - vol[0][k] < 3 * DAY:
            index = vol[1][k]
            out["implied_vol"][i] = index
            if i >= 30:
                realised = float(np.std(log_returns[i - 29 : i + 1]) * math.sqrt(365) * 100)
                out["vol_premium"][i] = index - realised
        now, month = before(stable, t, DAY), before(stable, t, 31 * DAY)
        if now and month:
            out["stable_30d"][i] = now / month - 1
        out["mood"][i] = before(mood, t, DAY)
        if i >= 6:
            volume = sum(c[2] for c in candles[i - 6 : i + 1])
            out["taker_7d"][i] = sum(c[3] for c in candles[i - 6 : i + 1]) / volume - 0.5 if volume else None
    return times, closes, out


def ranks(values):
    """Where today's value sits within its own trailing year. Uses earlier days only."""
    out = [None] * len(values)
    for i, v in enumerate(values):
        past = [x for x in values[max(0, i - WINDOW) : i] if x is not None]
        if v is not None and len(past) >= MIN_HISTORY:
            out[i] = sum(x <= v for x in past) / len(past)
    return out


def interval(values, flags, repeats=2000, seed=5):
    """Mean of the flagged days and a 95% interval from circular 30-day blocks: neighbouring days share a market."""
    values, flags = np.asarray(values), np.asarray(flags)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(values), size=(repeats, len(values) // BLOCK + 1))
    rows = ((starts[:, :, None] + np.arange(BLOCK)) % len(values)).reshape(repeats, -1)[:, : len(values)]
    picked = flags[rows]
    sums, counts = (values[rows] * picked).sum(axis=1), picked.sum(axis=1)
    means = sums[counts > 0] / counts[counts > 0]
    return float(values[flags].mean()), [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def bucket_table(refresh=False):
    table, series = [], {}
    for asset in ASSETS:
        times, closes, raw = signals(asset, refresh)
        series[asset] = (times, {name: ranks(values) for name, values in raw.items()})
        logs = np.log(closes)
        for name, rank in series[asset][1].items():
            for horizon in HORIZONS:
                for period, (lo, hi) in {"fit": (START, SPLIT), "test": (SPLIT, 2**40)}.items():
                    days = [
                        i
                        for i, t in enumerate(times)
                        if lo <= t < hi
                        and rank[i] is not None
                        and i + horizon < len(times)
                        # A window that starts before the split must also end before it.
                        and (period == "test" or times[i + horizon] < SPLIT)
                    ]
                    if len(days) < 200:
                        continue
                    forward = np.array([logs[i + horizon] - logs[i] for i in days])
                    forward -= forward.mean()
                    for side, flag in (
                        ("low", [rank[i] <= LOW for i in days]),
                        ("high", [rank[i] >= HIGH for i in days]),
                    ):
                        if sum(flag) < MIN_DAYS:
                            continue
                        mean, ci = interval(forward, flag)
                        table.append(
                            {
                                "asset": asset,
                                "signal": name,
                                "side": side,
                                "horizon": horizon,
                                "period": period,
                                "days": int(sum(flag)),
                                "mean": mean,
                                "ci95": ci,
                                "clear": ci[0] > 0 or ci[1] < 0,
                            }
                        )
    return table, series


def overlays(series, refresh=False):
    """On top of the frozen trend rule: step aside on the days a signal sits in one extreme. Chosen before the split."""
    from .study import daily_closes

    data = daily_closes(list(ASSETS), refresh)
    days = min(len(data[a]) for a in ASSETS)
    times = [row[0] for row in data[ASSETS[0]][-days:]]
    log_prices = np.log([[data[a][-days + i][1] for a in ASSETS] for i in range(days)])
    base = np.full(len(ASSETS), MAX_CRYPTO / len(ASSETS))
    split = bisect_left(times, SPLIT)
    lookup = {a: dict(zip(series[a][0], range(len(series[a][0])), strict=True)) for a in ASSETS}

    def factor(name, side, i):
        out = np.ones(len(ASSETS))
        for k, a in enumerate(ASSETS):
            j = lookup[a].get(times[i])
            rank = series[a][1][name][j] if j is not None else None
            if rank is not None and (rank <= LOW if side == "low" else rank >= HIGH):
                out[k] = 0.0
        return out

    def run(weights, lo, hi):
        return simulate(log_prices[: hi + 1], weights, COST, start=lo)

    def plain(p, i):
        return trend_weights(p, i, base)

    first = max(LOOKBACKS) + 4
    results, reference = [], {"fit": run(plain, first, split), "test": run(plain, split, days - 1)}
    held = {"fit": run(lambda *_: base, first, split), "test": run(lambda *_: base, split, days - 1)}
    for name in series[ASSETS[0]][1]:
        for side in ("low", "high"):

            def rule(p, i, name=name, side=side):
                return trend_weights(p, i, base) * factor(name, side, i)

            fit, test = run(rule, first, split), run(rule, split, days - 1)
            results.append(
                {
                    "signal": name,
                    "step_aside_when": side,
                    "fit": {
                        **curve_stats(fit),
                        "sharpe_gap": curve_stats(fit)["sharpe"] - curve_stats(reference["fit"])["sharpe"],
                    },
                    "test": {
                        **curve_stats(test),
                        "sharpe_gap": curve_stats(test)["sharpe"] - curve_stats(reference["test"])["sharpe"],
                        "sharpe_gap_ci95": sharpe_gap_interval(test, reference["test"]),
                    },
                }
            )
    # The choice uses the years before the split alone.
    chosen = [
        r["signal"] + ":" + r["step_aside_when"]
        for r in sorted(results, key=lambda r: -r["fit"]["sharpe_gap"])[:3]
    ]
    return {
        "first_day": times[first],
        "split_day": times[split],
        "last_day": times[-1],
        "trend_rule": {k: curve_stats(v) for k, v in reference.items()},
        "rebalanced": {k: curve_stats(v) for k, v in held.items()},
        "chosen_before_split": chosen,
        "overlays": results,
    }


def build(refresh=False):
    table, series = bucket_table(refresh)
    paired = {}
    for row in table:
        paired.setdefault((row["asset"], row["signal"], row["side"], row["horizon"]), {})[row["period"]] = row
    effects = []
    for (asset, signal, side, horizon), both in sorted(paired.items()):
        if len(both) < 2:
            continue
        fit, test = both["fit"], both["test"]
        effects.append(
            {
                "asset": asset,
                "signal": signal,
                "side": side,
                "horizon": horizon,
                "fit": {k: fit[k] for k in ("days", "mean", "ci95", "clear")},
                "test": {k: test[k] for k in ("days", "mean", "ci95", "clear")},
                "holds": fit["clear"] and test["clear"] and (fit["mean"] > 0) == (test["mean"] > 0),
            }
        )
    report = {
        "schema": 1,
        "kind": "exploratory historical study of slow market-state signals; every combination reported; not a forward claim",
        "created_at": int(time.time()),
        "split": SPLIT,
        "tests": len(effects),
        "expected_false_positives": round(len(effects) * 0.05 * 0.05 * 0.5, 2),
        "effects": effects,
        "trend_overlays": overlays(series, refresh),
    }
    (config.DATA / "signals-study-report.json").write_text(json.dumps(report, indent=2))
    return report
