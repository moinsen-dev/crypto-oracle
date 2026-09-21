"""Exploratory study: does buying the last weeks' strongest coins pay?

Survivors flatter this kind of test, so the universe is rebuilt for every week from the pairs that traded then,
delisted ones included, ranked by the dollar volume of the month before. The rule comes from the published
cross-sectional momentum literature and was fixed before looking: every Monday hold the strongest fifth of the
thirty most traded coins, equally weighted, for one week. Every variant is reported, the years before SPLIT and
after it separately. Not a forward claim.
"""

import json
import math
import re
import time
from datetime import UTC, datetime

import httpx
import numpy as np

from . import config
from .study import HEADERS, LOOKBACKS, MAX_CRYPTO, get

DAY = 86400
START = 1514764800  # 2018-01-01
SPLIT = 1672531200  # 2023-01-01
LOOKBACK_WEEKS = (1, 2, 4)
UNIVERSES = (30, 50)
COSTS = (0.003, 0.005)  # per side; small coins cost more to trade than the three large ones
PRIMARY = {"weeks": 2, "universe": 30, "cost": 0.003, "trend": False}
MIN_LISTED_DAYS = 60
DELISTING_HAIRCUT = (
    0.5  # a position still held when a pair stops trading is assumed to lose half of what is left
)
BLOCK_WEEKS = 8
# Not coins in the sense of this test: money, wrapped copies of another coin, leveraged products.
NOT_COINS = {
    "USDC", "BUSD", "TUSD", "DAI", "FDUSD", "USDP", "PAX", "USDS", "USDSB", "USDSOLD", "SUSD", "UST", "USTC",
    "EUR", "EURI", "AEUR", "GBP", "AUD", "TRY", "BRL", "RUB", "UAH", "NGN", "ZAR", "IDRT", "BIDR", "BKRW", "BVND",
    "XUSD", "USD1", "PYUSD", "USDE", "BFUSD", "WBTC", "BETH", "WBETH", "BTCB", "PAXG",
}  # fmt: skip


def folder():
    path = config.DATA / "momentum-study"
    path.mkdir(parents=True, exist_ok=True)
    return path


def symbols(refresh=False):
    """Every USDT pair the exchange has ever listed and still reports, whatever its status today."""
    cache = folder() / "symbols.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())
    with httpx.Client(timeout=60, headers=HEADERS) as client:
        info = get(client, "https://api.binance.com/api/v3/exchangeInfo").json()
    pairs = [s for s in info["symbols"] if s["quoteAsset"] == "USDT"]
    bases = {s["baseAsset"] for s in pairs}
    out = []
    for s in pairs:
        base = s["baseAsset"]
        leveraged = re.fullmatch(r"(.+)(UP|DOWN|BULL|BEAR)", base)
        if base in NOT_COINS or (leveraged and leveraged.group(1) in bases):
            continue
        out.append({"symbol": s["symbol"], "base": base, "trading": s["status"] == "TRADING"})
    cache.write_text(json.dumps(out))
    return out


