import copy
import json
import os
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from oracle import config, laya_news
from oracle.db import connect, digest, init
from oracle.web import app


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.sqlite3")
    monkeypatch.setenv("ORACLE_LAYA_ENABLED", "1")
    monkeypatch.delenv("ORACLE_AUTH_PASSWORD", raising=False)
    init()


def article(ident="n1", age=60, assets="BTC", url=None, published=True, title="A headline"):
    now = int(time.time())
    with connect() as db:
        db.execute(
            "INSERT INTO news(id,source,url,title,published_at,first_seen,content_hash,cluster,"
            "assets,event_type,sentiment,classified_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ident,
                "test",
                url or "https://example.com/" + ident,
                title,
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


def result():
    """Raw output in the shape laya 0.3.20 returns."""
    answers = {}
    for name, q in laya_news.LAYA_QUESTIONS.items():
        if q["type"] == "noul":
            answers[name] = {"type": "noul", "noul": 0.9, "confidence": 0.9, "answer_confidence": 0.9}
        else:
            labels = list(q["criteria"])
            probs = {label: round(0.5 / (len(labels) - 1), 4) for label in labels}
            probs[labels[0]] = round(1 - sum(probs[label] for label in labels[1:]), 4)
            answers[name] = {"type": "choice", "choice": labels[0], "probabilities": probs}
    return {"model": "laya-rl-agent", "answers": answers, "usage": {"input_tokens": 63, "output_tokens": 0}}


class FakeAgent:
    def __init__(self, fail_on=()):
        self.calls, self.fail_on = [], set(fail_on)

    def predict(self, state, questions):
        self.calls.append((state, questions))
        if state in self.fail_on:
            raise RuntimeError("model failure")
        return result()


def use(monkeypatch, fake):
    monkeypatch.setattr(laya_news, "agent", lambda: fake)
    return fake


def test_collect_is_idempotent_preserves_finbert_and_records_time(monkeypatch):
    article(title="Bitcoin tops $77,000")
    fake = use(monkeypatch, FakeAgent())
    before = int(time.time())
    assert laya_news.collect()["classified"] == 1
    assert laya_news.collect()["classified"] == 0
    assert fake.calls == [("Bitcoin tops $77,000", laya_news.LAYA_QUESTIONS)]
    with connect() as db:
        record = db.execute("SELECT * FROM news_evaluations").fetchone()
        assert record["model"] == laya_news.MODEL and laya_news.REVISION in record["model"]
        assert record["version"] == laya_news.VERSION and record["sdk"] == "laya==0.3.20"
        assert record["evaluated_at"] >= before
        assert record["input_hash"] == digest(json.loads(record["input"]))
        answers = json.loads(record["answers"])
        assert answers["BTC"] == {"type": "boolean", "probability": 0.9}
        assert answers["tone"]["choice"] == "positive"
        assert json.loads(record["response"])["answers"]["BTC"]["noul"] == 0.9
        assert db.execute("SELECT sentiment FROM news").fetchone()[0] == 0.25
        assert db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE news_evaluations SET evaluated_at=0")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM news_evaluations")


def test_only_recent_dated_latest_versions_are_sent(monkeypatch):
    article("old", age=90000)
    article("undated", published=False)
    article("future", age=-100)
    article("v1", age=100, url="https://example.com/shared")
    article("v2", age=50, url="https://example.com/shared")
    use(monkeypatch, FakeAgent())
    assert laya_news.collect()["classified"] == 1
    with connect() as db:
        assert db.execute("SELECT news_id FROM news_evaluations").fetchone()[0] == "v2"


def test_disabled_or_empty_never_loads_the_model(monkeypatch):
    def forbidden():
        pytest.fail("model loaded")

    monkeypatch.setattr(laya_news, "agent", forbidden)
    assert laya_news.collect()["classified"] == 0
    article()
    monkeypatch.setenv("ORACLE_LAYA_ENABLED", "0")
    assert laya_news.collect()["state"] == "disabled"


