import pytest

from oracle import config, paper, paper_trend
from oracle.db import connect, init
from oracle.ingest import store_candles
from tests.test_paper import NOW, snapshot

DAY = 86400
TODAY = int(NOW // DAY) * DAY


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "trend.sqlite3")
    monkeypatch.setenv("ORACLE_PAPER_ENABLED", "1")
    monkeypatch.setenv("ORACLE_PAPER_V3_ENABLED", "1")
    monkeypatch.delenv("ORACLE_PAPER_V2_ENABLED", raising=False)
    init()
    paper.init_schema()


def closes(values, day=TODAY, assets=config.ASSETS):
    """Daily closes keyed by days before `day`; 0 is the close that ends at `day` itself."""
    for asset in assets:
        rows = [[(day - back * DAY - 3600) * 1000, c, c, c, c, 1] for back, c in values.items()]
        store_candles(asset, rows, day + 60)


def run(at=NOW, price=100, depth=1000):
    current = [at]

    def collect():
        current[0] += 1
        return snapshot(current[0], price, depth)

    return paper_trend.cycle(collect, lambda: current[0] + 0.01)


def ledger():
    with connect() as db:
        return paper.events(db, paper.RUN_V3)


def fills(account):
    return [r for r in ledger() if r["kind"] == "fill" and r["account"] == account]


UP = {0: 100, 7: 90, 14: 90, 28: 90, 56: 90}
DOWN = {0: 100, 7: 110, 14: 110, 28: 110, 56: 110}


def test_live_runs_keep_their_identity_and_the_third_run_is_separate():
    assert (paper.RUN, paper.RUN_V2) == ("paper-v1-12b50e70aff6", "paper-v2-a782a0f058cb")
    assert paper.RUN_V3.startswith("paper-v3-") and paper.accounts(paper.RUN_V3) == paper.TREND_ACCOUNTS
    assert paper.accounts(paper.RUN) == paper.accounts(paper.RUN_V2) == paper.ACCOUNTS


def test_disabled_run_writes_nothing(monkeypatch):
    monkeypatch.delenv("ORACLE_PAPER_V3_ENABLED")
    closes(UP)
    assert run() == {"state": "disabled"} and paper.public_snapshot(paper.RUN_V3) is None


def test_uptrend_buys_like_the_benchmarks_and_a_restart_adds_nothing():
    closes(UP)
    run()
    rows = ledger()
    for account in paper.TREND_ACCOUNTS:
        state = paper.balance(rows, account, paper.POLICY_V3)
        assert state["fills"] == 3 and 3950 < state["cash"] < 4100
    assert {r["payload"]["reason"] for r in rows if r["kind"] == "decision"} == {
        "trend_up",
        "reference_entry",
    }
    run(NOW + 60)
    assert [r["event_key"] for r in ledger() if r["kind"] != "valuation"] == [
        r["event_key"] for r in rows if r["kind"] != "valuation"
    ]
    assert paper.verify_chain(ledger())


def test_downtrend_keeps_the_trend_account_in_cash():
    closes(DOWN)
    run()
    assert not fills("trend") and len(fills("rebalanced")) == len(fills("reference")) == 3
    trend = [r["payload"] for r in ledger() if r["kind"] == "decision" and r["account"] == "trend"]
    assert all(d["action"] == "hold" and d["signal"]["target_weight"] == 0 for d in trend)
    assert all(d["signal"]["trend"]["share"] == 0 and "news" not in d for d in trend)


def test_partial_trend_scales_the_position():
    closes({0: 100, 7: 90, 14: 90, 28: 110, 56: 110})
    run()
    state = paper.balance(ledger(), "trend", paper.POLICY_V3)
    assert 6950 < state["cash"] < 7050  # half of 20% in each of three coins leaves about 70% cash


