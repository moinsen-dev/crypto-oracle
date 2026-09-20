import fcntl
import logging
import signal
import threading
from contextlib import contextmanager

from . import config
from .db import init, job_end, job_start
from .forecast import evaluate, generate
from .ingest import collect_feed, collect_prices
from .models import classify_news

log = logging.getLogger("oracle")


@contextmanager
def process_lock(name):
    config.DATA.mkdir(parents=True, exist_ok=True)
    with (config.DATA / (name + ".lock")).open("w") as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"Another {name} process is already running") from exc
        try:
            yield
        finally:
            fcntl.flock(file, fcntl.LOCK_UN)


def task(name, fn):
    job_start(name)
    try:
        result = fn()
        job_end(name, result)
        log.info("%s: %s", name, result)
        return True
    except Exception as exc:
        job_end(name, error=f"{type(exc).__name__}: {exc}")
        log.exception("%s failed", name)
        return False


def cycle():
    job_start("worker")
    results = []
    for source, url in config.FEEDS.items():
        results.append(task("feed:" + source, lambda s=source, u=url: collect_feed(s, u)))
    results.append(task("news-classifier", classify_news))
    for asset in config.ASSETS:
        results.append(task("prices:" + asset, lambda a=asset: collect_prices(a)))
    results.append(task("evaluation", evaluate))
    for asset in config.ASSETS:
        results.append(task("forecast:" + asset, lambda a=asset: generate(a)))
    job_end(
        "worker",
        {"ok": sum(results), "total": len(results)},
        error=None if all(results) else "Some collectors/models failed; see individual job status",
    )
    # The optional evaluator is a separate experiment; its outage must not stop price forecasts.
    from .jev import collect as collect_jev

    task("jev-news", collect_jev)
    from .paper import cycle as paper_cycle
    from .paper import publish as publish_paper

    task("paper-trading", paper_cycle)
    task("paper-publication", publish_paper)
    from .learning import cycle as learning_cycle
    from .public_forecasts import publish as publish_forecasts

    task("learning", learning_cycle)
    from .volband import cycle as volband_cycle

    task("volatility-band", volband_cycle)
    task("forecast-publication", publish_forecasts)
    # Weekly digest for the public site. This server never sees who receives it.
    from .newsletter import publish as publish_newsletter

    task("newsletter", publish_newsletter)
    return all(results)


def worker(once=False):
    init()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    with process_lock("worker"):
        while not stop.is_set():
            cycle()
            if once:
                break
            stop.wait(900)
