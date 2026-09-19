import json
import random
import sqlite3
import time
from itertools import pairwise

import pytest

from oracle import config, fusion, learning, paper, volband
from oracle.db import connect, digest, init
from oracle.forecast import evaluate, store_forecast
from oracle.ingest import store_candles


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "volband.sqlite3")
    monkeypatch.delenv("ORACLE_VOLBAND_ENABLED", raising=False)
    init()
    volband.init_schema()


def seed_history(asset, origin, hours, seed, start=100.0):
    """hours+1 consecutive hourly candles ending exactly at origin; a small deterministic random walk."""
    rng = random.Random(seed)
    price = start
    rows = []
    for i in range(hours + 1):
        ts = origin - (hours - i) * 3600
        if i:
            price *= 1 + rng.uniform(-0.01, 0.01)
        rows.append((asset, ts, price, 1.0, "test", ts + 1, digest([asset, ts, seed])))
    with connect() as db:
        db.executemany("INSERT OR IGNORE INTO candles VALUES(?,?,?,?,?,?,?)", rows)
    return price


SEEDS = {"BTC": 1, "ETH": 2, "SOL": 3}


def seed_all(origin, hours=1500):
    for asset in config.ASSETS:
        seed_history(asset, origin, hours, SEEDS[asset])


def parent_forecast(origin, base=100.0):
    horizon = max(config.HORIZONS)
    path = [
        {"t": origin + (i + 1) * 3600, "p": base * (1 + 0.001 * i), "lo": base * 0.9, "hi": base * 1.1}
        for i in range(horizon)
    ]
    provenance = {"model_revision": config.MODEL_REVISION, "quote": "USDT", "input_hash": "a" * 64}
    return store_forecast(
        "BTC", "timesfm", origin, horizon, base, path, {}, provenance, 1, issued_at=origin + 2
    )


def test_disabled_flag_writes_nothing():
    origin = 1789635600
    seed_all(origin, hours=800)
    parent_forecast(origin)
    with connect() as db:
        before = (
            db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0],
            db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0],
        )
    assert volband.cycle() == {"state": "disabled"}
    with connect() as db:
        after = (
            db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0],
            db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0],
        )
    assert after == before


def test_fit_cannot_see_the_future(monkeypatch):
    monkeypatch.setitem(volband.POLICY, "min_fit_samples", 30)
    origin = 2_000_000 * 3600
    seed_all(origin, hours=1500)
    baseline = volband.fit(origin, 1)
    assert baseline is not None and baseline["n"] >= 30
    with connect() as db:
        db.execute(
            "INSERT INTO candles VALUES(?,?,?,?,?,?,?)",
            ("BTC", origin + 3600, 101.0, 1, "test", origin + 3601, "f1"),
        )
        db.execute(
            "INSERT INTO candles VALUES(?,?,?,?,?,?,?)",
            ("BTC", origin + 7200, 102.0, 1, "test", origin + 7201, "f2"),
        )
    # A candle recorded after the origin, however it later gets revised, must never move the artifact.
    assert volband.fit(origin, 1) == baseline
    with connect() as db:
        db.execute("UPDATE candles SET close=9999.0 WHERE asset='BTC' AND ts=?", (origin + 3600,))
        db.execute("UPDATE candles SET close=0.5 WHERE asset='BTC' AND ts=?", (origin + 7200,))
    assert volband.fit(origin, 1) == baseline


def test_gaps_exclude_samples(monkeypatch):
    monkeypatch.setitem(volband.POLICY, "min_fit_samples", 30)
    origin = 2_000_000 * 3600
    seed_all(origin, hours=1500)
    baseline = volband.fit(origin, 1)
    assert baseline is not None
    with connect() as db:
        db.execute("DELETE FROM candles WHERE asset='BTC' AND ts=?", (origin - 400 * 3600,))
    gapped = volband.fit(origin, 1)
    assert gapped is not None
    assert gapped["n"] < baseline["n"]


def test_emission_is_idempotent_and_pairs_correctly(monkeypatch):
    monkeypatch.setenv("ORACLE_VOLBAND_ENABLED", "1")
    monkeypatch.setitem(volband.POLICY, "min_fit_samples", 30)
    now = 2_000_000 * 3600 + 100
    monkeypatch.setattr(time, "time", lambda: now)
    origin = now // 3600 * 3600
    seed_all(origin, hours=1500)
    fid = parent_forecast(origin, base=100.0)
    result = volband.cycle()
    horizons = volband.POLICY["horizons"]
    assert result == {
        "state": "observing",
        "experiment": volband.EXPERIMENT,
        "forecasts_added": len(horizons) * 2,
    }
    assert volband.cycle() == {"state": "observing", "experiment": volband.EXPERIMENT, "forecasts_added": 0}
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM forecasts WHERE experiment=? AND asset='BTC' ORDER BY horizon,model",
            (volband.EXPERIMENT,),
        ).fetchall()
        parent_path = json.loads(db.execute("SELECT path FROM forecasts WHERE id=?", (fid,)).fetchone()[0])
    assert len(rows) == len(horizons) * 2
    for h in horizons:
        band = next(r for r in rows if r["horizon"] == h and r["model"] == "volband")
        path_row = next(r for r in rows if r["horizon"] == h and r["model"] == "timesfm_path")
        assert band["origin"] == path_row["origin"] == origin
        assert band["base"] == path_row["base"] == 100.0
        assert band["target"] == path_row["target"] == origin + h * 3600
        assert band["prediction"] == 100.0
        assert band["lower"] < 100.0 < band["upper"]
        truncated = json.loads(path_row["path"])
        assert len(truncated) == h
        assert truncated[-1]["p"] == parent_path[h - 1]["p"]
        assert truncated[-1]["lo"] == parent_path[h - 1]["lo"]


