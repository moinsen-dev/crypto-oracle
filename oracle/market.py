"""Public, read-only order books. No exchange credentials or order placement exist here."""

import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email.utils import parsedate_to_datetime

import httpx

from . import config
from .db import digest

MAX_AGE = 45
MAX_SPREAD_BPS = 30
MAX_DIVERGENCE = 0.01


def positive(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("invalid_number")
    return value


def book(client, venue, asset):
    started = time.time()
    try:
        if venue == "coinbase":
            url = f"https://api.exchange.coinbase.com/products/{asset}-USD/book"
            params = {"level": 2 if asset != "USDT" else 1}
        elif venue == "kraken":
            url = "https://api.kraken.com/0/public/Depth"
            params = {"pair": ("XBT" if asset == "BTC" else asset) + "USD", "count": 25}
        else:
            url = "https://api.binance.com/api/v3/depth"
            params = {"symbol": asset + "USDT", "limit": 20}
        response = client.get(url, params=params)
        response.raise_for_status()
        raw = response.json()
        received = time.time()
        date = parsedate_to_datetime(response.headers["date"]).timestamp()
        payload = next(iter(raw["result"].values())) if venue == "kraken" else raw
        source_at = datetime.fromisoformat(payload["time"]).timestamp() if venue == "coinbase" else date
        if payload.get("auction_mode"):
            raise ValueError("auction")
        if not (-5 <= received - date <= MAX_AGE and -5 <= received - source_at <= MAX_AGE):
            raise ValueError("stale")
        if received - started > 10 or float(response.headers.get("age", 0)) > MAX_AGE:
            raise ValueError("stale")
        bids = [[positive(r[0]), positive(r[1])] for r in payload["bids"][:50]]
        asks = [[positive(r[0]), positive(r[1])] for r in payload["asks"][:50]]
        if not bids or not asks or bids[0][0] >= asks[0][0]:
            raise ValueError("crossed_or_empty")
        if bids != sorted(bids, reverse=True) or asks != sorted(asks):
            raise ValueError("unordered")
        return {
            "venue": venue,
            "asset": asset,
            "started_at": started,
            "received_at": received,
            "source_at": source_at,
            "bids": bids,
            "asks": asks,
            "error": None,
            "payload_hash": digest(raw),
        }
    except (
        httpx.HTTPError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        StopIteration,
        OverflowError,
    ) as exc:
        # Never retain provider error bodies or headers in the journal/public export.
        code = (
            str(exc)
            if isinstance(exc, ValueError)
            and str(exc) in {"invalid_number", "auction", "stale", "crossed_or_empty", "unordered"}
            else "unavailable"
        )
        return {
            "venue": venue,
            "asset": asset,
            "started_at": started,
            "received_at": time.time(),
            "source_at": None,
            "bids": [],
            "asks": [],
            "error": code,
            "payload_hash": None,
        }


def collect():
    started = time.time()
    requests = [(v, a) for a in config.ASSETS for v in ("coinbase", "kraken", "binance")]
    requests.append(("coinbase", "USDT"))
    with (
        httpx.Client(
            timeout=8, headers={"User-Agent": "CryptoOracle-paper/1", "Cache-Control": "no-cache"}
        ) as c,
        ThreadPoolExecutor(max_workers=5) as pool,
    ):
        values = list(pool.map(lambda pair: book(c, *pair), requests))
    result = {
        "started_at": started,
        "received_at": time.time(),
        "books": {f"{b['venue']}:{b['asset']}": b for b in values},
    }
    return {"id": digest(result), **result}


def fresh(value, now):
    return bool(
        value
        and not value["error"]
        and -5 <= now - value["source_at"] <= MAX_AGE
        and 0 <= now - value["received_at"] <= MAX_AGE
    )


def mid(value):
    return (value["bids"][0][0] + value["asks"][0][0]) / 2


def quality(snapshot, asset, now):
    books = snapshot["books"]
    cb, kr, bn = [books.get(f"{v}:{asset}") for v in ("coinbase", "kraken", "binance")]
    fx_book = books.get("coinbase:USDT")
    ok = {v: fresh(b, now) for v, b in zip(("coinbase", "kraken", "binance"), (cb, kr, bn))}
    fx = mid(fx_book) if fresh(fx_book, now) else None
    usd = {
        "coinbase": mid(cb) if ok["coinbase"] else None,
        "kraken": mid(kr) if ok["kraken"] else None,
        "binance": mid(bn) * fx if ok["binance"] and fx else None,
    }
    spread = (cb["asks"][0][0] / cb["bids"][0][0] - 1) * 10000 if ok["coinbase"] else None
    usd_agree = bool(
        usd["coinbase"] and usd["kraken"] and abs(usd["coinbase"] / usd["kraken"] - 1) <= MAX_DIVERGENCE
    )
    values = [v for v in usd.values() if v is not None]
    divergence = max(values) / min(values) - 1 if len(values) == 3 else None
    execution_ok = bool(usd_agree and spread <= MAX_SPREAD_BPS)
    checks = [{"code": f"{v}_fresh", "passed": state} for v, state in ok.items()]
    checks += [
        {"code": "usd_pair_agreement", "passed": usd_agree},
        {"code": "usdt_conversion", "passed": bool(fx and abs(fx - 1) <= 0.01)},
        {"code": "three_venue_agreement", "passed": divergence is not None and divergence <= MAX_DIVERGENCE},
        {"code": "spread", "passed": spread is not None and spread <= MAX_SPREAD_BPS},
    ]
    return {
        "checks": checks,
        "buy_ok": all(c["passed"] for c in checks),
        "execution_ok": execution_ok,
        "mark": (usd["coinbase"] + usd["kraken"]) / 2 if usd_agree else None,
        "fx": fx,
        "spread_bps": spread,
        "divergence": divergence,
        "prices": usd,
        "ask_depth_usd": sum(p * q for p, q in cb["asks"] if p <= cb["asks"][0][0] * 1.003)
        if ok["coinbase"]
        else None,
        "bid_depth_usd": sum(p * q for p, q in cb["bids"] if p >= cb["bids"][0][0] * 0.997)
        if ok["coinbase"]
        else None,
        "observed_at": snapshot["received_at"],
        "observation_id": snapshot["id"],
    }


def sweep(value, side, quantity, slippage):
    """All-or-none simulated market fill within 30 bps of best quote; no invented liquidity."""
    levels = value["asks"] if side == "buy" else value["bids"]
    remaining, gross = quantity, 0.0
    for price, available in levels:
        if abs(price / levels[0][0] - 1) > 0.003:
            break
        take = min(remaining, available)
        gross += price * take
        remaining -= take
        if remaining <= quantity * 1e-10:
            return gross * (1 + slippage if side == "buy" else 1 - slippage)
    return None
