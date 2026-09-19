import math
import sqlite3
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from oracle import config
from oracle.db import connect, init
from oracle.forecast import evaluate, history, metrics, news_features, store_forecast
from oracle.fusion import fit, training_rows
from oracle.ingest import store_candles
from oracle.web import app


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.sqlite3")
    monkeypatch.delenv("ORACLE_AUTH_PASSWORD", raising=False)
    init()


def candle(asset, timestamp, price=100):
    with connect() as db:
        db.execute(
            "INSERT INTO candles VALUES(?,?,?,?,?,?,?)",
            (asset, timestamp, price, 1, "test", int(time.time()), "hash"),
        )


def forecast(model="timesfm", origin=3600, horizon=24, prediction=110, scope="live", features=None):
    return store_forecast(
        "BTC",
        model,
        origin,
        horizon,
        100,
        [{"t": origin + horizon * 3600, "p": prediction, "lo": 90, "hi": 120}],
        features or {},
        {},
        1,
        scope,
        issued_at=origin + 60,
    )


def test_excludes_open_candles_and_normalizes_microseconds():
    base = 1780002000 // 3600 * 3600
    rows = [
        [base * 1000, 0, 0, 0, "101", "2"],
        [(base + 3600) * 1_000_000, 0, 0, 0, "102", "3"],
        [(base + 7200) * 1000, 0, 0, 0, "103", "4"],
    ]
    store_candles("BTC", rows, base + 7300)
    with connect() as db:
        assert [(r["ts"], r["close"]) for r in db.execute("SELECT * FROM candles ORDER BY ts")] == [
            (base + 3600, 101),
            (base + 7200, 102),
        ]
    rows[0][4] = "100.5"
    store_candles("BTC", rows[:1], base + 7400)
    with connect() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM candle_revisions WHERE ts=?", (base + 3600,)).fetchone()[0] == 2
        )


def test_history_rejects_gaps():
    for ts in (3600, 7200, 14400):
        candle("BTC", ts)
    with pytest.raises(ValueError, match="consecutive"):
        history("BTC", origin=14400, limit=3)


def test_forecasts_cannot_be_rewritten_or_deleted():
    ident = forecast()
    forecast(prediction=999)
    with connect() as db:
        assert db.execute("SELECT prediction FROM forecasts").fetchone()[0] == 110
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE forecasts SET prediction=99 WHERE id=?", (ident,))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM forecasts")


def test_evaluation_uses_exact_target_and_is_idempotent():
    forecast()
    candle("BTC", 3600 + 23 * 3600, 400)
    assert evaluate()["evaluated"] == 0
    candle("BTC", 3600 + 24 * 3600, 105)
    assert evaluate()["evaluated"] == 1
    assert evaluate()["evaluated"] == 0
    with connect() as db:
        r = db.execute("SELECT * FROM evaluations").fetchone()
        assert r["actual"] == 105
        assert r["absolute_log_error"] == pytest.approx(abs(math.log(110 / 105)))
        assert r["covered"] == 1


def test_comparison_uses_paired_origins_and_separate_scopes():
    forecast("timesfm", origin=3600, prediction=110)
    forecast("persistence", origin=3600, prediction=100)
    candle("BTC", 90000, 105)
    forecast("persistence", origin=7200, prediction=100)
    candle("BTC", 93600, 500)
    forecast("timesfm", origin=10800, prediction=100, scope="backtest")
    candle("BTC", 97200, 800)
    evaluate()
    result = next(r for r in metrics() if r["model"] == "timesfm")
    assert result["n"] == 1
    assert result["baseline_mae"] == pytest.approx(math.log(1.05))


def insert_news(
    ident, origin, *, seen=None, classified=None, url=None, title="Bitcoin upgrade", published=None
):
    with connect() as db:
        db.execute(
            "INSERT INTO news VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ident,
                "CoinDesk",
                url or "https://example.com/" + ident,
                title,
                published or origin - 60,
                seen or origin - 60,
                ident,
                title,
                "BTC",
                "Netzwerk",
                0.7,
                0.9,
                "test",
                classified or origin - 30,
            ),
        )


def test_news_features_cannot_see_future_ingestion_or_classification():
    origin = 200000
    insert_news("past", origin)
    insert_news("future-seen", origin, seen=origin + 1, title="Bitcoin market")
    insert_news("future-classified", origin, classified=origin + 1, title="Bitcoin hack")
    insert_news("repost", origin, url="https://example.com/past", title="Updated Bitcoin upgrade")
    insert_news("old", origin, published=origin - 2 * 86400, title="Bitcoin old news")
    features = news_features("BTC", origin)
    assert features["news_ids"] == ["past"]
    assert features["news_available"] is False
    with connect() as db:
        for source in config.FEEDS:
            for h in range(24):
                db.execute("INSERT INTO source_polls VALUES(?,?,1,1)", (source, origin - h * 3600 - 2))
    assert news_features("BTC", origin)["news_available"] is True
    with connect() as db:
        db.execute("INSERT INTO source_polls VALUES(?,?,0,0)", ("CoinDesk", origin - 1))
    assert news_features("BTC", origin)["news_available"] is False


def test_fusion_only_uses_matured_evidence_known_at_origin(monkeypatch):
    forecast(features={"news_available": True})
    candle("BTC", 90000, 105)
    monkeypatch.setattr("oracle.forecast.time.time", lambda: 100000)
    evaluate()
    assert training_rows("BTC", 24, 95000) == []
    assert len(training_rows("BTC", 24, 100001)) == 1


