"""Exploratory event study: what did Bitcoin do after which kind of headline?

A public historical corpus, not a forward claim. A headline enters only after a realistic delay, labels use the
headline text alone, every class is reported, and any rule is chosen on the years before SPLIT and judged on the
years after it. Returns are measured against the average of the same calendar month, so a bull year does not
make every headline look bullish.
"""

import csv
import json
import math
import re
import time
from collections import defaultdict
from itertools import pairwise

import httpx
import numpy as np

from . import config
from .study import HEADERS, get

CORPUS_URL = "https://huggingface.co/datasets/edaschau/bitcoin_news/resolve/main/BTC_match_title.csv"
START = 1514764800  # 2018-01-01
SPLIT = 1672531200  # 2023-01-01: rules are chosen before this day and judged after it
DELAY = 900  # the live feed sees a headline a median 13 minutes after publication
HORIZONS = (1, 4, 24, 72)
COST = 0.0015  # per side, the paper policy's fee plus slippage
MIN_EVENTS = 40

# What a headline is about. The first match wins; the order puts the rarer, more specific kinds first.
EVENTS = (
    (
        "security",
        r"\b(hack(ed|s|ers?)?|exploit(ed)?|stolen|theft|heist|breach(ed)?|drained|phishing|ransomware)\b",
    ),
    (
        "failure",
        (
            r"\b(bankrupt(cy)?|insolven\w+|collaps\w+|halts? withdrawals?|suspends? withdrawals?"
            r"|freezes? withdrawals?|liquidators?|chapter 11)\b"
        ),
    ),
    (
        "enforcement",
        (
            r"\b(ban(s|ned)?|crackdown|lawsuit|sues?|sued|charges?|charged|indict\w+|fraud|probe|investigat\w+"
            r"|subpoena|fined?|illegal|arrest(ed|s)?|guilty|sanction(s|ed)?)\b"
        ),
    ),
    ("etf", r"\b(etfs?|exchange[- ]traded)\b"),
    (
        "approval",
        r"\b(approv\w+|legal tender|legaliz\w+|greenlights?|licen[cs]e granted|wins? approval|clears? the way)\b",
    ),
    (
        "adoption",
        (
            r"\b(buys?|bought|purchas\w+|acquir\w+|adds?|treasury|accepts?|accepting|adopts?|adoption|integrat\w+"
            r"|partners?(hip)?|launch(es|ed)?|rolls? out|invests?|investment)\b"
        ),
    ),
    (
        "macro",
        r"\b(fed|fomc|powell|inflation|cpi|rate (hike|cut)s?|interest rates?|recession|yields?|tariffs?|jobs report)\b",
    ),
    ("network", r"\b(halving|hash ?rate|miners?|mining|difficulty|fork|upgrade|taproot|lightning)\b"),
)
# Headlines that report a move which has already happened carry momentum, not news.
ECHO = (
    r"\b(surg\w+|soar\w+|jump\w+|rall(y|ies|ied|ying)|spik\w+|plung\w+|tumbl\w+|slump\w+|crash\w+|plummet\w+"
    r"|sink\w+|slid\w+|slides?|drops?|dropped|falls?|fell|rises?|rose|climbs?|climbed|gains?|gained|loses?|lost"
    r"|hits?|tops?|topped|breaks?|record high|all[- ]time high|new high|new low|sell[- ]?off|rebound\w*|recover\w*)\b"
)
# Opinion, listicles and promotion: no event at all.
NOISE = (
    r"\b(should you|reasons? (to|why)|best (crypto|coins?|stocks?)|to buy now|price prediction|prediction"
    r"|technical analysis|price analysis|forecast|could|might|may|will .* ever|here'?s (why|what)|what to know"
    r"|explained|opinion|podcast|newsletter|sponsored|press release|top \d+|\d+ (things|ways|reasons|cryptos?))\b"
)


def folder():
    path = config.DATA / "news-study"
    path.mkdir(parents=True, exist_ok=True)
    return path


