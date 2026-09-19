import calendar
import re
import time
from urllib.parse import urlsplit, urlunsplit

import feedparser
import httpx

from .db import connect, digest

HEADERS = {"User-Agent": "CryptoOracle/0.1 research-dashboard"}
ASSET_WORDS = {"BTC": r"\b(bitcoin|btc)\b", "ETH": r"\b(ethereum|ether|eth)\b", "SOL": r"\b(solana|sol)\b"}
EVENTS = {
    "Sicherheitsvorfall": r"hack|exploit|breach|stolen",
    "Regulierung": r"\bsec\b|regulat|legislat|lawsuit|\betf\b",
    "Netzwerk": r"upgrade|hard fork|mainnet|validator|outage",
    "Börse / Listing": r"listing|delist|exchange|\blists\b",
    "Markt": r"price|rally|selloff|surge|plunge|market",
}


def get(client, url, **kwargs):
    for attempt in range(3):
        try:
            r = client.get(url, **kwargs)
            r.raise_for_status()
            return r
        except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.NetworkError):
            if attempt == 2:
                raise
            time.sleep(2**attempt)


def store_candles(asset, rows, now):
    saved = 0
    with connect() as db:
        for row in rows:
            # Binance REST uses milliseconds; archives may use microseconds.
            raw_ts = int(row[0])
            start = raw_ts // (1_000_000 if raw_ts > 100_000_000_000_000 else 1000)
            ts = start + 3600
            close, volume = float(row[4]), float(row[5])
            if ts > now or start % 3600 or close <= 0 or volume < 0:
                continue
            content_hash = digest(row)
            db.execute(
                "INSERT OR IGNORE INTO candle_revisions VALUES(?,?,?,?,?,?)",
                (asset, ts, now, close, volume, content_hash),
            )
            db.execute(
                "INSERT INTO candles VALUES(?,?,?,?,?,?,?) ON CONFLICT(asset,ts) DO UPDATE "
                "SET close=excluded.close,volume=excluded.volume,payload_hash=excluded.payload_hash,"
                "observed_at=excluded.observed_at",
                (asset, ts, close, volume, "binance-spot-1h", now, content_hash),
            )
            saved += 1
    return saved


def collect_prices(asset, days=30):
    now = int(time.time())
    end = now // 3600 * 3600
    start = end - days * 86400
    with connect() as db:
        last = db.execute("SELECT MAX(ts) FROM candles WHERE asset=?", (asset,)).fetchone()[0]
    # Explicit history requests backfill; the normal collector follows the latest close.
    if last and days <= 30:
        start = last - 2 * 3600
    count = 0
    with httpx.Client(timeout=30, headers=HEADERS) as client:
        while start < end:
            rows = get(
                client,
                "https://api.binance.com/api/v3/klines",
                params={
                    "symbol": asset + "USDT",
                    "interval": "1h",
                    "startTime": start * 1000,
                    "endTime": end * 1000 - 1,
                    "limit": 1000,
                },
            ).json()
            if not rows:
                break
            count += store_candles(asset, rows, now)
            next_start = int(rows[-1][0]) // 1000 + 3600
            if next_start <= start:
                raise ValueError("Market pagination did not advance")
            start = next_start
            time.sleep(0.15)
    return {"asset": asset, "candles": count}


def canonical_url(url):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return None
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, "", ""))


def collect_feed(source, url):
    now = int(time.time())
    try:
        with httpx.Client(timeout=30, headers=HEADERS, follow_redirects=True) as client:
            raw = get(client, url).content
        feed = feedparser.parse(raw)
        if not feed.entries:
            raise ValueError("Feed returned no readable entries")
        count = 0
        with connect() as db:
            for entry in feed.entries:
                title = re.sub(r"<[^>]*>", "", entry.get("title", "")).strip()[:600]
                link = canonical_url(entry.get("link", ""))
                if not title or not link:
                    continue
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                published = calendar.timegm(published) if published else None
                assets = [a for a, pat in ASSET_WORDS.items() if re.search(pat, title, re.IGNORECASE)]
                if source == "Ethereum Blog" and "ETH" not in assets:
                    assets.append("ETH")
                event = next(
                    (name for name, pat in EVENTS.items() if re.search(pat, title, re.IGNORECASE)),
                    "Sonstiges",
                )
                normalized = " ".join(re.findall(r"[a-z0-9]+", title.lower()))
                h = digest(title)
                # Headline changes are separate immutable versions; never rewrite first_seen.
                ident = digest([link, h])
                c = db.execute(
                    "INSERT OR IGNORE INTO news(id,source,url,title,published_at,first_seen,"
                    "content_hash,cluster,assets,event_type) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        ident,
                        source,
                        link,
                        title,
                        published,
                        now,
                        h,
                        digest(normalized),
                        ",".join(assets),
                        event,
                    ),
                )
                count += c.rowcount
            db.execute(
                "INSERT OR REPLACE INTO source_polls VALUES(?,?,1,?)", (source, now, len(feed.entries))
            )
        return {"new": count, "entries": len(feed.entries)}
    except Exception:
        with connect() as db:
            db.execute("INSERT OR REPLACE INTO source_polls VALUES(?,?,0,0)", (source, now))
        raise
