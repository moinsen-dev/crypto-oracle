import copy
import json
import sqlite3

import pytest

from oracle import config, market, paper
from oracle.db import connect, digest, init, packed
from oracle.forecast import store_forecast

NOW = 1789733100.0


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.sqlite3")
    monkeypatch.setenv("ORACLE_PAPER_ENABLED", "1")
    monkeypatch.delenv("ORACLE_PAPER_V2_ENABLED", raising=False)
    monkeypatch.delenv("ORACLE_PUBLIC_TOKEN", raising=False)
    init()
    paper.init_schema()


def snapshot(at=NOW, price=100.0, depth=1000):
    books = {}
    for asset in (*config.ASSETS, "USDT"):
        p = 1.0 if asset == "USDT" else price
        for venue in ("coinbase", "kraken", "binance"):
            books[f"{venue}:{asset}"] = {
                "venue": venue,
                "asset": asset,
                "started_at": at - 0.2,
                "received_at": at,
                "source_at": at - 0.1,
                "bids": [[p * 0.9999, depth]],
                "asks": [[p * 1.0001, depth]],
                "error": None,
                "payload_hash": "b" * 64,
            }
    value = {"started_at": at - 0.3, "received_at": at, "books": books}
    return {"id": digest(value), **value}


def forecasts(at=NOW, prediction=104, bad_input=False):
    origin = int(at // 3600) * 3600
    for asset in config.ASSETS:
        candles = [
            {"ts": origin - (511 - i) * 3600, "observed_at": at - 60, "close": 100.0, "volume": 10.0}
            for i in range(512)
        ]
        if bad_input:
            candles[-1]["observed_at"] = at + 60
        inputs = {"kind": "input-candles-v1", "asset": asset, "candles": candles}
        ident = digest(inputs)
        with connect() as db:
            db.execute("INSERT INTO artifacts VALUES(?,?,?)", (ident, at - 60, packed(inputs)))
        store_forecast(
            asset,
            "timesfm",
            origin,
            24,
            100,
            [{"t": origin + 86400, "p": prediction, "lo": prediction - 2, "hi": prediction + 2}],
            {"volatility_24h": 0.002},
            {"input_artifact_id": ident, "model_revision": config.MODEL_REVISION, "quote": "USDT"},
            1,
            issued_at=int(at - 30),
        )


def run(at=NOW, price=100, depth=1000):
    current = [at]

    def collect():
        current[0] += 1
        return snapshot(current[0], price, depth)

    return paper.cycle(collect, lambda: current[0] + 0.01)


def ledger():
    with connect() as db:
        return paper.events(db)


def test_cash_positions_and_restart_are_consistent_and_no_double_deposit():
    forecasts()
    run()
    rows = ledger()
    state = paper.balance(rows, "news-guarded")
    assert state["fills"] == 3
    assert 0 < state["fees"] < 2
    assert state["cash"] > 8500
    value = sum(p["quantity"] * 100 for p in state["positions"].values())
    assert state["cash"] + value < 10000
    run()
    assert len(ledger()) == len(rows)
    assert paper.verify_chain(ledger()) == rows[-1]["hash"]
    assert sum(r["kind"] == "deposit" for r in rows) == 3
    assert all(r["payload"]["observed_at"] > r["ts"] - 0.1 for r in rows if r["kind"] == "fill")
    with connect() as db:
        for sql in ("UPDATE paper_events SET ts=0", "DELETE FROM paper_events"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                db.execute(sql)


def test_sell_uses_later_bid_and_preserves_accounting():
    forecasts()
    run()
    before = paper.balance(ledger(), "news-guarded")
    # Risk-reducing stop bypasses the normal six-hour cooldown, with a new valid quote.
    run(NOW + 3600, price=90)
    after = paper.balance(ledger(), "news-guarded")
    assert after["fills"] == 6
    assert all(p["quantity"] == 0 for p in after["positions"].values())
    assert after["cash"] < before["cash"] + 1500
    assert after["cash"] == pytest.approx(10000 + after["realized"])
    assert all(
        r["payload"]["price"] < 90 for r in ledger() if r["kind"] == "fill" and r["payload"]["side"] == "sell"
    )


def test_thin_books_never_invent_fills_and_cancellation_is_durable():
    forecasts()
    run(depth=0.00001)
    rows = ledger()
    assert not any(r["kind"] == "fill" for r in rows)
    assert any(r["kind"] == "cancel" and r["payload"]["reason"] == "insufficient_depth" for r in rows)
    assert all(paper.balance(rows, a)["cash"] == 10000 for a in paper.ACCOUNTS)
    run()
    assert not any(r["kind"] == "fill" for r in ledger())


def test_stale_poisoned_and_depegged_data_are_distinct_hard_gates():
    s = snapshot()
    assert market.quality(s, "BTC", NOW)["buy_ok"]
    assert not market.quality(s, "BTC", NOW + 46)["buy_ok"]
    poison = copy.deepcopy(s)
    poison["books"]["binance:BTC"]["bids"][0][0] = 119.9
    poison["books"]["binance:BTC"]["asks"][0][0] = 120.1
    q = market.quality(poison, "BTC", NOW)
    assert not q["buy_ok"] and q["execution_ok"]
    depeg = copy.deepcopy(s)
    depeg["books"]["coinbase:USDT"]["bids"][0][0] = 0.899
    depeg["books"]["coinbase:USDT"]["asks"][0][0] = 0.901
    assert not market.quality(depeg, "BTC", NOW)["buy_ok"]
    # Common market moves are accepted when the independent venues agree.
    assert market.quality(snapshot(price=70), "BTC", NOW)["buy_ok"]


def test_forecast_information_boundary_and_no_fallback_model():
    forecasts(bad_input=True)
    run()
    rows = ledger()
    assert not any(r["kind"] == "fill" and r["account"] != "reference" for r in rows)
    assert any(r["kind"] == "decision" and r["payload"]["reason"] == "input_invalid" for r in rows)


def test_jev_is_a_veto_not_a_price_multiplier_and_future_annotations_are_excluded():
    from oracle.jev import VERSION

    forecasts()
    answers = {a: {"probability": 0.9} for a in config.ASSETS}
    answers.update(material={"probability": 0.9}, tone={"choice": "negative"}, event={"choice": "security"})
    ident = "a" * 64
    with connect() as db:
        db.execute(
            "INSERT INTO news(id,source,url,title,published_at,first_seen,content_hash,cluster,assets,event_type) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                ident,
                "CoinDesk",
                "https://example.com/",
                "Untrusted title",
                NOW - 20,
                NOW - 10,
                ident,
                ident,
                "BTC,ETH,SOL",
                "security",
            ),
        )
        db.execute(
            "INSERT INTO news_evaluations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("c" * 64, ident, "typesafe-ai/jev", VERSION, NOW, ident, "{}", packed(answers), "{}", 1, "test"),
        )
        assert paper.news_context(db, "BTC", NOW - 1)["items"] == []
    run()
    assert paper.balance(ledger(), "news-guarded")["fills"] == 0
    assert paper.balance(ledger(), "price-only")["fills"] == 3
    data = paper.public_snapshot()
    assert "Untrusted title" not in json.dumps(data)
    assert "https://example.com" not in json.dumps(data)


def test_expired_order_and_pre_decision_quote_never_fill():
    paper.start(NOW)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        paper.append(
            db,
            "order:test",
            NOW,
            "price-only",
            "order",
            {"decision_key": "test", "side": "buy", "quantity": 1, "budget": 500},
            "BTC",
        )
    paper.settle(ledger()[-1], snapshot(NOW + 121), NOW + 122)
    assert ledger()[-1]["payload"]["reason"] == "order_expired"
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        paper.append(
            db,
            "order:test2",
            NOW + 130,
            "price-only",
            "order",
            {"decision_key": "test2", "side": "buy", "quantity": 1, "budget": 500},
            "BTC",
        )
    paper.settle(ledger()[-1], snapshot(NOW + 129), NOW + 131)
    assert ledger()[-1]["payload"]["reason"] == "quote_before_decision"


def test_unknown_marks_are_visible_and_prevent_new_risk():
    forecasts()
    run()
    stale = snapshot(NOW)
    paper.cycle(lambda: stale, lambda: NOW + 3600)
    data = paper.public_snapshot()
    assert all(not a["fresh"] for a in data["accounts"])
    assert all(a["cash"] >= 0 for a in data["accounts"])
    assert any(d["action"] == "blocked" for d in data["decisions"])


def test_drawdown_brake_persists_and_export_contains_no_manual_holdings():
    forecasts()
    run()
    with connect() as db:
        db.execute("INSERT INTO holdings VALUES('BTC',123456,1,?)", (NOW,))
        db.execute("BEGIN IMMEDIATE") if not db.in_transaction else None
        paper.append(db, "brake:news-guarded", NOW + 20, "news-guarded", "brake", {"drawdown": 0.08})
    state = paper.balance(ledger(), "news-guarded")
    q = market.quality(snapshot(), "BTC", NOW)
    result = paper.plan(
        state,
        paper.valued(state, {a: q for a in config.ASSETS}),
        q,
        None,
        None,
        {"veto": False},
        "news-guarded",
        "BTC",
        NOW + 25000,
        False,
    )
    assert result["reason"] == "drawdown_brake"
    assert "123456" not in json.dumps(paper.public_snapshot())


def test_chain_detects_altered_evidence():
    forecasts()
    run()
    rows = ledger()
    rows[0]["payload"]["usd"] = 99999
    with pytest.raises(ValueError, match="chain"):
        paper.verify_chain(rows)


def test_public_chart_window_does_not_bridge_omitted_months():
    paper.start(NOW - 31 * 86400)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for account in paper.ACCOUNTS:
            for index, at in enumerate((NOW - 31 * 86400 + 1, NOW)):
                paper.append(
                    db,
                    f"chart:{account}:{index}",
                    at,
                    account,
                    "valuation",
                    {"equity": 10000, "marks": {}, "fresh": True, "drawdown": 0},
                )
    result = paper.public_snapshot()
    assert all(h["points"] == [{"at": NOW, "equity": 10000, "fresh": True}] for h in result["history"])


def test_intra_hour_drawdown_brake_survives_a_price_recovery():
    at = NOW // 3600 * 3600 + 60
    forecasts(at=at)
    run(at=at)
    run(at=at + 900, price=40)
    assert paper.balance(ledger(), "news-guarded")["braked"]
    assert paper.balance(ledger(), "price-only")["braked"]
    run(at=at + 1800, price=100)
    assert paper.balance(ledger(), "news-guarded")["braked"]
    assert not paper.balance(ledger(), "reference")["braked"]


def v2_rows():
    with connect() as db:
        return paper.events(db, paper.RUN_V2)


def test_common_start_is_identical_prospective_and_does_not_rewrite_v1(monkeypatch):
    forecasts(prediction=98)
    run()
    original = ledger()
    assert paper.RUN == "paper-v1-12b50e70aff6"
    monkeypatch.setenv("ORACLE_PAPER_V2_ENABLED", "1")
    run(NOW + 30)
    rows = v2_rows()
    states = [paper.balance(rows, a, paper.POLICY_V2) for a in paper.ACCOUNTS]
    assert states[0] == states[1] == states[2]
    assert all(s["fills"] == 3 and 4000 <= s["cash"] < 4050 for s in states)
    assert ledger() == original
    fills = [r for r in rows if r["kind"] == "fill"]
    assert len({r["payload"]["observation_id"] for r in fills}) == 1
    assert len({r["ts"] for r in fills}) == 1
    with connect() as db:
        obs = json.loads(
            db.execute(
                "SELECT payload FROM paper_observations WHERE id=?", (fills[0]["payload"]["observation_id"],)
            ).fetchone()[0]
        )
    assert obs["started_at"] > max(r["ts"] for r in rows if r["kind"] == "decision")
    assert all(d["reason"] == "initial_allocation" for d in paper.public_snapshot()["decisions"])
    run(NOW + 35)
    assert v2_rows() == rows
    assert paper.verify_chain(v2_rows()) == rows[-1]["hash"]


def test_common_start_cancels_every_fill_if_one_asset_has_insufficient_depth(monkeypatch):
    current = [NOW]

    def collect():
        current[0] += 1
        s = snapshot(current[0])
        s["books"]["coinbase:SOL"]["asks"][0][1] = 0.00001
        s["id"] = digest({k: v for k, v in s.items() if k != "id"})
        return s

    paper._cycle(collect, lambda: current[0] + 0.01, paper.RUN_V2)
    rows = v2_rows()
    assert not any(r["kind"] == "fill" for r in rows)
    assert len([r for r in rows if r["kind"] == "cancel"]) == 9
    assert not paper.initialized(rows)
    # The next hourly attempt uses new prices, not a retroactive repair.
    current[0] += 3600
    paper._cycle(lambda: snapshot(current[0] + 1), lambda: current[0] + 1.01, paper.RUN_V2)
    assert not paper.initialized(v2_rows())  # execution request did not follow its decision


def test_common_start_recovery_never_leaves_one_portfolio_partially_invested(monkeypatch):
    current = [NOW]

    def collect():
        current[0] += 1
        return snapshot(current[0])

    original_settle = paper._settle
    attempts = [0]

    def interrupted(*args):
        attempts[0] += 1
        if attempts[0] == 4:
            raise RuntimeError("simulated interruption")
        return original_settle(*args)

    monkeypatch.setattr(paper, "_settle", interrupted)
    with pytest.raises(RuntimeError, match="interruption"):
        paper._cycle(collect, lambda: current[0] + 0.01, paper.RUN_V2)
    assert not any(r["kind"] == "fill" for r in v2_rows())
    assert len(paper.pending(v2_rows())) == 9
    monkeypatch.setattr(paper, "_settle", original_settle)
    paper._cycle(collect, lambda: current[0] + 0.01, paper.RUN_V2)
    assert len([r for r in v2_rows() if r["kind"] == "fill"]) == 9
    assert len([r for r in v2_rows() if r["kind"] == "deposit"]) == 3


def test_common_start_respects_bad_inputs_and_active_exits_after_start(monkeypatch):
    paper._cycle(lambda: snapshot(NOW), lambda: NOW + 60, paper.RUN_V2)
    assert not any(r["kind"] == "fill" for r in v2_rows())
    assert all(
        r["payload"]["reason"] == "initial_allocation_wait" for r in v2_rows() if r["kind"] == "decision"
    )
    monkeypatch.setenv("ORACLE_PAPER_V2_ENABLED", "1")
    run(NOW + 3600)
    assert paper.initialized(v2_rows())
    run(NOW + 7200, price=90)
    rows = v2_rows()
    for a in paper.ACCOUNTS[:2]:
        state = paper.balance(rows, a, paper.POLICY_V2)
        assert state["fills"] == 6
        assert state["cash"] == pytest.approx(10000 + state["realized"])
    assert paper.balance(rows, "reference", paper.POLICY_V2)["fills"] == 3
    # Sold positions must never be re-seeded by the shared-start mechanism.
    run(NOW + 10800, price=90)
    assert paper.balance(v2_rows(), "price-only", paper.POLICY_V2)["fills"] == 6


def test_common_start_then_forecast_exit_waits_for_six_hour_cooldown(monkeypatch):
    monkeypatch.setenv("ORACLE_PAPER_V2_ENABLED", "1")
    forecasts(prediction=98)
    run()
    # An eligible negative forecast is context during setup; it cannot cancel the fixed start.
    assert paper.balance(v2_rows(), "price-only", paper.POLICY_V2)["fills"] == 3
    forecasts(at=NOW + 3600, prediction=98)
    run(NOW + 3600)
    assert paper.balance(v2_rows(), "price-only", paper.POLICY_V2)["fills"] == 3
    forecasts(at=NOW + 7 * 3600, prediction=98)
    run(NOW + 7 * 3600)
    state = paper.balance(v2_rows(), "price-only", paper.POLICY_V2)
    assert state["fills"] == 6
    assert all(p["quantity"] == 0 for p in state["positions"].values())
    assert paper.balance(v2_rows(), "reference", paper.POLICY_V2)["fills"] == 3
    assert any(r["kind"] == "decision" and r["payload"]["reason"] == "negative_forecast" for r in v2_rows())
