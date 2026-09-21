import math

import numpy as np
import pytest

from oracle import news_study


def test_headlines_are_typed_by_their_words_and_price_echoes_are_flagged():
    assert news_study.kind("Exchange hacked, 4,000 bitcoin stolen") == ("security", False, False)
    assert news_study.kind("SEC sues exchange over unregistered securities")[0] == "enforcement"
    assert news_study.kind("Bitcoin plunges after SEC lawsuit") == ("enforcement", True, False)
    assert news_study.kind("3 reasons why bitcoin could double this year")[2] is True
    assert news_study.kind("Bitcoin conference opens in Miami") == ("other", False, False)


def series(hours, step=0.001):
    start = news_study.SPLIT - 40 * 86400
    return {start + i * 3600: 100 * math.exp(step * i) for i in range(hours)}, start


def test_a_headline_counts_only_from_the_first_full_hour_after_we_could_have_seen_it(monkeypatch):
    closes, start = series(24 * 60)
    seen = start + 30 * 86400
    rows = [
        {"at": seen + 60, "title": "Exchange hacked", "source": "x"},  # 00:01 -> seen 00:16 -> acts at 01:00
        {"at": seen + 3600 - 1000, "title": "Miners expand", "source": "x"},  # 00:43 -> seen 00:58 -> 01:00
        {"at": seen + 3600 - 800, "title": "Fed holds rates", "source": "x"},  # 00:46 -> seen 01:01 -> 02:00
    ]
    monkeypatch.setattr(news_study, "hourly", lambda refresh=False: closes)
    monkeypatch.setattr(news_study, "corpus", lambda refresh=False: rows)
    monkeypatch.setattr(news_study, "sentiments", lambda rows, refresh=False: {r["title"]: 0.0 for r in rows})
    events, _ = news_study.events()
    assert [e["base"] - seen for e in events] == [3600, 3600, 7200]
    # A steady drift is the month's normal; measured against it nothing is abnormal, and no move is unusual.
    assert all(abs(v) < 1e-9 for e in events for v in e["after"].values())
    assert all(v == pytest.approx(1.0) for e in events for v in e["size"].values())


def test_the_interval_resamples_days_not_headlines():
    # Fifty headlines of one day are one observation of the market, however many there are.
    mean, (low, high) = news_study.interval([0.01] * 50 + [-0.01], [1] * 50 + [2])
    assert mean == pytest.approx(0.49 / 51) and low == pytest.approx(-0.01) and high == pytest.approx(0.01)


def test_a_rule_acts_only_after_its_trigger_and_pays_for_every_switch():
    closes = {news_study.SPLIT + i * 3600: 100 * math.exp(0.01 * i) for i in range(-1, 49)}
    trigger = news_study.SPLIT + 10 * 3600
    flat = news_study.rule_test([trigger], closes, horizon=4, flat=True)
    assert flat["hours"] == 49 and flat["hours_held"] == 45 and flat["switches"] == 2
    expected = math.exp(0.01 * 45 - 2 * news_study.COST) - 1
    assert flat["return"] == pytest.approx(expected) and flat["hold_return"] == pytest.approx(
        math.exp(0.49) - 1
    )
    only = news_study.rule_test([trigger], closes, horizon=4, flat=False)
    assert only["hours_held"] == 4 and np.isclose(only["return"], math.exp(0.04 - 2 * news_study.COST) - 1)
