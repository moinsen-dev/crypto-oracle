"""Weekly public digest built from recorded evidence.

The research server assembles numbers and already-public headlines for one completed ISO week and pushes them to
the public site. It never receives, stores or sees a subscriber address; the list lives with the site only.
"""

import json
import math
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from . import config, paper
from .db import connect, digest, packed
from .jev import VERSION as JEV_VERSION

WEEK = 7 * 86400
SEND_AFTER = 7 * 3600  # Monday 07:00 UTC, once the week's last forecasts have had time to settle
HEADLINES = 5
CHANGES = Path(__file__).with_name("changes.json")


def init_schema():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS newsletter_issues (
          id TEXT PRIMARY KEY, published_at INTEGER NOT NULL, payload_hash TEXT NOT NULL, payload TEXT NOT NULL
        );
        """)
        for action in ("UPDATE", "DELETE"):
            db.execute(
                f"CREATE TRIGGER IF NOT EXISTS immutable_newsletter_issues_{action} BEFORE {action} "
                "ON newsletter_issues BEGIN SELECT RAISE(ABORT, 'Published issues are immutable'); END"
            )


def week(now):
    """The latest completed ISO week (Monday 00:00 UTC to Monday 00:00 UTC) and its identifier."""
    day = int(now // 86400)
    end = (day - (day + 3) % 7) * 86400  # 1970-01-01 was a Thursday
    year, number, _ = datetime.fromtimestamp(end - 86400, UTC).isocalendar()
    return end - WEEK, end, f"{year}-W{number:02d}"


def market(db, start, end):
    result = []
    for asset in config.ASSETS:
        closes = [
            r["close"]
            for r in db.execute(
                "SELECT close FROM candles WHERE asset=? AND ts>=? AND ts<=? ORDER BY ts", (asset, start, end)
            )
        ]
        if len(closes) < 2:
            continue
        result.append(
            {
                "asset": asset,
                "close": closes[-1],
                "change": closes[-1] / closes[0] - 1,
                "low": min(closes),
                "high": max(closes),
            }
        )
    return result


def forecasts(db, start, end):
    """24-hour live forecasts whose target fell inside the week, paired with 'the price stays the same'."""
    rows = [
        dict(r)
        for r in db.execute(
            "SELECT f.id,f.asset,f.model,f.origin,f.base,f.prediction,e.actual,e.absolute_log_error,e.covered,"
            "e.actual_hash FROM forecasts f JOIN evaluations e ON e.forecast_id=f.id WHERE f.experiment=? "
            "AND f.scope='live' AND f.horizon=24 AND f.model IN ('timesfm','persistence') AND f.target>=? "
            "AND f.target<? AND e.evaluated_at<=?",
            (config.EXPERIMENT, start, end, end + SEND_AFTER),
        )
    ]
    issued = db.execute(
        "SELECT COUNT(*) FROM forecasts WHERE experiment=? AND scope='live' AND model='timesfm' "
        "AND horizon=24 AND origin>=? AND origin<?",
        (config.EXPERIMENT, start, end),
    ).fetchone()[0]
    assets = []
    for asset in config.ASSETS:
        reference = {r["origin"]: r for r in rows if r["asset"] == asset and r["model"] == "persistence"}
        paired = [
            r
            for r in rows
            if r["asset"] == asset
            and r["model"] == "timesfm"
            and r["origin"] in reference
            and reference[r["origin"]]["actual_hash"] == r["actual_hash"]
        ]
        if not paired:
            continue
        ranked = sorted(paired, key=lambda r: r["absolute_log_error"])

        def call(r):
            return {
                "id": r["id"],
                "predicted": r["prediction"] / r["base"] - 1,
                "actual": r["actual"] / r["base"] - 1,
            }

        assets.append(
            {
                "asset": asset,
                "scored": len(paired),
                "miss": sum(r["absolute_log_error"] for r in paired) / len(paired),
                "last_price_miss": sum(reference[r["origin"]]["absolute_log_error"] for r in paired)
                / len(paired),
                "inside_band": sum(bool(r["covered"]) for r in paired),
                "days": len({r["origin"] // 86400 for r in paired}),
                "best": call(ranked[0]),
                "worst": call(ranked[-1]),
            }
        )
    return {"issued": issued, "assets": assets}


def portfolios(db, start, end):
    result = []
    for run_id, policy in paper.POLICIES.items():
        run = db.execute("SELECT started_at FROM paper_runs WHERE id=?", (run_id,)).fetchone()
        if run is None or run["started_at"] >= end:
            continue
        rows = [r for r in paper.events(db, run_id) if r["ts"] < end]
        decisions = {r["event_key"]: r for r in rows if r["kind"] == "decision"}
        accounts = []
        for account in paper.accounts(run_id):
            values = [r for r in rows if r["account"] == account and r["kind"] == "valuation"]
            if not values:
                continue
            before = [r for r in values if r["ts"] < start]
            opening = before[-1]["payload"]["equity"] if before else policy["starting_usd"]
            accounts.append(
                {
                    "id": account,
                    "equity": values[-1]["payload"]["equity"],
                    "change": values[-1]["payload"]["equity"] / opening - 1,
                    "since_start": values[-1]["payload"]["equity"] / policy["starting_usd"] - 1,
                }
            )
        trades = [
            {
                "at": r["ts"],
                "account": r["account"],
                "asset": r["asset"],
                "side": r["payload"]["side"],
                "reason": decisions[r["payload"]["decision_key"]]["payload"]["reason"],
            }
            for r in rows
            if r["kind"] == "fill" and r["ts"] >= start
        ]
        if accounts:
            result.append(
                {"run": run_id, "started_at": run["started_at"], "accounts": accounts, "trades": trades[-12:]}
            )
    return result


def news(db, start, end):
    """Headlines that were both seen and classified inside the week. Titles and links are already public."""
    rows = db.execute(
        "SELECT n.id,n.title,n.source,n.url,n.cluster,n.published_at,e.answers FROM news n "
        "JOIN news_evaluations e ON e.news_id=n.id WHERE e.version=? AND n.first_seen>=? AND n.first_seen<? "
        "AND e.evaluated_at<? ORDER BY n.first_seen",
        (JEV_VERSION, start, end, end),
    ).fetchall()
    seen, items = set(), []
    for r in rows:
        if r["cluster"] in seen or r["url"] in seen or not r["url"].startswith("https://"):
            continue
        seen.update((r["cluster"], r["url"]))
        answers = json.loads(r["answers"])
        assets = [a for a in config.ASSETS if answers[a]["probability"] >= 0.7]
        if not assets or answers["material"]["probability"] < 0.7:
            continue
        items.append(
            {
                "title": " ".join(r["title"].split())[:160],
                "source": r["source"],
                "url": r["url"],
                "published_at": r["published_at"],
                "assets": assets,
                "tone": answers["tone"]["choice"],
                "event": answers["event"]["choice"],
                "material": answers["material"]["probability"],
            }
        )
    items.sort(key=lambda x: (-x["material"], -(x["published_at"] or 0)))
    collected = db.execute(
        "SELECT COUNT(*) FROM news WHERE first_seen>=? AND first_seen<?", (start, end)
    ).fetchone()[0]
    return {
        "collected": collected,
        "classified": len(rows),
        "items": [{k: v for k, v in x.items() if k != "material"} for x in items[:HEADLINES]],
    }


def changes(start, end):
    entries = json.loads(CHANGES.read_text()) if CHANGES.exists() else []
    inside = [
        e for e in entries if start <= datetime.fromisoformat(e["date"]).replace(tzinfo=UTC).timestamp() < end
    ]
    return sorted(inside, key=lambda e: e["date"])[-6:]


def build_issue(now=None):
    start, end, ident = week(now or time.time())
    paper.init_schema()
    with connect() as db:
        issue = {
            "schema": 1,
            "id": ident,
            "start": start,
            "end": end,
            "market": market(db, start, end),
            "forecasts": forecasts(db, start, end),
            "portfolios": portfolios(db, start, end),
            "news": news(db, start, end),
            "changes": changes(start, end),
        }
    # A non-finite number would make the public boundary reject the whole issue; fail here with the reason.
    packed(issue)
    if not all(math.isfinite(m["change"]) for m in issue["market"]):
        raise ValueError("Non-finite market change")
    return issue


def publish(now=None):
    if os.getenv("ORACLE_NEWSLETTER_ENABLED") != "1":
        return {"state": "disabled"}
    token = os.getenv("ORACLE_PUBLIC_TOKEN")
    if not token:
        return {"state": "not_configured"}
    now = now or time.time()
    _, end, ident = week(now)
    if now < end + SEND_AFTER:
        return {"state": "waiting", "issue": ident}
    init_schema()
    with connect() as db:
        if db.execute("SELECT 1 FROM newsletter_issues WHERE id=?", (ident,)).fetchone():
            return {"state": "published", "issue": ident}
    issue = build_issue(now)
    if not issue["market"]:
        return {"state": "no_market_data", "issue": ident}
    try:
        response = httpx.post(
            "https://crypto-oracle-public.developer-331.workers.dev/api/newsletter/issue",
            content=packed({**issue, "generated_at": int(now)}),
            timeout=25,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        if response.status_code != 200:
            raise RuntimeError(f"Newsletter issue rejected (HTTP {response.status_code})")
    except httpx.HTTPError:
        raise RuntimeError("Newsletter publication unavailable") from None
    with connect() as db:
        db.execute(
            "INSERT OR IGNORE INTO newsletter_issues VALUES(?,?,?,?)",
            (ident, int(now), digest(issue), packed(issue)),
        )
    return {"state": "published", "issue": ident, "headlines": len(issue["news"]["items"])}
