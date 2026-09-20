import json
import time
from datetime import UTC, datetime

import httpx
import pytest

from oracle import config, newsletter, paper, volband
from oracle.db import connect, digest, init, packed
from oracle.forecast import evaluate, store_forecast
from oracle.ingest import store_candles
from oracle.jev import VERSION

MONDAY = int(datetime(2026, 9, 21, tzinfo=UTC).timestamp())  # end of ISO week 2026-W38
START = MONDAY - 7 * 86400
NOW = MONDAY + 8 * 3600


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "newsletter.sqlite3")
    monkeypatch.setenv("ORACLE_NEWSLETTER_ENABLED", "1")
    monkeypatch.setenv("ORACLE_PUBLIC_TOKEN", "test-token")
    init()
    paper.init_schema()


def candle(asset, ts, close):
    store_candles(asset, [[(ts - 3600) * 1000, close, close, close, close, 1]], ts + 60)


def headline(title, seen, answers, cluster=None, url=None, evaluated=None):
    ident = digest([title, seen])
    full = {a: {"probability": 0.0} for a in config.ASSETS} | {
        "material": {"probability": 0.9},
        "tone": {"choice": "negative"},
        "event": {"choice": "security"},
    }
    full.update(answers)
    with connect() as db:
        db.execute(
            "INSERT INTO news(id,source,url,title,published_at,first_seen,content_hash,cluster,assets,event_type) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                ident,
                "CoinDesk",
                url or f"https://www.coindesk.com/{ident[:8]}",
                title,
                seen - 60,
                seen,
                ident,
                cluster or ident,
                "BTC",
                "Markt",
            ),
        )
        db.execute(
            "INSERT INTO news_evaluations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                digest([ident, VERSION]),
                ident,
                "typesafe-ai/jev",
                VERSION,
                evaluated or seen + 30,
                ident,
                "{}",
                packed(full),
                "{}",
                1.0,
                "ai",
            ),
        )


def test_week_is_the_last_completed_iso_week():
    assert newsletter.week(NOW) == (START, MONDAY, "2026-W38")
    assert newsletter.week(MONDAY - 1) == (START - 7 * 86400, START, "2026-W37")
    assert datetime.fromtimestamp(START, UTC).weekday() == 0


def test_market_uses_only_closes_inside_the_week():
    for ts, close in (
        (START - 3600, 50),
        (START, 100),
        (START + 86400, 80),
        (MONDAY, 110),
        (MONDAY + 3600, 500),
    ):
        candle("BTC", ts, close)
    with connect() as db:
        (btc,) = newsletter.market(db, START, MONDAY)
    assert btc == {
        "asset": "BTC",
        "close": 110,
        "change": pytest.approx(0.1),
        "low": 80,
        "high": 110,
        "change_30d": None,
        "swing": pytest.approx(0.3889, abs=1e-4),
        "largest_move": None,  # the three closes are days apart; a gap is not an hourly move
        "calmer_weeks": 0,
        "compared_weeks": 0,
    }


def test_market_context_ranks_the_week_against_complete_earlier_weeks_only():
    # Two complete earlier weeks: a flat one and a wild one. A third has holes and must not be compared.
    for k, step in ((1, 0.0), (2, 0.05), (3, 0.05)):
        for h in range(169):
            if k == 3 and h % 2:
                continue
            candle("BTC", START - k * 7 * 86400 + h * 3600, 100 * (1 + step * (h % 2)))
    for h in range(169):
        candle("BTC", START + h * 3600, 100 * (1 + 0.01 * (h % 2)) if h != 50 else 90)
    candle("BTC", MONDAY - 30 * 86400, 80)
    with connect() as db:
        (btc,) = newsletter.market(db, START, MONDAY)
    assert btc["compared_weeks"] == 2 and btc["calmer_weeks"] == 1
    assert btc["change_30d"] == pytest.approx(100 / 80 - 1)
    assert btc["largest_move"] == {"at": START + 51 * 3600, "change": pytest.approx(101 / 90 - 1)}


def band_forecast(model, origin, horizon, lower, upper):
    path = [{"t": origin + horizon * 3600, "p": 100, "lo": lower, "hi": upper}]
    return store_forecast(
        "BTC",
        model,
        origin,
        horizon,
        100,
        path,
        {},
        {},
        0,
        issued_at=origin + 60,
        experiment=volband.EXPERIMENT,
    )