def test_failed_headline_stays_missing_and_the_job_reports_it(monkeypatch):
    article("bad", age=50, title="breaks the model")
    article("good", age=60, title="fine")
    use(monkeypatch, FakeAgent(fail_on={"breaks the model"}))
    with pytest.raises(RuntimeError, match="1 of 2 headlines"):
        laya_news.collect()
    with connect() as db:
        assert [r[0] for r in db.execute("SELECT news_id FROM news_evaluations")] == ["good"]


def test_rejects_nonfinite_incomplete_and_unexpected_answers():
    for mutate in [
        lambda r: r["answers"].pop("BTC"),
        lambda r: r["answers"]["BTC"].update(noul=float("nan")),
        lambda r: r["answers"]["BTC"].update(noul=True),
        lambda r: r["answers"]["BTC"].update(noul=1.5),
        lambda r: r["answers"]["BTC"].update(type="choice"),
        lambda r: r["answers"]["tone"].update(choice="invented"),
        lambda r: r["answers"]["tone"]["probabilities"].pop("neutral"),
        lambda r: r["answers"]["tone"]["probabilities"].update(neutral=0.4),
        lambda r: r.update(usage={"input_tokens": float("inf")}),
    ]:
        r = copy.deepcopy(result())
        mutate(r)
        with pytest.raises(ValueError):
            laya_news.normalize(r)
    assert set(laya_news.normalize(result())) == set(laya_news.QUESTIONS)


def test_checkpoint_digest_mismatch_refuses_the_load(tmp_path, monkeypatch):
    for name in laya_news.DIGESTS:
        (tmp_path / "snap" / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "snap" / name).write_bytes(b"tampered")
    requested = {}

    def download(repo, revision, allow_patterns):
        requested.update(repo=repo, revision=revision, files=allow_patterns)
        return str(tmp_path / "snap")

    import huggingface_hub
    import laya

    monkeypatch.setattr(huggingface_hub, "snapshot_download", download)
    monkeypatch.setattr(laya, "Agent", lambda *a, **k: pytest.fail("weights parsed before verification"))
    laya_news.agent.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="digest mismatch"):
            laya_news.agent()
    finally:
        laya_news.agent.cache_clear()
    assert requested == {"repo": laya_news.REPO, "revision": laya_news.REVISION, "files": list(laya_news.DIGESTS)}


def test_version_pins_package_revision_questions_and_input():
    import laya

    assert laya_news.VERSION.startswith("laya-headlines-v1-")
    assert laya_news.PACKAGE == "laya==" + laya.__version__
    # Same questions as the JEV version; only the name of the yes/no type differs.
    assert {k: q["type"] for k, q in laya_news.QUESTIONS.items()} == {
        "BTC": "boolean", "ETH": "boolean", "SOL": "boolean", "material": "boolean",
        "tone": "choice", "event": "choice",
    }
    assert all(q["type"] in ("noul", "choice") for q in laya_news.LAYA_QUESTIONS.values())


def test_news_ui_shows_laya_asset_match_and_keeps_finbert_separate(monkeypatch):
    article(assets="")
    use(monkeypatch, FakeAgent())
    laya_news.collect()
    with TestClient(app) as client:
        data = client.get("/api/dashboard?asset=SOL").json()
    assert len(data["news"]) == 1
    assert data["news"][0]["laya"]["answers"]["SOL"]["probability"] == 0.9
    assert data["news"][0]["sentiment"] == 0.25
    assert data["laya"]["evaluated"] == 1
    assert data["laya"]["version"] == laya_news.VERSION


@pytest.mark.skipif(os.getenv("ORACLE_LAYA_REAL") != "1", reason="set ORACLE_LAYA_REAL=1 to load the checkpoint")
def test_real_checkpoint_answers_in_the_stored_schema():
    laya_news.agent.cache_clear()
    raw = laya_news.agent().predict("Bitcoin ETF flows turn positive for 2026", laya_news.LAYA_QUESTIONS)
    answers = laya_news.normalize(raw)
    assert set(answers) == set(laya_news.QUESTIONS)
    assert answers["tone"]["choice"] in laya_news.QUESTIONS["tone"]["criteria"]