def test_trend_turning_down_sells_everything_once_per_day():
    closes(UP)
    run()
    # Later the same UTC day nothing may trade again, whatever the prices do.
    run(NOW + 3600, price=80)
    assert len(fills("trend")) == 3
    tomorrow = TODAY + DAY
    closes({0: 80, 7: 100, 14: 100, 28: 100, 56: 100}, day=tomorrow)
    run(tomorrow + 900, price=80)
    sold = [r for r in fills("trend") if r["payload"]["side"] == "sell"]
    assert len(sold) == 3 and all(
        p["quantity"] == 0 for p in paper.balance(ledger(), "trend", paper.POLICY_V3)["positions"].values()
    )
    assert {
        r["payload"]["reason"] for r in ledger() if r["kind"] == "decision" and r["payload"]["side"] == "sell"
    } == {"trend_down"}
    assert len(fills("reference")) == 3  # the held benchmark never trades again


def test_missing_daily_close_blocks_only_the_trend_account():
    closes({0: 100, 7: 90, 14: 90, 28: 90})  # no close 56 days back
    run()
    assert not fills("trend") and len(fills("rebalanced")) == 3
    reasons = {
        r["payload"]["reason"] for r in ledger() if r["kind"] == "decision" and r["account"] == "trend"
    }
    assert reasons == {"trend_input_missing"}


def test_signal_ignores_candles_after_the_daily_close():
    closes(DOWN)
    with connect() as db:
        before = paper_trend.trend(db, "BTC", NOW)
    # An intraday rally after today's close, and a fresher close tomorrow, are not part of today's signal.
    store_candles("BTC", [[(TODAY + 3 * 3600) * 1000, 500, 500, 500, 500, 1]], NOW)
    with connect() as db:
        assert paper_trend.trend(db, "BTC", NOW) == before
    assert before[0]["share"] == 0 and before[0]["origin"] == TODAY


def test_rebalanced_benchmark_restores_weights_and_the_held_one_does_not():
    closes(UP)
    run()
    tomorrow = TODAY + DAY
    closes({0: 160, 7: 90, 14: 90, 28: 90, 56: 90}, day=tomorrow)
    run(tomorrow + 900, price=160)  # every coin +60%: 60% crypto has become about 71%
    sells = [r for r in fills("rebalanced") if r["payload"]["side"] == "sell"]
    assert len(sells) == 3 and len(fills("reference")) == 3
    sold = [r for r in ledger() if r["kind"] == "decision" and r["payload"]["side"] == "sell"]
    assert [r["payload"]["reason"] for r in sold if r["account"] == "rebalanced"] == ["rebalance"] * 3
    # The trend account also trims back to 20% per coin; that is its target, not a benchmark rebalance.
    assert {r["payload"]["reason"] for r in sold if r["account"] == "trend"} == {"trend_down"}
    state = paper.balance(ledger(), "rebalanced", paper.POLICY_V3)
    nav = state["cash"] + sum(p["quantity"] * 160 for p in state["positions"].values())
    assert all(
        p["quantity"] * 160 / nav == pytest.approx(0.2, abs=0.005) for p in state["positions"].values()
    )


def test_failed_benchmark_entry_is_retried_until_it_fills():
    closes(UP)
    run(depth=0.001)  # books too thin: every order is cancelled
    assert not fills("reference") and any(r["kind"] == "cancel" for r in ledger())
    run(NOW + 3600)
    assert len(fills("reference")) == 3


def test_third_run_does_not_touch_the_first(monkeypatch):
    closes(UP)
    current = [NOW]

    def collect():
        current[0] += 1
        return snapshot(current[0])

    paper.cycle(collect, lambda: current[0] + 0.01)
    with connect() as db:
        first = [r["event_key"] for r in paper.events(db, paper.RUN)]
        assert {r["account"] for r in paper.events(db, paper.RUN_V3)} == set(paper.TREND_ACCOUNTS)
    assert first and all("trend" not in key and "rebalanced" not in key for key in first)


def test_public_export_names_the_three_accounts_and_explains_each_trade():
    closes(UP)
    run()
    data = paper.public_snapshot(paper.RUN_V3)
    assert [a["id"] for a in data["accounts"]] == list(paper.TREND_ACCOUNTS) and data[
        "policy"
    ] == paper.POLICY_V3
    assert {t["reason"] for t in data["trades"]} == {"trend_up", "reference_entry"}
    assert all(
        d["news"] is None and d["signal"]["trend"]["lookbacks"][0]["days"] == 7 for d in data["decisions"]
    )
    assert set(data["reasons"]) == {"trend_up"} and data["journal"]["verified"]