def candles(symbol, client, refresh=False):
    """Completed daily candles of one pair: [close time, close, dollar volume]."""
    cache = folder() / f"{symbol}.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())
    rows, start, now = [], START * 1000, int(time.time())
    while True:
        page = get(
            client,
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": "1d", "startTime": start, "limit": 1000},
        ).json()
        rows += page
        if len(page) < 1000:
            break
        start = page[-1][0] + DAY * 1000
        time.sleep(0.12)
    data = [
        [r[6] // 1000 + 1, float(r[4]), float(r[7])] for r in rows if r[6] // 1000 < now and float(r[4]) > 0
    ]
    cache.write_text(json.dumps(data))
    time.sleep(0.12)
    return data


def panel(refresh=False):
    """Closes and dollar volumes of every pair on one daily grid; NaN where a pair did not trade."""
    listed = symbols(refresh)
    with httpx.Client(timeout=30, headers=HEADERS) as client:
        data = {s["base"]: candles(s["symbol"], client, refresh) for s in listed}
    data = {k: v for k, v in data.items() if v}
    first, last = min(v[0][0] for v in data.values()), max(v[-1][0] for v in data.values())
    times = list(range(first, last + 1, DAY))
    index = {t: i for i, t in enumerate(times)}
    names = sorted(data)
    close = np.full((len(times), len(names)), np.nan)
    volume = np.zeros((len(times), len(names)))
    for k, name in enumerate(names):
        for t, c, v in data[name]:
            if t in index:
                close[index[t], k], volume[index[t], k] = c, v
    return times, names, close, volume


def weekly(times, names, close, volume, universe, refresh=False):
    """For every Monday: who was in the universe, how strong each coin had been, and what it did next."""
    out = []
    btc = names.index("BTC")
    for i, t in enumerate(times):
        if datetime.fromtimestamp(t, UTC).weekday() != 0 or i < 70 or i + 7 >= len(times):
            continue
        listed = (~np.isnan(close[i - MIN_LISTED_DAYS : i + 1])).all(axis=0)
        dollars = np.where(listed, volume[i - 29 : i + 1].mean(axis=0), -1.0)
        members = np.argsort(-dollars)[:universe]
        members = members[dollars[members] > 0]
        if len(members) < universe:
            continue
        week = close[i : i + 8, members]
        # A pair that stops trading during the week is sold at its last price, less the haircut.
        last = np.array([column[~np.isnan(column)][-1] for column in week.T])
        gone = np.isnan(week[-1])
        forward = last / week[0] * np.where(gone, 1 - DELISTING_HAIRCUT, 1.0) - 1
        strength = {
            w: close[i, members] / close[i - 7 * w, members] - 1 for w in LOOKBACK_WEEKS
        }  # NaN if not listed then
        trend = float(np.mean([close[i, btc] > close[i - k, btc] for k in LOOKBACKS]))
        out.append(
            {
                "t": t,
                "members": [names[m] for m in members],
                "forward": forward,
                "gone": gone,
                "strength": strength,
                "trend": trend,
                "btc": float(close[i + 7, btc] / close[i, btc] - 1),
            }
        )
    return out


def quintiles(weeks, lookback):
    """Average next-week return of each strength fifth, relative to the whole universe of that week."""
    rows = []
    for w in weeks:
        strength, forward = w["strength"][lookback], w["forward"]
        known = ~np.isnan(strength)
        if known.sum() < 10:
            continue
        order = np.argsort(strength[known])
        groups = np.array_split(forward[known][order], 5)
        rows.append([g.mean() - forward[known].mean() for g in groups])
    return np.array(rows)


def block_interval(values, repeats=2000, seed=3):
    rng = np.random.default_rng(seed)
    n = len(values)
    starts = rng.integers(0, n, size=(repeats, n // BLOCK_WEEKS + 1))
    rows = ((starts[:, :, None] + np.arange(BLOCK_WEEKS)) % n).reshape(repeats, -1)[:, :n]
    means = values[rows].mean(axis=1)
    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def curve(weeks, pick, cost, trend):
    """Weekly equity of a long-only portfolio at the paper policy's crypto cap, with costs on every change."""
    equity, held, out = 1.0, {}, []
    for w in weeks:
        chosen = pick(w)
        scale = MAX_CRYPTO * (w["trend"] if trend else 1.0)
        wanted = {name: scale / len(chosen) for name in chosen} if chosen else {}
        turnover = sum(abs(wanted.get(k, 0) - held.get(k, 0)) for k in set(wanted) | set(held))
        equity *= 1 - turnover * cost
        returns = dict(zip(w["members"], w["forward"], strict=True))
        growth = sum(weight * returns[name] for name, weight in wanted.items())
        equity *= 1 + growth
        held = {name: weight * (1 + returns[name]) / (1 + growth) for name, weight in wanted.items()}
        out.append(equity)
    return np.array(out)


def stats(equity):
    weekly_log = np.diff(np.log(np.r_[1.0, equity]))
    return {
        "cagr": float(equity[-1] ** (52 / len(equity)) - 1),
        "sharpe": float(weekly_log.mean() / weekly_log.std() * math.sqrt(52)) if weekly_log.std() else 0.0,
        "max_drawdown": float(np.max(1 - equity / np.maximum.accumulate(np.r_[1.0, equity])[1:])),
    }


def sharpe_gap(a, b, repeats=2000, seed=9):
    x, y = np.diff(np.log(np.r_[1.0, a])), np.diff(np.log(np.r_[1.0, b]))
    rng = np.random.default_rng(seed)
    n = len(x)
    starts = rng.integers(0, n, size=(repeats, n // BLOCK_WEEKS + 1))
    rows = ((starts[:, :, None] + np.arange(BLOCK_WEEKS)) % n).reshape(repeats, -1)[:, :n]
    gaps = (
        x[rows].mean(axis=1) / x[rows].std(axis=1) - y[rows].mean(axis=1) / y[rows].std(axis=1)
    ) * math.sqrt(52)
    return [float(np.quantile(gaps, 0.025)), float(np.quantile(gaps, 0.975))]


def strongest(lookback):
    def pick(w):
        strength = w["strength"][lookback]
        known = [k for k in range(len(w["members"])) if not np.isnan(strength[k])]
        top = sorted(known, key=lambda k: -strength[k])[: max(1, len(w["members"]) // 5)]
        return [w["members"][k] for k in top]

    return pick


def everyone(w):
    return list(w["members"])


def build(refresh=False):
    times, names, close, volume = panel(refresh)
    report = {
        "schema": 1,
        "kind": "exploratory historical study; rule fixed in advance; every variant reported; not a forward claim",
        "created_at": int(time.time()),
        "pairs": len(names),
        "pairs_no_longer_trading": sum(not s["trading"] for s in symbols() if s["base"] in names),
        "split": SPLIT,
        "primary": PRIMARY,
        "universes": {},
    }
    for universe in UNIVERSES:
        weeks = weekly(times, names, close, volume, universe)
        periods = {
            "fit": [w for w in weeks if w["t"] + 7 * DAY <= SPLIT],
            "test": [w for w in weeks if w["t"] >= SPLIT],
        }
        entry = {
            "first_week": weeks[0]["t"],
            "last_week": weeks[-1]["t"],
            "weeks": {k: len(v) for k, v in periods.items()},
            "distinct_coins": len({m for w in weeks for m in w["members"]}),
            "forced_exits": int(sum(w["gone"].sum() for w in weeks)),
            "fifths": {},
            "portfolios": {},
        }
        for lookback in LOOKBACK_WEEKS:
            entry["fifths"][lookback] = {}
            for name, part in periods.items():
                rows = quintiles(part, lookback)
                spread = rows[:, 4] - rows[:, 0]
                entry["fifths"][lookback][name] = {
                    "weakest_to_strongest": rows.mean(axis=0).tolist(),
                    "strongest_minus_weakest": float(spread.mean()),
                    "ci95": block_interval(spread),
                    "strongest_vs_universe_ci95": block_interval(rows[:, 4]),
                }
        for name, part in periods.items():
            for cost in COSTS:
                reference = curve(part, everyone, cost, False)
                key = f"{name} · cost {cost:.1%}"
                entry["portfolios"][key] = {
                    "all coins equally": stats(reference),
                    "bitcoin only": stats(np.cumprod([1 + MAX_CRYPTO * w["btc"] for w in part])),
                }
                for lookback in LOOKBACK_WEEKS:
                    for trend in (False, True):
                        equity = curve(part, strongest(lookback), cost, trend)
                        label = f"strongest fifth · {lookback}w" + (" · market trend" if trend else "")
                        entry["portfolios"][key][label] = {
                            **stats(equity),
                            "sharpe_gap_vs_all_ci95": sharpe_gap(equity, reference),
                        }
                trended = curve(part, everyone, cost, True)
                entry["portfolios"][key]["all coins equally · market trend"] = {
                    **stats(trended),
                    "sharpe_gap_vs_all_ci95": sharpe_gap(trended, reference),
                }
        report["universes"][universe] = entry
    (config.DATA / "momentum-study-report.json").write_text(json.dumps(report, indent=2))
    return report