def test_fusion_fit_purges_overlapping_training_targets():
    rows = [
        {
            "id": str(i),
            "origin": i * 3600,
            "target": (i + 24) * 3600,
            "prediction": 100,
            "actual": 100 + i % 5,
            "features": {"x": float(i)},
        }
        for i in range(160)
    ]
    artifact = fit(rows, ("x",))
    assert artifact is not None
    latest_train = max(int(i) + 24 for i in artifact["training_ids"])
    first_calibration = min(int(i) for i in artifact["calibration_ids"])
    assert latest_train < first_calibration


def test_model_adapter_uses_log_prices_and_correct_quantile_channels(monkeypatch):
    from oracle import models

    class Model:
        def forecast(self, horizon, inputs):
            assert inputs[0][0] == pytest.approx(math.log(100))
            q = np.zeros((1, horizon, 10))
            q[:, :, 1], q[:, :, 5], q[:, :, 9] = math.log(90), math.log(105), math.log(120)
            return np.zeros((1, horizon)), q

    monkeypatch.setattr(models, "forecaster", lambda: Model())
    result, _ = models.predict([100] * 512, 24)
    assert result.shape == (24, 3)
    np.testing.assert_allclose(result[0], [90, 105, 120])


def test_holdings_validation_persistence_and_delete():
    with TestClient(app) as client:
        assert client.put("/api/holdings/BTC", json={"quantity": -1}).status_code == 422
        assert (
            client.put("/api/holdings/BTC", json={"quantity": 0.25, "average_cost": 50000}).status_code == 200
        )
        dashboard = client.get("/api/dashboard?asset=BTC&horizon=24&scope=live").json()
        assert dashboard["assets"][0]["holding"]["quantity"] == 0.25
        assert client.put("/api/holdings/OTHER", json={"quantity": 1}).status_code == 404
        assert client.delete("/api/holdings/BTC").status_code == 200
        assert client.get("/api/dashboard").json()["assets"][0]["holding"] is None


def test_server_auth_csrf_and_export(monkeypatch):
    monkeypatch.setenv("ORACLE_AUTH_PASSWORD", "test-password")
    forecast()
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/dashboard").status_code == 401
        assert client.get("/").status_code == 401
        auth = ("oracle", "test-password")
        assert client.get("/api/dashboard", auth=auth).status_code == 200
        assert (
            client.put(
                "/api/holdings/BTC",
                json={"quantity": 1},
                auth=auth,
                headers={"Origin": "https://evil.example"},
            ).status_code
            == 403
        )
        data = client.get("/api/export.csv", auth=auth)
        assert data.status_code == 200 and "timesfm" in data.text
        assert "forecast" not in client.get("/api/export.csv?scope=backtest", auth=auth).text.splitlines()[-1]


def test_empty_dashboard_and_fusion_are_honest():
    with TestClient(app) as client:
        result = client.get("/api/dashboard").json()
        assert result["forecasts"] == [] and result["metrics"] == []
        assert result["fusion"]["samples"] == 0
        assert result["assets"][0]["price"] is None
        assert client.get("/api/dashboard?asset=FAKE").status_code == 422
        assert client.get("/api/dashboard?horizon=72").status_code == 200
        assert client.get("/api/dashboard?horizon=25").status_code == 422


def test_news_list_filters_asset_before_limiting():
    now = int(time.time())
    insert_news("bitcoin", now - 10, title="Bitcoin news")
    with connect() as db:
        for i in range(210):
            db.execute(
                "INSERT INTO news(id,source,url,title,first_seen,content_hash,cluster,assets,event_type) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    str(i),
                    "Ethereum Blog",
                    f"https://example.com/{i}",
                    "Ethereum post",
                    now,
                    str(i),
                    str(i),
                    "ETH",
                    "Netzwerk",
                ),
            )
    with TestClient(app) as client:
        result = client.get("/api/dashboard?asset=BTC&horizon=24").json()
        assert result["news"][0]["id"] == "bitcoin"


def test_block_bootstrap_reports_uncertainty_without_fabricating_small_sample_evidence():
    from oracle.report import block_interval

    assert block_interval([[1, 2]] * 20) is None
    assert block_interval([[1, 2]] * 100) == pytest.approx([0.5, 0.5])


def test_shadow_fusion_emits_both_models_only_after_mature_history():
    from oracle.fusion import generate_fusion

    now = int(time.time())
    features = {
        "news_available": True,
        "model_return": 0.01,
        "return_24h": 0.005,
        "volatility_24h": 0.003,
        "news_count": 1,
        "sentiment": 0.5,
        "negative_count": 0,
        "news_ids": ["latest"],
    }
    path = [{"t": now + (i + 1) * 3600, "p": 101} for i in range(24)]
    generate_fusion("BTC", now + 10, 24, 100, path, features, {})
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0] == 0
    for i in range(160):
        origin = now - (163 - i) * 86400
        forecast(
            origin=origin,
            prediction=101,
            features={**features, "sentiment": (i % 3 - 1) * 0.5, "news_ids": [str(i)]},
        )
        candle("BTC", origin + 86400, 101 + (i % 3 - 1))
    evaluate()
    generate_fusion("BTC", now + 10, 24, 100, path, features, {})
    with connect() as db:
        rows = db.execute("SELECT * FROM forecasts WHERE model LIKE 'fusion_%'").fetchall()
        assert {r["model"] for r in rows} == {"fusion_market", "fusion_news"}
        assert all(r["lower"] <= r["upper"] and r["prediction"] > 0 for r in rows)


def test_news_ui_shows_latest_version_but_preserves_history():
    now = int(time.time())
    insert_news("old", now - 10, url="https://example.com/story", title="Bitcoin original headline")
    insert_news("new", now, url="https://example.com/story", title="Bitcoin corrected headline")
    with TestClient(app) as client:
        news = client.get("/api/dashboard?asset=BTC&horizon=24").json()["news"]
        assert len(news) == 1 and news[0]["id"] == "new"
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM news").fetchone()[0] == 2
