"""Prospective paper portfolios: immutable evidence, decisions and USD cash flows.

This module has no broker SDK, private exchange credentials or real-order endpoint.
"""

import json
import math
import os
import time

from . import config, market
from .db import connect, digest, packed

ACCOUNTS = ("news-guarded", "price-only", "reference")
POLICY = {
    "version": "paper-v1",
    "starting_usd": 10000,
    "execution": "coinbase-usd",
    "fee_rate": 0.001,
    "slippage_rate": 0.0005,
    "max_order_age": 120,
    "entry_fraction": 0.05,
    "asset_cap": 0.25,
    "total_cap": 0.60,
    "cooldown_hours": 6,
    "drawdown_brake": 0.08,
    "position_stop": 0.06,
    "daily_vol_target": 0.03,
    "min_margin": 0.0025,
    "vol_margin": 0.20,
    "band_margin": 0.05,
    "news_probability": 0.7,
    "news_hours": 6,
    "max_forecast_age": 5400,
    "max_book_age": market.MAX_AGE,
    "max_spread_bps": market.MAX_SPREAD_BPS,
    "max_divergence": market.MAX_DIVERGENCE,
    "min_order_usd": 25,
    "reference_weights": [0.2, 0.2, 0.2],
}
RUN = "paper-v1-" + digest(POLICY)[:12]
POLICY_V2 = {**POLICY, "version": "paper-v2", "initial_weights": [0.2, 0.2, 0.2]}
RUN_V2 = "paper-v2-" + digest(POLICY_V2)[:12]
# Third run: no forecasts and no news. Its decision rule lives in paper_trend.py; the ledger is shared.
TREND_ACCOUNTS = ("trend", "rebalanced", "reference")
POLICY_V3 = {
    "version": "paper-v3",
    "starting_usd": 10000,
    "execution": "coinbase-usd",
    "fee_rate": 0.001,
    "slippage_rate": 0.0005,
    "max_order_age": 120,
    "asset_weight": 0.2,
    "asset_cap": 0.25,
    "total_cap": 0.60,
    "lookback_days": [7, 14, 28, 56],
    "rebalance_band": 0.05,
    "min_order_usd": 25,
    "max_book_age": market.MAX_AGE,
    "max_spread_bps": market.MAX_SPREAD_BPS,
    "max_divergence": market.MAX_DIVERGENCE,
}
RUN_V3 = "paper-v3-" + digest(POLICY_V3)[:12]
POLICIES = {RUN: POLICY, RUN_V2: POLICY_V2, RUN_V3: POLICY_V3}


def accounts(run_id):
    return TREND_ACCOUNTS if run_id == RUN_V3 else ACCOUNTS