def test_no_parent_means_no_emission(monkeypatch):
    monkeypatch.setenv("ORACLE_VOLBAND_ENABLED", "1")
    monkeypatch.setitem(volband.POLICY, "min_fit_samples", 30)
    now = 2_000_000 * 3600 + 50
    monkeypatch.setattr(time, "time", lambda: now)
    seed_all(now // 3600 * 3600, hours=1500)
    assert volband.cycle() == {"state": "observing", "experiment": volband.EXPERIMENT, "forecasts_added": 0}
    with connect() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM forecasts WHERE experiment=?", (volband.EXPERIMENT,)).fetchone()[
                0
            ]
            == 0
        )


def test_experiment_id_changes_when_policy_changes():
    changed = {**volband.POLICY, "min_fit_samples": volband.POLICY["min_fit_samples"] + 1}
    assert "volband-v1-" + digest(changed)[:12] != volband.EXPERIMENT


def test_review_window_is_immutable_and_assessed_once(monkeypatch):
    horizon = 1
    start = 1780002000 // 3600 * 3600
    due = start + 28 * 86400 + horizon * 3600
    monkeypatch.setattr(time, "time", lambda: due - 1)
    for i in range(28):
        origin = start + i * 86400
        target = origin + horizon * 3600
        for model, prediction in (("volband", 100.0), ("timesfm_path", 101.0)):
            store_forecast(
                "BTC",
                model,
                origin,
                horizon,
                100.0,
                [{"t": target, "p": prediction, "lo": 96.0, "hi": 104.0}],
                {},
                {},
                1,
                issued_at=origin + 4,
                experiment=volband.EXPERIMENT,
            )
        store_candles("BTC", [[(target - 3600) * 1000, 103, 103, 103, 103, 1]], target + 10)
    evaluate()
    volband.assess()
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM volband_reviews").fetchone()[0] == 0
    monkeypatch.setattr(time, "time", lambda: due + 1)
    volband.assess()
    volband.assess()
    with connect() as db:
        rows = db.execute("SELECT * FROM volband_reviews").fetchall()
        assert len(rows) == 1
        verdict = json.loads(rows[0]["payload"])
        assert verdict["n"] == 28
        assert verdict["auto_promoted"] is False
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE volband_reviews SET reviewed_at=0")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM volband_reviews")


def test_existing_learning_fusion_and_paper_queries_ignore_volband_rows():
    origin, horizon = 1789635600, 24
    now = origin + 90000
    path = [{"t": origin + (i + 1) * 3600, "p": 101, "lo": 96, "hi": 104} for i in range(horizon)]
    # Same asset/horizon/origin/model as a real signal would use, but filed only under the volband experiment.
    adversarial = store_forecast(
        "BTC",
        "timesfm",
        origin,
        horizon,
        100,
        path,
        {"news_available": True},
        {},
        1,
        issued_at=origin + 2,
        experiment=volband.EXPERIMENT,
    )
    with connect() as db:
        db.execute(
            "INSERT INTO evaluations VALUES(?,?,?,?,?,?,?,?)",
            (adversarial, 101, now, 0.01, 1, 1, 0.01, "adversarial-hash"),
        )
        assert learning.training_rows(db, "BTC", horizon, now) == []
        assert fusion.training_rows("BTC", horizon, now) == []
        signal, error = paper.signal(db, "BTC", now, {})
    assert signal is None and error == "forecast_missing"


def test_live_cycle_runs_the_review_and_a_disabled_one_does_not(monkeypatch):
    calls = []
    monkeypatch.setattr(volband, "assess", lambda: calls.append(1))
    assert volband.cycle() == {"state": "disabled"} and not calls
    monkeypatch.setenv("ORACLE_VOLBAND_ENABLED", "1")
    assert volband.cycle()["state"] == "observing" and calls == [1]


def test_gap_in_the_trailing_window_at_the_origin_blocks_that_coin(monkeypatch):
    monkeypatch.setenv("ORACLE_VOLBAND_ENABLED", "1")
    monkeypatch.setitem(volband.POLICY, "min_fit_samples", 30)
    now = 2_000_000 * 3600 + 100
    monkeypatch.setattr(time, "time", lambda: now)
    origin = now // 3600 * 3600
    for asset in ("ETH", "SOL"):
        seed_history(asset, origin, 1500, SEEDS[asset])
    # BTC misses ten hours inside its last 720; a multi-hour move must not pass as one hourly return.
    seed_history("BTC", origin - 110 * 3600, 1390, SEEDS["BTC"])
    seed_history("BTC", origin, 99, 7)
    parent_forecast(origin)
    assert volband.cycle()["forecasts_added"] == 0
    with connect() as db:
        ts = [r[0] for r in db.execute("SELECT ts FROM candles WHERE asset='BTC' ORDER BY ts")]
    assert max(b - a for a, b in pairwise(ts)) == 11 * 3600
