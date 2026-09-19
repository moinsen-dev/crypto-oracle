"""Third paper run: a frozen slow trend filter against a rebalanced and a held benchmark.

No forecast, no news and no fitted parameter. The rule was fixed from the published study before this run began.
"""

import os
import time

from . import config, market
from .db import connect
from .paper import (
    POLICY_V3,
    RUN_V3,
    TREND_ACCOUNTS,
    append,
    balance,
    events,
    pending,
    remember,
    settle,
    start,
    valued,
)

DAY = 86400


def trend(db, asset, now, policy=POLICY_V3):
    """Share of trailing returns above zero, from completed daily closes that already exist in the database."""
    origin = int(now // DAY) * DAY
    wanted = [origin] + [origin - days * DAY for days in policy["lookback_days"]]
    found = {
        r["ts"]: r
        for r in db.execute(
            f"SELECT ts,close,payload_hash FROM candles WHERE asset=? AND ts IN ({','.join('?' * len(wanted))})",
            (asset, *wanted),
        )
    }
    if len(found) != len(wanted):
        return None, "trend_input_missing"
    last = found[origin]
    lookbacks = [
        {
            "days": days,
            "close": found[origin - days * DAY]["close"],
            "hash": found[origin - days * DAY]["payload_hash"],
            "positive": last["close"] > found[origin - days * DAY]["close"],
        }
        for days in policy["lookback_days"]
    ]
    return {
        "origin": origin,
        "close": last["close"],
        "hash": last["payload_hash"],
        "lookbacks": lookbacks,
        "share": sum(x["positive"] for x in lookbacks) / len(lookbacks),
    }, None


def targets(account, signals, policy=POLICY_V3):
    """Wanted weight per coin, or None while a trend input is missing."""
    if account != "trend":
        return {a: policy["asset_weight"] for a in config.ASSETS}
    if any(signals[a][0] is None for a in config.ASSETS):
        return None
    return {a: policy["asset_weight"] * signals[a][0]["share"] for a in config.ASSETS}


def plan(state, valuation, quality, wanted, act, account, asset, now, entered, error, policy=POLICY_V3):
    pos = state["positions"][asset]
    qty, nav, mark = pos["quantity"], valuation["equity"], quality["mark"]
    base = {"action": "hold", "reason": "within_band", "side": None, "quantity": 0.0, "budget": 0.0}
    if account == "reference" and entered:
        return {**base, "reason": "reference_hold"}
    if wanted is None:
        return {**base, "action": "blocked", "reason": error or "trend_input_missing"}
    if not valuation["fresh"] or mark is None:
        return {**base, "action": "blocked", "reason": "data_quality"}
    # The rule is daily: one fill per coin and UTC day. A cancelled order may try again within the day.
    if pos["last_trade"] and int(pos["last_trade"] // DAY) == int(now // DAY):
        return {**base, "reason": "cooldown"}
    if not act:
        return base
    gap = wanted[asset] * nav - qty * mark
    # Both benchmarks enter once; only later trades of the rebalanced one are rebalancing.
    moved = None if account == "trend" else "rebalance" if entered else "reference_entry"
    if gap <= -policy["min_order_usd"]:
        if not quality["execution_ok"]:
            return {**base, "action": "blocked", "reason": "execution_invalid"}
        quantity = qty if wanted[asset] == 0 else min(qty, -gap / mark)
        return {
            **base,
            "action": "sell",
            "side": "sell",
            "quantity": quantity,
            "reason": moved or "trend_down",
        }
    if gap < policy["min_order_usd"]:
        return base
    if not quality["buy_ok"]:
        return {**base, "action": "blocked", "reason": "data_quality"}
    budget = min(gap, state["cash"] - nav * (1 - policy["total_cap"]), nav * policy["asset_cap"] - qty * mark)
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
        "reason": moved or "trend_up",
    }


def cycle(collector=None, clock=None):
    if os.getenv("ORACLE_PAPER_ENABLED") != "1" or os.getenv("ORACLE_PAPER_V3_ENABLED") != "1":
        return {"state": "disabled"}
    collector, clock = collector or market.collect, clock or time.time
    run_id, policy = RUN_V3, POLICY_V3
    start(clock(), run_id)
    snapshot = collector()
    remember(snapshot)
    with connect() as db:
        outstanding = pending(events(db, run_id))
    for order in outstanding:
        settle(order, snapshot, clock())
    for account in TREND_ACCOUNTS:
        # Whether to act is decided once per account and hour, before any of its three orders moves the weights.
        act = None
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
                signals = {a: trend(db, a, now, policy) for a in config.ASSETS}
                wanted = targets(account, signals, policy)
                if act is None and wanted is not None and value["fresh"] and value["equity"] > 0:
                    held = {
                        a: p["quantity"] * (value["marks"][a] or 0) / value["equity"]
                        for a, p in state["positions"].items()
                    }
                    act = sum(abs(wanted[a] - held[a]) for a in config.ASSETS) > policy["rebalance_band"]
                # The held benchmark keeps trying until its single purchase per coin has actually filled.
                entered = any(
                    r["account"] == account and r["asset"] == asset and r["kind"] == "fill" for r in rows
                )
                decision = plan(
                    state,
                    value,
                    qualities[asset],
                    wanted,
                    bool(act),
                    account,
                    asset,
                    now,
                    entered,
                    signals[asset][1],
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
                        "signal": {
                            "trend": signals[asset][0],
                            "target_weight": wanted[asset] if wanted else None,
                            "weight": state["positions"][asset]["quantity"]
                            * (value["marks"][asset] or 0)
                            / value["equity"]
                            if value["equity"] > 0
                            else 0.0,
                        },
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
        for account in TREND_ACCOUNTS:
            append(
                db,
                f"valuation:{int(now // 900)}:{account}",
                now,
                account,
                "valuation",
                valued(balance(rows, account, policy), qualities),
                run_id=run_id,
            )
    return {"state": "running", "run": run_id, "observation": snapshot["id"]}
