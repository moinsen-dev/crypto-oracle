import json
import math
import sqlite3
import time

import pytest

from oracle import config, learning, outcomes, public_forecasts
from oracle.db import connect, digest, init, packed
from oracle.forecast import evaluate, store_forecast
from oracle.ingest import store_candles


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "learning.sqlite3")
    monkeypatch.setattr(config, "CONTEXT", 3)
    monkeypatch.delenv("ORACLE_LEARNING_ENABLED", raising=False)
    init()
    learning.init_schema()


def parent(origin, horizon=24, actual=None, now=None):
    candles = [
        {"ts": origin - (2 - i) * 3600, "close": 100, "volume": 1, "observed_at": origin + 1}
        for i in range(3)
    ]
    artifact = {"kind": "input-candles-v1", "asset": "BTC", "candles": candles}
    h = digest(artifact)
    provenance = {"model_revision": config.MODEL_REVISION, "quote": "USDT", "input_artifact_id": h}
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO artifacts VALUES(?,?,?)", (h, origin + 1, packed(artifact)))
    ids = {}
    for model, price in (("timesfm", 99), ("persistence", 100), ("momentum", 101)):
        path = [{"t": origin + (i + 1) * 3600, "p": price, "lo": 96, "hi": 104} for i in range(horizon)]
        ids[model] = store_forecast(
            "BTC",
            model,
            origin,
            horizon,
            100,
            path,
            {"news_available": False},
            provenance,
            1,
            issued_at=origin + 2,
        )
    if actual:
        target = origin + horizon * 3600
        store_candles("BTC", [[(target - 3600) * 1000, actual, actual, actual, actual, 1]], now)
    return ids["timesfm"]


def references(target, now, price=103, missing=False):
    rows = []
    for source, asset, close in (
        ("coinbase", "BTC", price),
        ("kraken", "BTC", price),
        ("coinbase", "USDT", 1),
    ):
        if missing and source == "kraken":
            continue
        h = digest([source, asset, target, close])
        rows.append((h, source, asset, target, close, now, h))
    with connect() as db:
        db.executemany("INSERT OR IGNORE INTO outcome_candles VALUES(?,?,?,?,?,?,?)", rows)