def hourly(refresh=False):
    """Completed BTCUSDT hourly closes since 2018, keyed by close time. Cached beside the research database."""
    cache = folder() / "btc-hourly.json"
    if cache.exists() and not refresh:
        return {int(k): v for k, v in json.loads(cache.read_text()).items()}
    rows, start, now = [], START * 1000, int(time.time())
    with httpx.Client(timeout=30, headers=HEADERS) as client:
        while True:
            page = get(
                client,
                "https://api.binance.com/api/v3/klines",
                params={"symbol": "BTCUSDT", "interval": "1h", "startTime": start, "limit": 1000},
            ).json()
            rows += page
            if len(page) < 1000:
                break
            start = page[-1][0] + 3600000
            time.sleep(0.15)
    closes = {r[6] // 1000 + 1: float(r[4]) for r in rows if r[6] // 1000 < now}
    cache.write_text(json.dumps(closes))
    return closes


def corpus(refresh=False):
    path = folder() / "BTC_match_title.csv"
    if not path.exists() or refresh:
        with httpx.stream("GET", CORPUS_URL, timeout=600, follow_redirects=True, headers=HEADERS) as response:
            response.raise_for_status()
            with path.open("wb") as out:
                for chunk in response.iter_bytes():
                    out.write(chunk)
    csv.field_size_limit(10**9)
    seen, rows = set(), []
    with path.open(newline="", encoding="utf-8") as handle:
        for r in csv.DictReader(handle):
            title = " ".join(r["title"].split())
            key = title.lower()
            at = int(float(r["time_unix"]))
            # Syndicated copies repeat a title; only its first appearance is an event.
            if at < START or not title or key in seen:
                continue
            seen.add(key)
            rows.append({"at": at, "title": title, "source": r["source"]})
    return sorted(rows, key=lambda r: r["at"])


def kind(title):
    text = title.lower()
    event = next((name for name, pattern in EVENTS if re.search(pattern, text)), "other")
    return event, bool(re.search(ECHO, text)), bool(re.search(NOISE, text))


def sentiments(rows, refresh=False):
    """The production FinBERT score (positive minus negative probability) for every headline. Cached by title."""
    cache = folder() / "finbert.json"
    known = json.loads(cache.read_text()) if cache.exists() and not refresh else {}
    todo = [r["title"] for r in rows if r["title"] not in known]
    if todo:
        from .models import sentiment_pipeline

        pipe = sentiment_pipeline()
        for i in range(0, len(todo), 512):
            batch = todo[i : i + 512]
            for title, scores in zip(
                batch, pipe(batch, top_k=None, truncation=True, max_length=64, batch_size=32), strict=True
            ):
                scores = {x["label"].lower(): float(x["score"]) for x in scores}
                known[title] = scores["positive"] - scores["negative"]
            cache.write_text(json.dumps(known))
    return known


def events(refresh=False):
    """One row per headline: when we could have acted, what kind it is, and what Bitcoin did before and after."""
    closes, rows = hourly(refresh), corpus(refresh)
    scores = sentiments(rows, refresh)
    months = defaultdict(lambda: defaultdict(list))
    for ts, close in closes.items():
        for h in HORIZONS:
            later = closes.get(ts + h * 3600)
            if later:
                months[time.strftime("%Y-%m", time.gmtime(ts))][h].append(math.log(later / close))
    normal = {m: {h: float(np.mean(v)) for h, v in per.items()} for m, per in months.items()}
    usual = {m: {h: float(np.mean(np.abs(v))) for h, v in per.items()} for m, per in months.items()}
    # The stricter yardstick: the move against what the last day's volatility already implies, compared with
    # other hours of the same month at the same time of day. News counts only for what it adds to that.
    ordered = sorted(closes)
    squared = {b: math.log(closes[b] / closes[a]) ** 2 for a, b in pairwise(ordered) if b - a == 3600}

    def surprise(ts, h):
        window = [squared.get(ts - k * 3600) for k in range(24)]
        later = closes.get(ts + h * 3600)
        if later is None or any(v is None for v in window) or not sum(window):
            return None
        return abs(math.log(later / closes[ts])) / math.sqrt(sum(window) * h / 24)

    slots = defaultdict(list)
    for ts in ordered:
        for h in HORIZONS:
            value = surprise(ts, h)
            if value is not None:
                slots[(time.strftime("%Y-%m", time.gmtime(ts)), ts // 3600 % 24, h)].append(value)
    typical = {k: float(np.mean(v)) for k, v in slots.items()}
    out = []
    for r in rows:
        base = (r["at"] + DELAY + 3599) // 3600 * 3600  # the first full hour after we could have seen it
        if base not in closes or base - 86400 not in closes:
            continue
        month = time.strftime("%Y-%m", time.gmtime(base))
        forward, size, extra = {}, {}, {}
        for h in HORIZONS:
            later = closes.get(base + h * 3600)
            if later:
                move = math.log(later / closes[base])
                forward[h] = move - normal[month][h]
                # How large the move was, whatever its direction, against the usual move of that month.
                size[h] = abs(move) / usual[month][h]
                value = surprise(base, h)
                if value is not None:
                    extra[h] = value / typical[(month, base // 3600 % 24, h)]
        if len(forward) < len(HORIZONS) or len(extra) < len(HORIZONS):
            continue
        event, echo, noise = kind(r["title"])
        score = scores[r["title"]]
        out.append(
            {
                **r,
                "base": base,
                "event": event,
                "echo": echo,
                "noise": noise,
                "sentiment": score,
                "tone": "negative" if score < -0.25 else "positive" if score > 0.25 else "neutral",
                "before": math.log(closes[base] / closes[base - 86400]),
                "after": forward,
                "size": size,
                "extra": extra,
            }
        )
    return out, closes


def interval(values, days, repeats=2000, seed=11):
    """Mean and a 95% interval that resamples whole days, because headlines of one day share one market."""
    by_day = defaultdict(list)
    for v, d in zip(values, days, strict=True):
        by_day[d].append(v)
    groups = [np.array(v) for v in by_day.values()]
    sums, counts = np.array([g.sum() for g in groups]), np.array([len(g) for g in groups])
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(groups), size=(repeats, len(groups)))
    means = sums[picks].sum(axis=1) / counts[picks].sum(axis=1)
    return float(np.mean(values)), [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def summarise(rows, horizon):
    values = [r["after"][horizon] for r in rows]
    days = [r["base"] // 86400 for r in rows]
    mean, ci = interval(values, days)
    size, size_ci = interval([r["size"][horizon] for r in rows], days)
    extra, extra_ci = interval([r["extra"][horizon] for r in rows], days)
    return {
        "n": len(rows),
        "days": len(set(days)),
        "mean": mean,
        "ci95": ci,
        "clear": ci[0] > 0 or ci[1] < 0,
        "size": size,
        "size_ci95": size_ci,
        "size_clear": size_ci[0] > 1 or size_ci[1] < 1,
        "extra": extra,
        "extra_ci95": extra_ci,
        "extra_clear": extra_ci[0] > 1 or extra_ci[1] < 1,
        "before_24h": float(np.mean([r["before"] for r in rows])),
    }


def classes(rows):
    """Every way we look at a headline. A row can sit in several groups; each group is reported, none is hidden."""
    groups = defaultdict(list)
    for r in rows:
        groups["all headlines"].append(r)
        groups["noise (opinion, listicle, prediction)" if r["noise"] else "not noise"].append(r)
        if r["noise"]:
            continue
        groups["echo of a move" if r["echo"] else "no move in the headline"].append(r)
        groups[f"tone:{r['tone']}"].append(r)
        groups[f"event:{r['event']}"].append(r)
        groups[f"event:{r['event']} · tone:{r['tone']}"].append(r)
        if not r["echo"]:
            groups[f"fresh · event:{r['event']}"].append(r)
            groups[f"fresh · event:{r['event']} · tone:{r['tone']}"].append(r)
    return groups


def rule_test(triggers, closes, horizon, flat):
    """Hold Bitcoin, but step aside (flat) or hold only then (not flat) for `horizon` hours after each trigger."""
    hours = sorted(t for t in closes if t >= SPLIT and t - 3600 in closes)
    triggers = sorted(triggers)
    active, j, until = [], 0, 0
    for t in hours:
        while j < len(triggers) and triggers[j] <= t - 3600:
            until = max(until, triggers[j] + horizon * 3600)
            j += 1
        active.append(t - 3600 < until)
    returns = np.array([math.log(closes[t] / closes[t - 3600]) for t in hours])
    active = np.array(active)
    held = ~active if flat else active
    switches = int(np.abs(np.diff(held.astype(int))).sum())
    curve = np.cumsum(returns * held) - COST * np.cumsum(np.r_[0, np.abs(np.diff(held.astype(int)))])
    reference = np.cumsum(returns)

    def drawdown(c):
        return float(1 - math.exp(np.min(c - np.maximum.accumulate(c))))

    return {
        "hours": len(hours),
        "hours_held": int(held.sum()),
        "switches": switches,
        "return": float(math.exp(curve[-1]) - 1),
        "max_drawdown": drawdown(curve),
        "hold_return": float(math.exp(reference[-1]) - 1),
        "hold_max_drawdown": drawdown(reference),
    }


def build(refresh=False):
    rows, closes = events(refresh)
    before, after = [r for r in rows if r["base"] < SPLIT], [r for r in rows if r["base"] >= SPLIT]
    fit, test = classes(before), classes(after)
    table = []
    for name in sorted(fit):
        if len(fit[name]) < MIN_EVENTS or len(test.get(name, [])) < MIN_EVENTS:
            continue
        for h in HORIZONS:
            a, b = summarise(fit[name], h), summarise(test[name], h)
            table.append(
                {
                    "class": name,
                    "horizon": h,
                    "fit": a,
                    "test": b,
                    # An effect counts only when both periods are clear of zero and agree in sign.
                    "holds": a["clear"] and b["clear"] and (a["mean"] > 0) == (b["mean"] > 0),
                    "size_holds": a["size_clear"] and b["size_clear"] and (a["size"] > 1) == (b["size"] > 1),
                    "extra_holds": a["extra_clear"]
                    and b["extra_clear"]
                    and (a["extra"] > 1) == (b["extra"] > 1),
                }
            )
    # Rules are picked from the years before the split alone, then run once on the years after it.
    chosen = sorted(
        (x for x in table if x["fit"]["clear"] and x["class"] != "all headlines"),
        key=lambda x: -abs(x["fit"]["mean"]) / (x["fit"]["ci95"][1] - x["fit"]["ci95"][0]),
    )[:6]
    rules = []
    for x in chosen:
        flat = x["fit"]["mean"] < 0
        rules.append(
            {
                "class": x["class"],
                "horizon": x["horizon"],
                "fit_mean": x["fit"]["mean"],
                "action": "step aside" if flat else "hold only then",
                **rule_test([r["base"] for r in test[x["class"]]], closes, x["horizon"], flat),
            }
        )
    report = {
        "schema": 1,
        "kind": "exploratory historical event study; every class reported; rules chosen before the split; not a forward claim",
        "created_at": int(time.time()),
        "corpus": CORPUS_URL,
        "delay_seconds": DELAY,
        "split": SPLIT,
        "headlines": {"fit": len(before), "test": len(after)},
        "tests": len(table),
        "expected_false_positives": round(len(table) * 0.05 * 0.05 * 0.5, 2),
        "table": table,
        "rules": rules,
    }
    (config.DATA / "news-study-report.json").write_text(json.dumps(report, indent=2))
    return report