def test_outlook_quotes_only_claims_that_are_already_frozen_and_still_open():
    origin = NOW - 2 * 3600
    path = [{"t": origin + 86400, "p": 103, "lo": 98, "hi": 107}]
    ident = store_forecast("BTC", "timesfm", origin, 24, 100, path, {}, {}, 1, issued_at=origin + 60)
    band_forecast("volband", origin, 24, 96, 104)
    # Neither an expired claim nor one from the future may appear.
    store_forecast("ETH", "timesfm", NOW - 30 * 3600, 24, 100, path, {}, {}, 1, issued_at=NOW - 30 * 3600)
    store_forecast("SOL", "timesfm", NOW + 3600, 24, 100, path, {}, {}, 1, issued_at=NOW + 3600)
    day = int(NOW // 86400) * 86400
    for days, close in ((0, 100), (7, 90), (14, 95), (28, 120), (56, 80)):
        candle("BTC", day - days * 86400, close)
    with connect() as db:
        (btc,) = newsletter.outlook(db, NOW)
    assert btc == {
        "asset": "BTC",
        "id": ident,
        "origin": origin,
        "target": origin + 86400,
        "base": 100,
        "predicted": pytest.approx(0.03),
        "model_band": [pytest.approx(-0.02), pytest.approx(0.07)],
        "volatility_band": [pytest.approx(-0.04), pytest.approx(0.04)],
        "trend_positive": 3,
    }


def test_band_standings_pair_both_bands_on_the_same_outcome(monkeypatch):
    for k, actual in enumerate((101, 109)):
        origin = START + (k + 1) * 86400
        candle("BTC", origin + 4 * 3600, actual)
        band_forecast("volband", origin, 4, 95, 105)
        band_forecast("timesfm_path", origin, 4, 99, 102)
    band_forecast("volband", START + 3 * 86400, 4, 95, 105)  # no partner, no outcome: not counted
    monkeypatch.setattr(time, "time", lambda: MONDAY - 3600)
    evaluate()
    with connect() as db:
        (row,) = newsletter.bands(db, START, MONDAY)
    assert (row["horizon"], row["n"], row["days"]) == (4, 2, 2)
    assert row["volatility_band"]["inside"] == 1 and row["model_band"]["inside"] == 1
    assert row["volatility_band"]["score"] > 0 and row["model_band"]["score"] > 0


def test_forecast_scoreboard_pairs_the_model_with_the_last_price(monkeypatch):
    origin = START + 3 * 3600
    candle("BTC", origin + 86400, 110)
    path = [{"t": origin + 86400, "p": 104, "lo": 100, "hi": 108}]
    store_forecast("BTC", "timesfm", origin, 24, 100, path, {}, {}, 1, issued_at=origin + 60)
    store_forecast(
        "BTC",
        "persistence",
        origin,
        24,
        100,
        [{"t": origin + 86400, "p": 100}],
        {},
        {},
        0,
        issued_at=origin + 60,
    )
    monkeypatch.setattr(time, "time", lambda: origin + 86400 + 600)
    evaluate()
    with connect() as db:
        board = newsletter.forecasts(db, START, MONDAY)
    (btc,) = board["assets"]
    assert board["issued"] == 1 and btc["scored"] == 1 and btc["inside_band"] == 0 and btc["days"] == 1
    assert btc["miss"] < btc["last_price_miss"]
    assert btc["best"]["predicted"] == pytest.approx(0.04) and btc["worst"]["actual"] == pytest.approx(0.1)


def test_news_needs_relevance_materiality_and_in_week_classification():
    headline("Exchange hacked, Bitcoin stolen", START + 100, {"BTC": {"probability": 0.95}})
    headline(
        "Exchange hacked: Bitcoin stolen (syndicated)",
        START + 200,
        {"BTC": {"probability": 0.95}},
        cluster=digest(["Exchange hacked, Bitcoin stolen", START + 100]),
    )
    headline(
        "Ten coins to buy now", START + 300, {"BTC": {"probability": 0.9}, "material": {"probability": 0.2}}
    )
    headline("Unrelated sports result", START + 400, {})
    headline("Seen after the week ended", MONDAY + 100, {"ETH": {"probability": 0.9}})
    headline(
        "Classified only after the week", MONDAY - 100, {"SOL": {"probability": 0.9}}, evaluated=MONDAY + 50
    )
    with connect() as db:
        result = newsletter.news(db, START, MONDAY)
    assert [x["title"] for x in result["items"]] == ["Exchange hacked, Bitcoin stolen"]
    assert result["items"][0]["assets"] == ["BTC"] and "material" not in result["items"][0]
    assert result["collected"] == 5 and result["classified"] == 4
    # Three distinct stories were classified in the week; the syndicated copy does not count twice.
    assert result["mix"] == {"events": {"security": 3}, "tones": {"negative": 3}}


def test_changes_come_from_the_shipped_list_and_only_from_this_week(tmp_path, monkeypatch):
    entries = [
        {"date": "2026-09-13", "title": "old", "summary": "s", "url": "https://example.org/"},
        {"date": "2026-09-19", "title": "new", "summary": "s", "url": "https://example.org/"},
        {"date": "2026-09-21", "title": "next week", "summary": "s", "url": "https://example.org/"},
    ]
    path = tmp_path / "changes.json"
    path.write_text(json.dumps(entries))
    monkeypatch.setattr(newsletter, "CHANGES", path)
    assert [e["title"] for e in newsletter.changes(START, MONDAY)] == ["new"]
    shipped = json.loads(newsletter.CHANGES.read_text())
    assert all(set(e) == {"date", "title", "summary", "url"} for e in shipped)


def test_issue_is_published_once_after_monday_morning_and_never_without_the_flag(monkeypatch):
    for asset in config.ASSETS:
        candle(asset, START, 100)
        candle(asset, MONDAY, 105)
    sent = []

    def post(url, content, timeout, headers):
        sent.append((url, json.loads(content), headers["Authorization"]))
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "post", post)
    assert newsletter.publish(MONDAY + 3600) == {"state": "waiting", "issue": "2026-W38"} and not sent
    assert newsletter.publish(NOW)["state"] == "published" and len(sent) == 1
    url, issue, auth = sent[0]
    assert url.endswith("/api/newsletter/issue") and auth == "Bearer test-token"
    assert issue["id"] == "2026-W38" and len(issue["market"]) == 3 and issue["generated_at"] == NOW
    assert issue["schema"] == 2 and issue["outlook"] == [] and issue["bands"] == []
    assert issue["explainer"] == json.loads(newsletter.EXPLAINERS.read_text())[38 % 8]
    assert "subscriber" not in json.dumps(issue) and "@" not in json.dumps(issue)
    assert newsletter.publish(NOW + 3600) == {"state": "published", "issue": "2026-W38"} and len(sent) == 1
    monkeypatch.setenv("ORACLE_NEWSLETTER_ENABLED", "0")
    assert newsletter.publish(NOW + 8 * 86400) == {"state": "disabled"}


