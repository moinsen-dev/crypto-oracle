from datetime import UTC, datetime

import httpx
import numpy as np
import pytest

from oracle import config
from oracle import momentum_study as study

DAY = study.DAY
MONDAY = int(datetime(2021, 3, 1, tzinfo=UTC).timestamp())


def test_money_wrapped_copies_and_leveraged_products_are_not_coins(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    listed = [
        ("BTC", "TRADING"),
        ("BTCUP", "BREAK"),
        ("ETHBEAR", "BREAK"),
        ("ETH", "TRADING"),
        ("JUP", "TRADING"),
    ]
    listed += [("USDC", "TRADING"), ("WBTC", "TRADING"), ("LUNA", "BREAK")]
    info = {
        "symbols": [
            {"symbol": b + "USDT", "baseAsset": b, "quoteAsset": "USDT", "status": s} for b, s in listed
        ]
    }
    info["symbols"].append({"symbol": "ETHBTC", "baseAsset": "ETH", "quoteAsset": "BTC", "status": "TRADING"})
    monkeypatch.setattr(study, "get", lambda client, url, **k: httpx.Response(200, json=info))
    found = {s["base"]: s["trading"] for s in study.symbols()}
    # JUP ends in "UP" but there is no coin called "J"; a delisted coin stays in the list.
    assert found == {"BTC": True, "ETH": True, "JUP": True, "LUNA": False}


def panel(days=170):
    times = [MONDAY - 98 * DAY + i * DAY for i in range(days)]
    names = ["BTC", "DOOMED", "LATE", "QUIET", *[f"C{k:02d}" for k in range(30)]]
    close = np.full((days, len(names)), 100.0)
    volume = np.full((days, len(names)), 1000.0)
    for k in range(30):
        close[:, 4 + k] = 100 * (1 + 0.001 * (k - 15)) ** np.arange(days)  # steady winners and losers
        volume[:, 4 + k] = 2000.0 + k  # distinct, so that the ranking by volume has no ties
    volume[:, names.index("QUIET")] = 1.0  # too little traded to be in the universe
    late = names.index("LATE")
    close[:80, late], volume[:80, late] = np.nan, 0.0  # listed for fewer than sixty days on the first Monday
    volume[80:, late] = 1e9
    doomed = names.index("DOOMED")
    volume[:, doomed] = 5000.0
    close[101:, doomed] = np.nan  # stops trading three days after the Monday
    close[100, doomed] = 40.0
    return times, names, close, volume


def test_the_universe_is_what_traded_then_and_a_vanished_pair_costs_half_of_what_was_left():
    times, names, close, volume = panel()
    weeks = study.weekly(times, names, close, volume, universe=30)
    first = next(w for w in weeks if w["t"] == MONDAY)
    assert "QUIET" not in first["members"] and "LATE" not in first["members"] and "DOOMED" in first["members"]
    k = first["members"].index("DOOMED")
    assert first["gone"][k] and first["forward"][k] == pytest.approx(40 / 100 * 0.5 - 1)
    # Seven weeks later the newcomer has sixty days of history and the vanished pair is no longer eligible.
    assert "LATE" not in next(w for w in weeks if w["t"] == MONDAY + 28 * DAY)["members"]
    later = next(w for w in weeks if w["t"] == MONDAY + 49 * DAY)
    assert "LATE" in later["members"] and "DOOMED" not in later["members"]
    # Strength reads the past only: changing every later close leaves it untouched.
    changed = close.copy()
    changed[times.index(MONDAY) + 1 :] *= 3
    again = next(w for w in study.weekly(times, names, changed, volume, universe=30) if w["t"] == MONDAY)
    assert all(np.allclose(first["strength"][w], again["strength"][w]) for w in study.LOOKBACK_WEEKS)


def test_the_strongest_fifth_is_picked_and_measured_against_the_whole_universe():
    times, names, close, volume = panel()
    weeks = [w for w in study.weekly(times, names, close, volume, universe=30) if w["t"] >= MONDAY + 28 * DAY]
    picked = study.strongest(2)(weeks[0])
    assert len(picked) == 6 and set(picked) <= {f"C{k:02d}" for k in range(24, 30)}
    fifths = study.quintiles(weeks, 2).mean(axis=0)
    assert (
        fifths[4] > 0 > fifths[0] and abs(fifths.sum()) < 1e-9
    )  # steady winners keep winning in this toy market


def test_costs_are_paid_on_every_change_and_the_market_trend_scales_the_position():
    week = {"members": ["A", "B"], "forward": np.array([0.10, 0.0]), "trend": 0.5}
    full = study.curve([week], lambda w: ["A"], cost=0.01, trend=False)
    assert full[0] == pytest.approx((1 - 0.6 * 0.01) * (1 + 0.6 * 0.10))
    half = study.curve([week], lambda w: ["A"], cost=0.01, trend=True)
    assert half[0] == pytest.approx((1 - 0.3 * 0.01) * (1 + 0.3 * 0.10))
    # Holding the same coin again costs only the small rebalancing back to the target weight.
    two = study.curve([week, week], lambda w: ["A"], cost=0.01, trend=False)
    drifted = 0.6 * 1.10 / (1 + 0.06)
    assert two[1] == pytest.approx(two[0] * (1 - abs(0.6 - drifted) * 0.01) * (1 + 0.06))
