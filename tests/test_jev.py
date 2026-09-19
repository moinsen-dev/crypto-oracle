import copy
import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from oracle import config, jev
from oracle.db import connect, init
from oracle.web import app


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.sqlite3")
    monkeypatch.setenv("ORACLE_JEV_ENABLED", "1")
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "test-key-never-used")
    monkeypatch.setenv("ORACLE_JEV_DAILY_REQUESTS", "200")
    monkeypatch.delenv("ORACLE_AUTH_PASSWORD", raising=False)
    init()


def article(ident="n1", age=60, assets="BTC", url=None, published=True):
    now = int(time.time())
    with connect() as db:
        db.execute(
            "INSERT INTO news(id,source,url,title,published_at,first_seen,content_hash,cluster,"
            "assets,event_type,sentiment,classified_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ident,
                "test",
                url or "https://example.com/" + ident,
                "A headline",
                now - age if published else None,
                now - age,
                ident,
                ident,
                assets,
                "Sonstiges",
                0.25,
                now - age,
            ),
        )


def response():
    answers = {}
    for name, q in jev.QUESTIONS.items():
        answers[name] = (
            {"type": "boolean", "probability": 0.9}
            if q["type"] == "boolean"
            else {"type": "choice", "choice": next(iter(q["criteria"]))}
        )
    return {"answers": answers, "usage": {"inputTokens": 790}, "sdk": jev.SDK}


def test_collect_is_idempotent_preserves_finbert_and_records_time(monkeypatch):
    article()
    calls = []

    def invoke(payload):
        calls.append(payload)
        return response()

    monkeypatch.setattr(jev, "invoke", invoke)
    assert jev.collect()["classified"] == 1
    assert jev.collect()["classified"] == 0
    assert len(calls) == 1
    assert set(calls[0]["state"]) == {"task", "headline", "source", "published_at"}
    with connect() as db:
        record = db.execute("SELECT * FROM news_evaluations").fetchone()
        assert record["input_hash"] == jev.digest(calls[0])
        assert db.execute("SELECT sentiment FROM news").fetchone()[0] == 0.25
        assert db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE news_evaluations SET evaluated_at=0")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM news_evaluations")
    assert not jev.annotations_at(record["evaluated_at"] - 1)
    assert len(jev.annotations_at(record["evaluated_at"])) == 1


def test_error_consumes_quota_is_sanitized_and_stops_batch(monkeypatch):
    article()
    article("n2")
    monkeypatch.setenv("ORACLE_JEV_DAILY_REQUESTS", "1")

    def fail(payload):
        raise RuntimeError("SECRET provider text")

    monkeypatch.setattr(jev, "invoke", fail)
    with pytest.raises(RuntimeError, match="request_failed") as error:
        jev.collect()
    assert "SECRET" not in str(error.value)
    assert jev.collect()["state"] == "request_limit"
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM news_evaluations").fetchone()[0] == 0
        assert db.execute("SELECT error FROM jev_attempts").fetchone()[0] == "request_failed"


def test_only_recent_dated_latest_versions_are_sent(monkeypatch):
    article("old", age=90000)
    article("undated", published=False)
    article("future", age=-100)
    article("v1", age=100, url="https://example.com/shared")
    article("v2", age=50, url="https://example.com/shared")
    monkeypatch.setattr(jev, "invoke", lambda p: response())
    assert jev.collect()["classified"] == 1
    with connect() as db:
        assert db.execute("SELECT news_id FROM news_evaluations").fetchone()[0] == "v2"


def test_missing_key_and_disabled_never_call_provider(monkeypatch):
    monkeypatch.setattr(jev, "invoke", lambda p: pytest.fail("unexpected request"))
    monkeypatch.delenv("AI_GATEWAY_API_KEY")
    assert jev.collect()["state"] == "missing_key"
    monkeypatch.setenv("ORACLE_JEV_ENABLED", "0")
    assert jev.collect()["state"] == "disabled"


def test_rejects_nonfinite_incomplete_and_unexpected_answers():
    for mutate in [
        lambda r: r["answers"].pop("BTC"),
        lambda r: r["answers"]["BTC"].update(probability=float("nan")),
        lambda r: r["answers"]["BTC"].update(probability=True),
        lambda r: r["answers"]["tone"].update(choice="invented"),
    ]:
        r = copy.deepcopy(response())
        mutate(r)
        with pytest.raises(ValueError):
            jev.validate(r)
    r = response()
    r["answers"]["tone"]["probabilities"] = {k: 0 for k in jev.QUESTIONS["tone"]["criteria"]}
    with pytest.raises(ValueError, match="sum"):
        jev.validate(r)


def test_news_ui_can_include_jev_asset_match_and_keeps_status_separate(monkeypatch):
    article(assets="")
    monkeypatch.setattr(jev, "invoke", lambda p: response())
    jev.collect()
    with TestClient(app) as client:
        data = client.get("/api/dashboard?asset=SOL").json()
    assert len(data["news"]) == 1
    assert data["news"][0]["jev"]["answers"]["SOL"]["probability"] == 0.9
    assert data["news"][0]["sentiment"] == 0.25
    assert data["jev"]["evaluated"] == 1
    assert data["jev"]["input_tokens"] == 790
    assert "test-key" not in json.dumps(data)


def test_provider_rate_limit_persists_across_calls_and_retries_later(monkeypatch):
    article()

    def limited(payload):
        raise jev.RateLimited(3600)

    monkeypatch.setattr(jev, "invoke", limited)
    result = jev.collect()
    assert result["state"] == "rate_limited"
    assert result["retry_at"] >= int(time.time()) + 3599
    monkeypatch.setattr(jev, "invoke", lambda p: pytest.fail("cooldown ignored"))
    assert jev.collect()["state"] == "rate_limited"
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM jev_attempts").fetchone()[0] == 1
        db.execute("UPDATE jev_backoff SET retry_at=0")
    monkeypatch.setattr(jev, "invoke", lambda p: response())
    assert jev.collect()["classified"] == 1