def test_rejected_issue_is_retried_and_published_issues_are_immutable(monkeypatch):
    for asset in config.ASSETS:
        candle(asset, START, 100)
        candle(asset, MONDAY, 105)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(409))
    with pytest.raises(RuntimeError, match="rejected"):
        newsletter.publish(NOW)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200))
    assert newsletter.publish(NOW)["state"] == "published"
    with connect() as db, pytest.raises(Exception, match="immutable"):
        db.execute("DELETE FROM newsletter_issues")


def test_worker_cycle_runs_the_weekly_digest_after_the_publications(monkeypatch):
    from oracle import runner

    seen = []
    monkeypatch.setattr(runner, "task", lambda name, fn: seen.append(name) or True)
    monkeypatch.setattr(runner, "job_start", lambda name: None)
    monkeypatch.setattr(runner, "job_end", lambda *a, **k: None)
    runner.cycle()
    assert seen[-1] == "newsletter" and seen.index("forecast-publication") < seen.index("newsletter")


def test_shipped_explainers_fit_the_public_boundary():
    entries = json.loads(newsletter.EXPLAINERS.read_text())
    assert len(entries) >= 8 and len({e["title"] for e in entries}) == len(entries)
    for e in entries:
        assert set(e) == {"title", "text", "url"} and len(e["title"]) <= 120 and len(e["text"]) <= 600
        assert e["url"].startswith("https://cryptooracle.moinsen.dev/")


def test_operator_preview_is_rolling_and_never_recorded(monkeypatch):
    now = NOW + 2 * 86400 + 1234
    hour = int(now // 3600) * 3600
    for asset in config.ASSETS:
        candle(asset, hour - 7 * 86400, 100)
        candle(asset, hour, 95)
    sent = []

    def post(url, content, timeout, headers):
        sent.append((url, json.loads(content)))
        return httpx.Response(200, json={"status": "previewed"})

    monkeypatch.setattr(httpx, "post", post)
    assert newsletter.preview(now) == {"state": "previewed", "issue": "preview-2026-09-23"}
    url, issue = sent[0]
    assert url.endswith("/api/newsletter/preview")
    assert (issue["start"], issue["end"]) == (hour - 7 * 86400, hour) and issue["market"][0]["change"] < 0
    newsletter.init_schema()
    with connect() as db:
        assert db.execute("SELECT COUNT(*) FROM newsletter_issues").fetchone()[0] == 0
    # The preview does not consume the week: the regular issue is still built and published afterwards.
    for asset in config.ASSETS:
        candle(asset, START, 100)
        candle(asset, MONDAY, 105)
    assert newsletter.publish(now)["state"] == "published" and sent[-1][0].endswith("/api/newsletter/issue")


def test_portfolios_count_every_fill_and_pass_on_only_the_latest(monkeypatch):
    from tests.test_paper_trend import closes, run

    monkeypatch.setenv("ORACLE_PAPER_ENABLED", "1")
    monkeypatch.setenv("ORACLE_PAPER_V3_ENABLED", "1")
    closes({0: 100, 7: 90, 14: 90, 28: 110, 56: 95}, day=START + 86400)
    run(START + 86400 + 1800)
    with connect() as db:
        (v3,) = newsletter.portfolios(db, START, MONDAY)
    assert v3["run"] == paper.RUN_V3 and v3["fills"] == 9 and len(v3["trades"]) == 9
    monkeypatch.setattr(newsletter, "TRADES", 4)
    with connect() as db:
        (v3,) = newsletter.portfolios(db, START, MONDAY)
    assert v3["fills"] == 9 and len(v3["trades"]) == 4
    assert {t["reason"] for t in v3["trades"]} <= {"trend_up", "reference_entry"}