def init_schema():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS paper_runs (
            id TEXT PRIMARY KEY, started_at REAL NOT NULL, policy TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS paper_observations (
            id TEXT PRIMARY KEY, received_at REAL NOT NULL, payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS paper_events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES paper_runs(id),
            event_key TEXT NOT NULL, ts REAL NOT NULL, account TEXT NOT NULL, asset TEXT,
            kind TEXT NOT NULL, payload TEXT NOT NULL, previous_hash TEXT NOT NULL, hash TEXT NOT NULL,
            UNIQUE(run_id,event_key)
        );
        CREATE INDEX IF NOT EXISTS paper_event_run ON paper_events(run_id,seq);
        """)
        for table in ("paper_runs", "paper_events", "paper_observations"):
            for action in ("UPDATE", "DELETE"):
                db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS no_{action}_{table} BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'Paper evidence is immutable'); END"
                )


def events(db, run_id=RUN):
    return [
        {**dict(r), "payload": json.loads(r["payload"])}
        for r in db.execute("SELECT * FROM paper_events WHERE run_id=? ORDER BY seq", (run_id,))
    ]


def append(db, key, ts, account, kind, payload, asset=None, run_id=RUN):
    # Callers hold BEGIN IMMEDIATE, so the chain and cash ledger share one writer.
    if db.execute("SELECT 1 FROM paper_events WHERE run_id=? AND event_key=?", (run_id, key)).fetchone():
        return False
    prev = db.execute(
        "SELECT hash FROM paper_events WHERE run_id=? ORDER BY seq DESC LIMIT 1", (run_id,)
    ).fetchone()
    prev = prev[0] if prev else "0" * 64
    hashed = digest([run_id, key, ts, account, asset, kind, payload, prev])
    db.execute(
        "INSERT INTO paper_events(run_id,event_key,ts,account,asset,kind,payload,previous_hash,hash) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (run_id, key, ts, account, asset, kind, packed(payload), prev, hashed),
    )
    return True


def start(now, run_id=RUN):
    policy = POLICIES[run_id]
    init_schema()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT OR IGNORE INTO paper_runs VALUES(?,?,?)", (run_id, now, packed(policy)))
        started = db.execute("SELECT started_at FROM paper_runs WHERE id=?", (run_id,)).fetchone()[0]
        for account in accounts(run_id):
            append(
                db,
                "deposit:" + account,
                started,
                account,
                "deposit",
                {"usd": policy["starting_usd"]},
                run_id=run_id,
            )


def remember(snapshot):
    with connect() as db:
        db.execute(
            "INSERT OR IGNORE INTO paper_observations VALUES(?,?,?)",
            (snapshot["id"], snapshot["received_at"], packed(snapshot)),
        )


def balance(rows, account, policy=POLICY):
    result = {
        "cash": 0.0,
        "fees": 0.0,
        "turnover": 0.0,
        "realized": 0.0,
        "fills": 0,
        "positions": {a: {"quantity": 0.0, "cost": 0.0, "last_trade": None} for a in config.ASSETS},
        "peak": policy["starting_usd"],
        "max_drawdown": 0.0,
        "braked": False,
        "last_marks": {},
    }
    for event in rows:
        if event["account"] != account:
            continue
        p = event["payload"]
        if event["kind"] == "deposit":
            result["cash"] += p["usd"]
        elif event["kind"] == "brake":
            result["braked"] = True
        elif event["kind"] == "valuation":
            result["last_marks"] = p["marks"]
            if p["fresh"]:
                result["peak"] = max(result["peak"], p["equity"])
                result["max_drawdown"] = max(result["max_drawdown"], p["drawdown"])
        elif event["kind"] == "fill":
            pos = result["positions"][event["asset"]]
            qty, gross, fee = p["quantity"], p["gross"], p["fee"]
            if p["side"] == "buy":
                pos["quantity"] += qty
                pos["cost"] += gross + fee
                result["cash"] -= gross + fee
            else:
                cost = pos["cost"] * min(1, qty / pos["quantity"])
                pos["quantity"] = max(0.0, pos["quantity"] - qty)
                pos["cost"] = max(0.0, pos["cost"] - cost)
                result["cash"] += gross - fee
                result["realized"] += gross - fee - cost
            pos["last_trade"] = event["ts"]
            result["fees"] += fee
            result["turnover"] += gross
            result["fills"] += 1
    if result["cash"] < -1e-7:
        raise ValueError("Paper ledger has negative cash")
    return result


def valued(state, qualities):
    marks = {a: qualities[a]["mark"] or state["last_marks"].get(a) for a in config.ASSETS}
    fresh = all(
        qualities[a]["mark"] is not None for a, p in state["positions"].items() if p["quantity"] > 1e-12
    )
    equity = state["cash"] + sum(p["quantity"] * (marks[a] or 0) for a, p in state["positions"].items())
    return {
        "equity": equity,
        "marks": marks,
        "fresh": fresh,
        "drawdown": max(0.0, 1 - equity / max(state["peak"], equity)),
    }


def signal(db, asset, now, quality, policy=POLICY):
    row = db.execute(
        "SELECT * FROM forecasts WHERE experiment=? AND scope='live' AND model='timesfm' "
        "AND asset=? AND horizon=24 AND issued_at<=? AND origin<=? ORDER BY origin DESC LIMIT 1",
        (config.EXPERIMENT, asset, now, now),
    ).fetchone()
    if row is None:
        return None, "forecast_missing"
    r = dict(row)
    if not (0 <= now - r["origin"] <= policy["max_forecast_age"] and r["target"] > now):
        return None, "forecast_stale"
    provenance, features = json.loads(r["provenance"]), json.loads(r["features"])
    artifact = db.execute(
        "SELECT payload,created_at FROM artifacts WHERE id=?", (provenance.get("input_artifact_id"),)
    ).fetchone()
    if not artifact or artifact["created_at"] > r["issued_at"]:
        return None, "input_invalid"
    inputs = json.loads(artifact["payload"])
    candles = inputs.get("candles", [])
    if (
        provenance.get("model_revision") != config.MODEL_REVISION
        or provenance.get("quote") != "USDT"
        or digest(inputs) != provenance.get("input_artifact_id")
        or len(candles) != config.CONTEXT
        or candles[-1]["ts"] != r["origin"]
        or candles[-1]["close"] != r["base"]
    ):
        return None, "input_invalid"
    for i, candle in enumerate(candles):
        if (
            candle["ts"] > r["origin"]
            or candle["observed_at"] > r["issued_at"]
            or not math.isfinite(candle["close"])
            or candle["close"] <= 0
            or not math.isfinite(candle["volume"])
            or candle["volume"] < 0
            or (i and candle["ts"] - candles[i - 1]["ts"] != 3600)
        ):
            return None, "input_invalid"
    if not (
        all(v is not None and math.isfinite(v) and v > 0 for v in (r["lower"], r["upper"], r["prediction"]))
        and r["lower"] <= r["prediction"] <= r["upper"]
    ):
        return None, "input_invalid"
    vol = features.get("volatility_24h")
    if vol is None or not math.isfinite(vol) or vol < 0:
        return None, "input_invalid"
    vol *= math.sqrt(24)
    margin = max(
        policy["min_margin"],
        policy["vol_margin"] * vol,
        policy["band_margin"] * math.log(r["upper"] / r["lower"]),
    )
    fx, current = quality["fx"], quality["prices"]["coinbase"]
    expected = r["prediction"] * fx / current - 1 if fx and current else None
    threshold = (
        2 * (policy["fee_rate"] + policy["slippage_rate"]) + (quality["spread_bps"] or 0) / 10000 + margin
    )
    return {
        "forecast_id": r["id"],
        "origin": r["origin"],
        "issued_at": r["issued_at"],
        "target": r["target"],
        "prediction_usdt": r["prediction"],
        "lower_usdt": r["lower"],
        "upper_usdt": r["upper"],
        "expected_return": expected,
        "entry_threshold": threshold,
        "daily_volatility": vol,
        "margin": margin,
        "input_hash": provenance["input_artifact_id"],
    }, None


def news_context(db, asset, now):
    from .jev import VERSION

    rows = db.execute(
        "SELECT n.*,e.id AS evaluation_id,e.evaluated_at,e.answers,e.version FROM news n "
        "JOIN news_evaluations e ON e.news_id=n.id WHERE e.version=? AND n.source IN ('CoinDesk','Ethereum Blog') "
        "AND n.published_at>? AND n.published_at<=? AND n.first_seen<=? AND e.evaluated_at<=? "
        "ORDER BY n.first_seen DESC LIMIT 100",
        (VERSION, now - POLICY["news_hours"] * 3600, now, now, now),
    ).fetchall()
    selected, seen_urls, clusters = [], set(), set()
    for r in rows:
        if r["url"] in seen_urls or r["cluster"] in clusters:
            continue
        seen_urls.add(r["url"])
        clusters.add(r["cluster"])
        answers = json.loads(r["answers"])
        relevance = answers[asset]["probability"]
        if relevance < POLICY["news_probability"]:
            continue
        material = answers["material"]["probability"]
        tone, event = answers["tone"]["choice"], answers["event"]["choice"]
        selected.append(
            {
                "id": r["id"],
                "evaluation_id": r["evaluation_id"],
                "source": r["source"],
                "published_at": r["published_at"],
                "first_seen": r["first_seen"],
                "evaluated_at": r["evaluated_at"],
                "relevance": relevance,
                "material": material,
                "tone": tone,
                "event": event,
            }
        )
        if len(selected) == 12:
            break
    polls = [
        db.execute(
            "SELECT ok,polled_at FROM source_polls WHERE source=? AND polled_at<=? "
            "ORDER BY polled_at DESC LIMIT 1",
            (s, now),
        ).fetchone()
        for s in config.FEEDS
    ]
    available = all(r and r["ok"] and now - r["polled_at"] < 3600 for r in polls)
    veto = any(
        r["material"] >= POLICY["news_probability"]
        and r["tone"] == "negative"
        and r["event"] in ("security", "network", "exchange", "regulation")
        for r in selected
    )
    return {
        "state": "available" if available and selected else "partial" if selected else "unavailable",
        "veto": veto,
        "version": VERSION,
        "items": selected,
    }


def plan(
    state,
    valuation,
    quality,
    forecast,
    forecast_error,
    news,
    account,
    asset,
    now,
    reference_done,
    policy=POLICY,
):
    pos = state["positions"][asset]
    qty, nav = pos["quantity"], valuation["equity"]
    mark = quality["mark"]
    base = {"action": "hold", "reason": "below_entry", "side": None, "quantity": 0.0, "budget": 0.0}
    if account == "reference" and reference_done:
        return {**base, "reason": "reference_hold"}
    if qty > 1e-12 and account != "reference":
        if not quality["execution_ok"]:
            return {**base, "action": "blocked", "reason": "execution_invalid"}
        value = qty * mark
        stop = mark <= pos["cost"] / qty * (1 - policy["position_stop"])
        excess = max(0.0, value - nav * policy["asset_cap"])
        exposure = max(0.0, nav - state["cash"])
        if valuation["fresh"] and exposure > nav * policy["total_cap"]:
            excess = max(excess, value * (exposure - nav * policy["total_cap"]) / exposure)
        normal_exit = (
            forecast
            and forecast["expected_return"] is not None
            and forecast["expected_return"] < -(0.003 + forecast["margin"] / 2)
            and now - (pos["last_trade"] or 0) >= policy["cooldown_hours"] * 3600
        )
        if stop or excess >= policy["min_order_usd"] or normal_exit:
            sell_qty = qty if stop or normal_exit else min(qty, excess / mark)
            # The reason names what set the quantity: a stop or a negative forecast sells everything,
            # so a cap that is also exceeded by a few dollars must not take the credit.
            reason = "position_stop" if stop else "negative_forecast" if normal_exit else "allocation_limit"
            return {**base, "action": "sell", "side": "sell", "quantity": sell_qty, "reason": reason}
    if not quality["buy_ok"] or not valuation["fresh"]:
        return {**base, "action": "blocked", "reason": "data_quality"}
    if state["braked"] or valuation["drawdown"] >= policy["drawdown_brake"]:
        return {**base, "action": "blocked", "reason": "drawdown_brake"}
    if account != "reference":
        if forecast_error or forecast is None:
            return {**base, "action": "blocked", "reason": forecast_error or "forecast_missing"}
        if pos["last_trade"] and now - pos["last_trade"] < policy["cooldown_hours"] * 3600:
            return {**base, "reason": "cooldown"}
        if forecast["expected_return"] is None or forecast["expected_return"] <= forecast["entry_threshold"]:
            return base
        if account == "news-guarded" and news["veto"]:
            return {**base, "action": "blocked", "reason": "news_veto"}
    size = (
        policy["starting_usd"] * 0.20
        if account == "reference"
        else (
            nav
            * policy["entry_fraction"]
            * min(1, policy["daily_vol_target"] / max(0.001, forecast["daily_volatility"]))
        )
    )
    budget = min(
        size, state["cash"] - nav * (1 - policy["total_cap"]), nav * policy["asset_cap"] - qty * mark
    )
    if budget < policy["min_order_usd"]:
        return {**base, "reason": "allocation_limit"}
    # Quantity is fixed at decision; reserve costs and a 0.3% price-movement allowance.
    quantity = budget / (
        quality["prices"]["coinbase"] * (1 + policy["fee_rate"] + policy["slippage_rate"] + 0.003)
    )
    return {
        **base,
        "action": "buy",
        "side": "buy",
        "quantity": quantity,
        "budget": budget,
        "reason": "reference_entry" if account == "reference" else "positive_forecast",
    }


def pending(rows):
    settled = {r["payload"]["order_key"] for r in rows if r["kind"] in ("fill", "cancel")}
    return [r for r in rows if r["kind"] == "order" and r["event_key"] not in settled]


def settle(order, snapshot, now):
    remember(snapshot)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        return _settle(db, order, snapshot, now)


def _settle(db, order, snapshot, now):
    """Persist either a full fill or cancellation, never a favourable historical fill."""
    run_id = order["run_id"]
    policy = POLICIES[run_id]
    account, asset, p = order["account"], order["asset"], order["payload"]
    q = market.quality(snapshot, asset, now)
    reason = None
    if now - order["ts"] > policy["max_order_age"]:
        reason = "order_expired"
    elif snapshot["started_at"] <= order["ts"]:
        reason = "quote_before_decision"
    elif not q["execution_ok"] or (p["side"] == "buy" and not q["buy_ok"]):
        reason = "execution_invalid"
    gross = (
        None
        if reason
        else market.sweep(
            snapshot["books"][f"coinbase:{asset}"], p["side"], p["quantity"], policy["slippage_rate"]
        )
    )
    if reason is None and gross is None:
        reason = "insufficient_depth"
    rows = events(db, run_id)
    if not any(r["event_key"] == order["event_key"] for r in pending(rows)):
        return
    state = balance(rows, account, policy)
    value = valued(state, {a: market.quality(snapshot, a, now) for a in config.ASSETS})
    fee = (gross or 0) * policy["fee_rate"]
    if reason is None:
        if p["side"] == "buy":
            after_cash = state["cash"] - gross - fee
            position_value = (state["positions"][asset]["quantity"] + p["quantity"]) * q["mark"]
            after_nav = value["equity"] - gross - fee + p["quantity"] * q["mark"]
            if (
                not value["fresh"]
                or gross + fee > p["budget"] + 1e-7
                or after_cash < -1e-7
                or after_cash < after_nav * (1 - policy["total_cap"]) - 1e-7
                or position_value > after_nav * policy["asset_cap"] + 1e-7
                or state["braked"]
                or value["drawdown"] >= policy.get("drawdown_brake", math.inf)
            ):
                reason = "execution_risk_limit"
        elif p["quantity"] > state["positions"][asset]["quantity"] + 1e-12:
            reason = "insufficient_position"
    payload = {
        "order_key": order["event_key"],
        "decision_key": p["decision_key"],
        "observation_id": snapshot["id"],
        "observed_at": snapshot["received_at"],
    }
    if reason:
        append(
            db,
            "settle:" + order["event_key"],
            now,
            account,
            "cancel",
            {**payload, "reason": reason},
            asset,
            run_id=run_id,
        )
    else:
        append(
            db,
            "settle:" + order["event_key"],
            now,
            account,
            "fill",
            {
                **payload,
                "side": p["side"],
                "quantity": p["quantity"],
                "gross": gross,
                "fee": fee,
                "price": gross / p["quantity"],
            },
            asset,
            run_id=run_id,
        )
    return reason


def initialized(rows):
    return any(r["kind"] == "initialization" for r in rows)


def settle_initial(orders, snapshot, now):
    """All nine initial fills use one later observation and commit together, or none do."""
    remember(snapshot)
    run_id = orders[0]["run_id"]
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = events(db, run_id)
        outstanding = pending(rows)
        if initialized(rows) or not outstanding:
            return
        expected = {(account, asset) for account in ACCOUNTS for asset in config.ASSETS}
        if (
            len(orders) != 9
            or {(o["account"], o["asset"]) for o in orders} != expected
            or any(o["run_id"] != run_id or not o["payload"].get("initial") for o in orders)
            or {o["event_key"] for o in outstanding} != {o["event_key"] for o in orders}
        ):
            raise ValueError("Incomplete common initial allocation")
        db.execute("SAVEPOINT initial_fills")
        failures = [_settle(db, order, snapshot, now) for order in orders]
        if any(failures):
            db.execute("ROLLBACK TO initial_fills")
            for order, failure in zip(orders, failures, strict=True):
                append(
                    db,
                    "settle:" + order["event_key"],
                    now,
                    order["account"],
                    "cancel",
                    {
                        "order_key": order["event_key"],
                        "decision_key": order["payload"]["decision_key"],
                        "observation_id": snapshot["id"],
                        "observed_at": snapshot["received_at"],
                        "reason": failure or "initial_allocation_cancelled",
                    },
                    order["asset"],
                    run_id=run_id,
                )
        else:
            append(
                db,
                "initialization",
                now,
                "reference",
                "initialization",
                {"weights": POLICIES[run_id]["initial_weights"], "observation_id": snapshot["id"]},
                run_id=run_id,
            )
        db.execute("RELEASE initial_fills")


def initialize_common(run_id, snapshot, collector, clock):
    policy = POLICIES[run_id]
    now = clock()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = events(db, run_id)
        if initialized(rows):
            return snapshot, True
        key_prefix = f"decision:{int(now // 3600)}:"
        if any(r["event_key"].startswith(key_prefix) for r in rows):
            return snapshot, False
        qualities = {a: market.quality(snapshot, a, now) for a in config.ASSETS}
        good = all(q["buy_ok"] for q in qualities.values())
        for account in ACCOUNTS:
            for asset, weight in zip(config.ASSETS, policy["initial_weights"], strict=True):
                q = qualities[asset]
                key = key_prefix + account + ":" + asset
                forecast, _ = signal(db, asset, now, q, policy)
                budget = policy["starting_usd"] * weight
                quantity = (
                    budget
                    / (q["prices"]["coinbase"] * (1 + policy["fee_rate"] + policy["slippage_rate"] + 0.003))
                    if good
                    else 0
                )
                append(
                    db,
                    key,
                    now,
                    account,
                    "decision",
                    {
                        "action": "buy" if good else "blocked",
                        "reason": "initial_allocation" if good else "initial_allocation_wait",
                        "side": "buy" if good else None,
                        "quantity": quantity,
                        "budget": budget if good else 0,
                        "quality": q,
                        "signal": forecast,
                        "news": news_context(db, asset, now),
                        "equity": policy["starting_usd"],
                    },
                    asset,
                    run_id=run_id,
                )
                if good:
                    append(
                        db,
                        "order:" + key,
                        now,
                        account,
                        "order",
                        {
                            "decision_key": key,
                            "side": "buy",
                            "quantity": quantity,
                            "budget": budget,
                            "initial": True,
                        },
                        asset,
                        run_id=run_id,
                    )
        orders = pending(events(db, run_id))
    if orders:
        snapshot = collector()
        settle_initial(orders, snapshot, clock())
    # Regular decisions start in the following hour, even if the common start just filled.
    return snapshot, False


def cycle(collector=None, clock=None):
    if os.getenv("ORACLE_PAPER_ENABLED") != "1":
        return {"state": "disabled"}
    collector, clock = collector or market.collect, clock or time.time
    runs = [RUN]
    if os.getenv("ORACLE_PAPER_V2_ENABLED") == "1":
        runs.append(RUN_V2)
    results = [_cycle(collector, clock, r) for r in runs]
    if os.getenv("ORACLE_PAPER_V3_ENABLED") == "1":
        from .paper_trend import cycle as trend_cycle

        results.append(trend_cycle(collector, clock))
    return {"state": "running", "runs": results}


def _cycle(collector, clock, run_id):
    policy = POLICIES[run_id]
    if os.getenv("ORACLE_PAPER_ENABLED") != "1":
        return {"state": "disabled"}
    start(clock(), run_id)
    snapshot = collector()
    remember(snapshot)
    with connect() as db:
        outstanding = pending(events(db, run_id))
    initial_orders = [o for o in outstanding if o["payload"].get("initial")]
    if initial_orders:
        settle_initial(initial_orders, snapshot, clock())
    for order in outstanding:
        if not order["payload"].get("initial"):
            settle(order, snapshot, clock())
    ready = True
    if "initial_weights" in policy:
        snapshot, ready = initialize_common(run_id, snapshot, collector, clock)
    for account in ACCOUNTS if ready else ():
        for asset in config.ASSETS:
            now = clock()
            key = f"decision:{int(now // 3600)}:{account}:{asset}"
            with connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute(
                    "SELECT 1 FROM paper_events WHERE run_id=? AND event_key=?", (run_id, key)
                ).fetchone():
                    continue
                rows = events(db, run_id)
                state = balance(rows, account, policy)
                qualities = {a: market.quality(snapshot, a, now) for a in config.ASSETS}
                value = valued(state, qualities)
                if (
                    value["fresh"]
                    and value["drawdown"] >= policy["drawdown_brake"]
                    and account != "reference"
                ):
                    append(
                        db,
                        "brake:" + account,
                        now,
                        account,
                        "brake",
                        {"drawdown": value["drawdown"]},
                        run_id=run_id,
                    )
                    state["braked"] = True
                forecast, error = signal(db, asset, now, qualities[asset], policy)
                news = news_context(db, asset, now)
                ref_done = any(
                    r["account"] == account and r["asset"] == asset and r["kind"] == "order" for r in rows
                )
                decision = plan(
                    state,
                    value,
                    qualities[asset],
                    forecast,
                    error,
                    news,
                    account,
                    asset,
                    now,
                    ref_done,
                    policy,
                )
                if pending([r for r in rows if r["account"] == account]):
                    decision = {
                        "action": "blocked",
                        "reason": "pending_order",
                        "side": None,
                        "quantity": 0,
                        "budget": 0,
                    }
                append(
                    db,
                    key,
                    now,
                    account,
                    "decision",
                    {
                        **decision,
                        "quality": qualities[asset],
                        "signal": forecast,
                        "news": news,
                        "equity": value["equity"],
                    },
                    asset,
                    run_id=run_id,
                )
                if decision["side"]:
                    append(
                        db,
                        "order:" + key,
                        now,
                        account,
                        "order",
                        {
                            "decision_key": key,
                            "side": decision["side"],
                            "quantity": decision["quantity"],
                            "budget": decision["budget"],
                        },
                        asset,
                        run_id=run_id,
                    )
                    order = events(db, run_id)[-1]
                else:
                    order = None
            if order:
                # A separate, subsequent market request is mandatory for execution.
                snapshot = collector()
                settle(order, snapshot, clock())
    now = clock()
    qualities = {a: market.quality(snapshot, a, now) for a in config.ASSETS}
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = events(db, run_id)
        for account in ACCOUNTS:
            state = balance(rows, account, policy)
            value = valued(state, qualities)
            if (
                account != "reference"
                and value["fresh"]
                and max(value["drawdown"], state["max_drawdown"]) >= policy["drawdown_brake"]
            ):
                append(
                    db,
                    "brake:" + account,
                    now,
                    account,
                    "brake",
                    {"drawdown": value["drawdown"]},
                    run_id=run_id,
                )
            append(
                db,
                f"valuation:{int(now // 900)}:{account}",
                now,
                account,
                "valuation",
                value,
                run_id=run_id,
            )
    return {"state": "running", "run": run_id, "observation": snapshot["id"]}


def verify_chain(rows):
    prev = "0" * 64
    for r in rows:
        if r["previous_hash"] != prev or r["hash"] != digest(
            [r["run_id"], r["event_key"], r["ts"], r["account"], r["asset"], r["kind"], r["payload"], prev]
        ):
            raise ValueError("Paper journal chain does not match")
        prev = r["hash"]
    return prev


def public_snapshot(run_id=None):
    """Explicit export from paper-only tables; never serialize private dashboard payloads."""
    init_schema()
    with connect() as db:
        if run_id is None:
            latest = db.execute("SELECT id FROM paper_runs ORDER BY started_at DESC LIMIT 1").fetchone()
            run_id = latest["id"] if latest else RUN
        policy = POLICIES[run_id]
        run = db.execute("SELECT * FROM paper_runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            return None
        rows = events(db, run_id)
    head = verify_chain(rows)
    names, summaries, history = accounts(run_id), [], []
    for account in names:
        state = balance(rows, account, policy)
        valuations = [r for r in rows if r["account"] == account and r["kind"] == "valuation"]
        value = (
            valuations[-1]["payload"]
            if valuations
            else {"equity": state["cash"], "fresh": True, "marks": {}, "drawdown": 0}
        )
        asof = valuations[-1]["ts"] if valuations else run["started_at"]
        last_valuation_seq = valuations[-1]["seq"] if valuations else 0
        if any(
            r["account"] == account and r["kind"] == "fill" and r["seq"] > last_valuation_seq for r in rows
        ):
            value = {
                **value,
                "fresh": False,
                "equity": state["cash"]
                + sum(p["quantity"] * (value["marks"].get(a) or 0) for a, p in state["positions"].items()),
            }
        summaries.append(
            {
                "id": account,
                "cash": state["cash"],
                "equity": value["equity"],
                "asof": asof,
                "fresh": value["fresh"],
                "fees": state["fees"],
                "turnover": state["turnover"],
                "realized": state["realized"],
                "fills": state["fills"],
                "braked": state["braked"],
                "max_drawdown": state["max_drawdown"],
                "positions": [
                    {"asset": a, "quantity": p["quantity"], "cost": p["cost"], "mark": value["marks"].get(a)}
                    for a, p in state["positions"].items()
                ],
            }
        )
        # Hourly chart points, full history stays in the server journal. Latest 30 days are public.
        cutoff = asof - 30 * 86400
        by_hour = {int(r["ts"] // 3600): r for r in valuations if r["ts"] >= cutoff}
        seed = (
            [{"at": run["started_at"], "equity": policy["starting_usd"], "fresh": True}]
            if run["started_at"] >= cutoff
            else []
        )
        history.append(
            {
                "account": account,
                "points": seed
                + [
                    {"at": r["ts"], "equity": r["payload"]["equity"], "fresh": r["payload"]["fresh"]}
                    for r in list(by_hour.values())[-720:]
                ],
            }
        )
    outcomes = {r["payload"]["decision_key"]: r for r in rows if r["kind"] in ("fill", "cancel")}
    recorded = [r for r in rows if r["kind"] == "decision"]
    origin = {r["event_key"]: r for r in recorded}
    # Hours of later holds must not push the reason for a trade out of public view.
    acted = [r for r in recorded if outcomes.get(r["event_key"], {}).get("kind") == "fill"][-40:]
    decisions = []
    for r in sorted({r["seq"]: r for r in recorded[-90:] + acted}.values(), key=lambda r: -r["seq"]):
        p, outcome = r["payload"], outcomes.get(r["event_key"])
        decisions.append(
            {
                "seq": r["seq"],
                "at": r["ts"],
                "account": r["account"],
                "asset": r["asset"],
                "action": p["action"],
                "reason": p["reason"],
                "hash": r["hash"],
                "quality": p["quality"],
                "signal": p["signal"],
                "news": p.get("news"),
                "outcome": outcome["kind"] if outcome else "none",
                "execution": outcome["payload"] if outcome else None,
            }
        )
    trades = [
        {
            "seq": r["seq"],
            "at": r["ts"],
            "account": r["account"],
            "asset": r["asset"],
            "side": r["payload"]["side"],
            "quantity": r["payload"]["quantity"],
            "price": r["payload"]["price"],
            "gross": r["payload"]["gross"],
            "fee": r["payload"]["fee"],
            "hash": r["hash"],
            "reason": origin[r["payload"]["decision_key"]]["payload"]["reason"],
            "decision": origin[r["payload"]["decision_key"]]["seq"],
        }
        for r in rows
        if r["kind"] == "fill"
    ][-60:][::-1]
    reasons = {}
    for r in rows:
        if r["kind"] == "decision" and r["account"] == names[0]:
            reason = r["payload"]["reason"]
            reasons[reason] = reasons.get(reason, 0) + 1
    return {
        "schema": 1,
        "mode": "paper",
        "run": run_id,
        "started_at": run["started_at"],
        "generated_at": time.time(),
        "policy": policy,
        "accounts": summaries,
        "history": history,
        "decisions": decisions,
        "trades": trades,
        "reasons": reasons,
        "journal": {"events": len(rows), "head": head, "verified": True},
    }


def publish():
    import httpx

    if os.getenv("ORACLE_PAPER_ENABLED") != "1":
        return {"state": "disabled"}
    token = os.getenv("ORACLE_PUBLIC_TOKEN")
    if not token:
        return {"state": "not_configured"}
    published = []
    for run_id in POLICIES:
        data = public_snapshot(run_id)
        if data is None:
            continue
        url = "https://crypto-oracle-public.developer-331.workers.dev/api/publish"
        try:
            response = httpx.post(
                url,
                content=packed(data),
                timeout=15,
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            )
            if response.status_code != 200:
                raise RuntimeError(f"Public paper export rejected (HTTP {response.status_code})")
        except httpx.HTTPError:
            raise RuntimeError("Public paper export unavailable") from None
        published.append({"run": run_id, "events": data["journal"]["events"]})
    return {"state": "published" if published else "waiting_for_run", "runs": published}