def test_protects_scores_and_artifacts_and_retains_source_revision(monkeypatch):
    origin = 1789635600
    target = origin + 86400
    monkeypatch.setattr(time, "time", lambda: target + 60)
    fid = parent(origin, actual=103, now=target + 10)
    evaluate()
    references(target, target + 30)
    assert outcomes.review()["reviews_added"] == 1
    assert outcomes.review()["reviews_added"] == 0
    with connect() as db:
        first = outcomes.latest_review(db, fid, target + 60)
        assert first["status"] == "qualified"
        for table in (
            "forecasts",
            "evaluations",
            "artifacts",
            "candle_revisions",
            "outcome_reviews",
            "outcome_candles",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                db.execute(f"DELETE FROM {table}")
    monkeypatch.setattr(time, "time", lambda: target + 120)
    store_candles("BTC", [[(target - 3600) * 1000, 107, 107, 107, 107, 1]], target + 100)
    assert evaluate()["evaluated"] == 0
    outcomes.review()
    with connect() as db:
        assert db.execute("SELECT actual FROM evaluations WHERE forecast_id=?", (fid,)).fetchone()[0] == 103
        assert outcomes.latest_review(db, fid, target + 120)["status"] == "source_revised"
        assert len(learning.training_rows(db, "BTC", 24, target + 90)) == 1
        assert learning.training_rows(db, "BTC", 24, target + 120) == []


def test_missing_reference_then_delayed_qualification_cannot_leak(monkeypatch):
    origin = 1789635600
    target = origin + 86400
    monkeypatch.setattr(time, "time", lambda: target + 60)
    fid = parent(origin, actual=103, now=target + 10)
    evaluate()
    references(target, target + 30, missing=True)
    outcomes.review()
    with connect() as db:
        assert outcomes.latest_review(db, fid, target + 60)["status"] == "reference_missing"
    monkeypatch.setattr(time, "time", lambda: target + 180)
    references(target, target + 150)
    outcomes.review()
    with connect() as db:
        assert learning.training_rows(db, "BTC", 24, target + 120) == []
        rows = learning.training_rows(db, "BTC", 24, target + 181)
        assert len(rows) == 1 and rows[0]["id"] == fid


def test_poisoned_reference_is_not_a_learning_label(monkeypatch):
    origin = 1789635600
    target = origin + 86400
    monkeypatch.setattr(time, "time", lambda: target + 60)
    fid = parent(origin, actual=103, now=target + 10)
    evaluate()
    references(target, target + 30, price=140)
    outcomes.review()
    with connect() as db:
        assert outcomes.latest_review(db, fid, target + 60)["status"] == "venue_divergence"
        assert learning.training_rows(db, "BTC", 24, target + 70) == []


def test_legacy_input_claim_remains_visible_but_is_not_certified(monkeypatch):
    origin = 1789635600
    target = origin + 86400
    monkeypatch.setattr(time, "time", lambda: target + 60)
    path = [{"t": origin + (i + 1) * 3600, "p": 99, "lo": 96, "hi": 104} for i in range(24)]
    provenance = {"model_revision": config.MODEL_REVISION, "quote": "USDT", "input_hash": "a" * 64}
    fid = store_forecast("BTC", "timesfm", origin, 24, 100, path, {}, provenance, 1, issued_at=origin + 2)
    store_candles("BTC", [[(target - 3600) * 1000, 103, 103, 103, 103, 1]], target + 10)
    evaluate()
    references(target, target + 30)
    outcomes.review()
    record = next(r for r in public_forecasts.snapshot()["records"] if r["id"] == fid)
    assert record["claim"]["input_hash"] == "a" * 64
    assert record["quality"]["status"] == "input_unverified"
    with connect() as db:
        assert learning.training_rows(db, "BTC", 24, target + 61) == []


def test_outcome_parser_rejects_open_nonfinite_and_invalid_bars():
    start = 1789635600
    good = [start, 90, 110, 100, 101, 1]
    rows = [
        good,
        [start + 3600, 90, 110, 100, 101, 1],
        [start - 3600, 90, 110, 100, float("nan"), 1],
        [start - 7200, 90, 99, 100, 101, 1],
    ]
    parsed = outcomes.normalize("coinbase", "BTC", rows, start + 3605, start - 10000)
    assert len(parsed) == 1 and parsed[0][3:5] == (start + 3600, 101)
    kraken = [[start, 100, 110, 90, 101, 100, 1, 12], [start + 3600, 100, 110, 90, 101, 100, 1, 12]]
    assert len(outcomes.normalize("kraken", "BTC", kraken, start + 3605, start - 10000)) == 1


def history_rows():
    return [
        {
            "id": digest([i]),
            "review_id": digest(["review", i]),
            "origin": 1780002000 + i * 21600,
            "target": 1780002000 + i * 21600 + 72 * 3600,
            "actual": 110 + i % 3,
            "prediction": 100,
        }
        for i in range(140)
    ]


def test_calibration_purges_overlap_and_keeps_exact_artifact_membership():
    rows = history_rows()
    assert learning.fit(rows[:100]) is None
    artifact = learning.fit(rows)
    lookup = {r["id"]: r for r in rows}
    assert max(lookup[x]["target"] for x in artifact["training_ids"]) < min(
        lookup[x]["origin"] for x in artifact["calibration_ids"]
    )
    expected = sum(math.log(lookup[x]["actual"] / 100) for x in artifact["training_ids"]) / (
        len(artifact["training_ids"]) + 24
    )
    assert artifact["bias"] == pytest.approx(expected)
    assert artifact["lower_residual"] <= 0 <= artifact["upper_residual"]
    assert set(artifact["training_ids"]).isdisjoint(artifact["calibration_ids"])


def test_shadow_issuance_is_versioned_current_only_and_idempotent(monkeypatch):
    now = 1789804800 + 90
    monkeypatch.setattr(time, "time", lambda: now)
    parent(now // 3600 * 3600)
    parent(now // 3600 * 3600 - 3600)
    monkeypatch.setattr(learning, "training_rows", lambda *args: history_rows())
    assert learning.generate() == {"forecasts_added": 1}
    assert learning.generate() == {"forecasts_added": 0}
    with connect() as db:
        records = db.execute("SELECT * FROM forecasts WHERE experiment=?", (learning.EXPERIMENT,)).fetchall()
        assert len(records) == 1 and records[0]["issued_at"] == now
        assert records[0]["model"] == "calibrated"
        artifact_id = json.loads(records[0]["provenance"])["artifact_id"]
        artifact = json.loads(
            db.execute("SELECT payload FROM artifacts WHERE id=?", (artifact_id,)).fetchone()[0]
        )
        assert digest(artifact) == artifact_id
        assert (
            db.execute("SELECT COUNT(*) FROM forecasts WHERE experiment=?", (config.EXPERIMENT,)).fetchone()[
                0
            ]
            == 6
        )


def test_public_record_waits_for_exact_outcome_and_preserves_endpoint(monkeypatch):
    origin = 1789635600
    target = origin + 86400
    monkeypatch.setattr(time, "time", lambda: target - 1)
    fid = parent(origin)
    with connect() as db:
        db.execute("INSERT INTO holdings VALUES('BTC',12345,1,?)", (target - 1,))
    before = public_forecasts.snapshot()
    r = next(r for r in before["records"] if r["id"] == fid)
    assert r["outcome"] is None
    assert "holdings" not in packed(before) and "12345" not in packed(before)
    monkeypatch.setattr(time, "time", lambda: target + 60)
    store_candles("BTC", [[(target - 3600) * 1000, 103, 103, 103, 103, 1]], target + 10)
    evaluate()
    r = next(r for r in public_forecasts.snapshot()["records"] if r["id"] == fid)
    assert r["outcome"]["actual"] == 103
    assert r["actual_path"][-1] == {"t": target, "p": 103}
    assert r["claim"]["prediction"] == 99


def test_publication_retries_only_unacknowledged_records(monkeypatch):
    now = 1789804800 + 90
    monkeypatch.setattr(time, "time", lambda: now)
    parent(now // 3600 * 3600)
    monkeypatch.setenv("ORACLE_LEARNING_ENABLED", "1")
    monkeypatch.setenv("ORACLE_PUBLIC_TOKEN", "local-test-only")

    class Response:
        status_code = 503

    sent = []

    def post(*args, **kwargs):
        sent.append(json.loads(kwargs["content"]))
        return Response()

    monkeypatch.setattr(public_forecasts.httpx, "post", post)
    with pytest.raises(RuntimeError, match="503"):
        public_forecasts.publish()
    Response.status_code = 200
    assert public_forecasts.publish()["updated"] == 1
    assert public_forecasts.publish()["updated"] == 0
    assert [len(s["records"]) for s in sent] == [1, 1, 0]


def test_review_waits_for_fixed_window_retains_missingness_and_never_promotes(monkeypatch):
    start = 1780002000 // 3600 * 3600
    due = start + 29 * 86400
    monkeypatch.setattr(time, "time", lambda: due - 1)
    for i in range(28):
        origin = start + i * 86400
        parent(origin, actual=103, now=origin + 86400 + 10)
        store_forecast(
            "BTC",
            "calibrated",
            origin,
            24,
            100,
            [{"t": origin + 86400, "p": 102, "lo": 98, "hi": 108}],
            {},
            {},
            1,
            issued_at=origin + 4,
            experiment=learning.EXPERIMENT,
        )
    evaluate()
    monkeypatch.setattr(
        outcomes, "latest_review", lambda db, fid, now: {"id": digest([fid]), "status": "qualified"}
    )
    learning.assess()
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM learning_reviews").fetchone()[0] == 0
    monkeypatch.setattr(time, "time", lambda: due + 1)
    learning.assess()
    learning.assess()
    with connect() as db:
        rows = db.execute("SELECT * FROM learning_reviews").fetchall()
        assert len(rows) == 1
        verdict = json.loads(rows[0]["payload"])
        assert verdict["n"] == 28
        assert verdict["availability"] == pytest.approx(28 / 672)
        assert verdict["status"] == "inconclusive" and verdict["auto_promoted"] is False
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE learning_reviews SET reviewed_at=0")
