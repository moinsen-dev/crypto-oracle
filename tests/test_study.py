import math

import numpy as np
import pytest

from oracle import config, study
from oracle.db import init
from oracle.forecast import store_forecast
from oracle.ingest import store_candles


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "study.sqlite3")
    init()


def walk(days=120, assets=2, seed=3):
    return np.cumsum(np.random.default_rng(seed).normal(0, 0.03, size=(days, assets)), axis=0)


def test_trend_weights_cannot_see_the_future():
    prices = walk()
    changed = prices.copy()
    changed[81:] += 5
    assert np.array_equal(study.trend_weights(prices, 80, 0.3), study.trend_weights(changed, 80, 0.3))
    # A coin above all four trailing closes gets its full share; one below all of them gets nothing.
    ramp = np.column_stack([np.linspace(0, 1, 120), np.linspace(1, 0, 120)])
    assert study.trend_weights(ramp, 80, 0.3).tolist() == [0.3, 0.0]


def test_trailing_volatility_cannot_see_the_future():
    prices = walk(assets=1)[:, 0]
    changed = prices.copy()
    changed[61:] += 5
    assert study.trailing_volatility(prices, 24)[60] == study.trailing_volatility(changed, 24)[60]
    assert math.isnan(study.trailing_volatility(prices, 24)[23])


def test_simulation_charges_costs_and_delays_execution():
    flat = np.zeros((80, 1))
    curve = study.simulate(flat, lambda *_: np.array([0.5]), cost=0.01)
    assert curve[0] == pytest.approx(0.995) and curve[-1] == curve[0]
    # The price doubles from day 70 to 71. A signal first visible at day 70 earns it only without delay.
    jump = np.zeros((80, 1))
    jump[71:] = math.log(2)

    def signal(_, i):
        return np.array([1.0 if i >= 70 else 0.0])

    assert study.simulate(jump, signal, cost=0)[-1] == pytest.approx(2)
    assert study.simulate(jump, signal, cost=0, lag=1)[-1] == pytest.approx(1)


def test_curve_stats_report_the_deepest_drawdown():
    stats = study.curve_stats(np.array([1.0, 2.0, 1.0, 1.5, 3.0]))
    assert stats["max_drawdown"] == pytest.approx(0.5)


def test_horizon_skill_scores_every_stored_step(monkeypatch):
    monkeypatch.setattr(config, "HORIZONS", (2,))
    origin = 1_700_000_000 // 3600 * 3600
    now = origin + 10 * 3600
    # Closes: 100 at the origin, then 110 and 121.
    store_candles(
        "BTC",
        [[(origin + (i - 1) * 3600) * 1000, p, p, p, p, 1] for i, p in enumerate((100, 110, 121))],
        now,
    )
    path = [
        {"t": origin + 3600, "lo": 100, "p": 110, "hi": 120},
        {"t": origin + 7200, "lo": 95, "p": 100, "hi": 105},
    ]
    store_forecast("BTC", "timesfm", origin, 2, 100, path, {}, {}, 1, scope="backtest", issued_at=now)
    first, second = study.horizon_skill(steps=(1, 2))
    assert first["model_mae"] == pytest.approx(0, abs=1e-9) and first["coverage"] == 1
    assert first["skill"] == pytest.approx(1)
    assert second["model_mae"] == pytest.approx(math.log(1.21)) and second["coverage"] == 0
    assert second["skill"] == pytest.approx(0, abs=1e-9) and second["direction"] is None
