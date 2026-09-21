import numpy as np
import pytest

from oracle import signals_study as study

DAY = study.DAY


def test_a_value_counts_only_if_it_was_stamped_before_the_decision():
    series = ([100, 200, 300], [1.0, 2.0, 3.0])
    assert (
        study.before(series, 200) == 2.0
        and study.before(series, 199) == 1.0
        and study.before(series, 99) is None
    )
    # With an age, a value stamped at the decision time itself is too young.
    assert study.before(series, 300, age=1) == 2.0


def test_ranks_compare_today_with_earlier_days_only():
    values = [float(i) for i in range(study.MIN_HISTORY + 2)]
    ranks = study.ranks(values)
    assert ranks[study.MIN_HISTORY - 1] is None and ranks[study.MIN_HISTORY] == 1.0
    # A later record high must not change what an earlier day was ranked as.
    assert study.ranks([*values, 1e9])[: len(values)] == ranks
    assert study.ranks([None] * 400) == [None] * 400


def test_signals_use_nothing_from_the_decision_time_or_later(monkeypatch):
    start = study.START + 400 * DAY
    candles = [[start + i * DAY, 100 + i, 10.0, 6.0] for i in range(60)]
    t = candles[40][0]
    funding = [[t - 7 * DAY + k * 28800, 0.0001] for k in range(21)] + [[t, 0.05], [t + 28800, 0.05]]
    dvol = [[t - 2 * DAY, 50.0], [t - DAY, 60.0], [t, 99.0]]
    stable = [[t - 40 * DAY, 100.0], [t - 31 * DAY, 100.0], [t - DAY, 110.0], [t, 500.0]]
    mood = [[t - DAY, 40.0], [t, 90.0]]
    monkeypatch.setattr(study, "daily", lambda asset, refresh=False: candles)
    monkeypatch.setattr(study, "funding", lambda asset, refresh=False: funding)
    monkeypatch.setattr(study, "implied", lambda currency, refresh=False: dvol)
    monkeypatch.setattr(study, "stablecoins", lambda refresh=False: stable)
    monkeypatch.setattr(study, "fear_greed", lambda refresh=False: mood)
    times, _, out = study.signals("BTC")
    i = times.index(t)
    assert out["funding_7d"][i] == pytest.approx(0.0001)  # the settlement at t itself is excluded
    assert out["implied_vol"][i] == 60.0  # yesterday's candle has closed; today's has not
    assert out["stable_30d"][i] == pytest.approx(0.10) and out["mood"][i] == 40.0
    assert out["taker_7d"][i] == pytest.approx(0.1)


def test_the_interval_is_wider_than_a_naive_one_when_forward_windows_overlap():
    rng = np.random.default_rng(1)
    daily = rng.normal(0, 0.03, 1200)
    # Fourteen-day forward returns of neighbouring days share thirteen of their fourteen days.
    values = np.array([daily[i : i + 14].sum() for i in range(1100)])
    flags = np.zeros(1100, dtype=bool)
    for begin in (100, 400, 700, 950):  # a slow signal stays in its extreme for weeks at a time
        flags[begin : begin + 40] = True
    mean, (low, high) = study.interval(values, flags)
    naive = values[flags].std() / np.sqrt(flags.sum()) * 1.96
    assert mean == pytest.approx(values[flags].mean()) and low < mean < high
    assert (high - low) / 2 > 2 * naive
