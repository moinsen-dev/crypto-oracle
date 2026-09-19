import argparse
import json
import logging
import sqlite3
import time
from pathlib import Path

from . import config
from .db import connect, init, job_end, job_start


def main():
    parser = argparse.ArgumentParser(description="CryptoOracle research service")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("init")
    run = subs.add_parser("worker")
    run.add_argument("--once", action="store_true")
    web = subs.add_parser("serve")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", default=8787, type=int)
    backtest = subs.add_parser("backtest")
    backtest.add_argument("--days", default=90, type=int)
    backtest.add_argument("--stride-hours", default=24, type=int)
    backtest.add_argument("--assets", nargs="+", choices=config.ASSETS, default=list(config.ASSETS))
    subs.add_parser("status")
    subs.add_parser("paper-report", help="Read the virtual portfolio and audit trail; no trading")
    subs.add_parser("paper-publish", help="Republish the bounded virtual-portfolio snapshot")
    subs.add_parser("forecast-report", help="Read the public forecast and learning snapshot")
    subs.add_parser("forecast-publish", help="Publish the allowlisted forecast journal; no model calls")
    jev_parser = subs.add_parser("jev", help="Evaluate recent headlines with JEV once")
    jev_parser.add_argument("--limit", type=int, default=1)
    report_parser = subs.add_parser("report")
    report_parser.add_argument("--scope", choices=("live", "backtest"), default="backtest")
    study_parser = subs.add_parser("study", help="Exploratory historical studies; no model calls")
    study_parser.add_argument("--refresh", action="store_true", help="Fetch the public daily closes again")
    backup = subs.add_parser("backup")
    backup.add_argument("destination", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    init()
    if args.command == "worker":
        from .runner import worker

        worker(args.once)
    elif args.command == "serve":
        import os

        import uvicorn

        if args.host not in ("127.0.0.1", "localhost", "::1") and not os.getenv("ORACLE_AUTH_PASSWORD"):
            parser.error("A non-loopback bind requires ORACLE_AUTH_PASSWORD")
        uvicorn.run("oracle.web:app", host=args.host, port=args.port, access_log=False)
    elif args.command == "backtest":
        from .forecast import evaluate, generate, metrics
        from .ingest import collect_prices
        from .runner import process_lock

        if not 1 <= args.days <= 730 or args.stride_hours < 1:
            parser.error("Use 1..730 days and stride >=1")
        # Share the worker lock: backtest cannot steal CPU or race live forecast issuance.
        with process_lock("worker"):
            job_start("backtest")
            try:
                end = int(time.time()) // 86400 * 86400 - max(config.HORIZONS) * 3600
                origins = list(range(end - args.days * 86400, end, args.stride_hours * 3600))
                for asset in args.assets:
                    collect_prices(asset, days=args.days + 30)
                    for idx, origin in enumerate(origins):
                        result = generate(asset, scope="backtest", origin=origin)
                        if idx % 10 == 0 or idx == len(origins) - 1:
                            print(json.dumps({"progress": f"{idx + 1}/{len(origins)}", **result}), flush=True)
                    evaluate()
                report = {
                    "created_at": int(time.time()),
                    "experiment": config.EXPERIMENT,
                    "kind": "exploratory retrospective, not an untouched confirmatory test",
                    "days": args.days,
                    "stride_hours": args.stride_hours,
                    "metrics": {h: metrics("backtest", h) for h in config.HORIZONS},
                }
                path = config.DATA / "backtest-report.json"
                path.write_text(json.dumps(report, indent=2))
                job_end("backtest", {"report": str(path), "days": args.days})
                print(json.dumps(report, indent=2))
            except Exception as exc:
                job_end("backtest", error=str(exc))
                raise
    elif args.command in ("paper-report", "paper-publish"):
        from .paper import public_snapshot, publish

        print(json.dumps(public_snapshot() if args.command == "paper-report" else publish(), indent=2))
    elif args.command in ("forecast-report", "forecast-publish"):
        from .public_forecasts import publish, snapshot

        print(json.dumps(snapshot() if args.command == "forecast-report" else publish(), indent=2))
    elif args.command == "jev":
        from .jev import collect

        print(json.dumps(collect(args.limit), indent=2))
    elif args.command == "status":
        with connect() as db:
            result = {
                "jobs": [dict(r) for r in db.execute("SELECT * FROM jobs")],
                "counts": {
                    t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("candles", "news", "forecasts", "evaluations")
                },
            }
        print(json.dumps(result, indent=2))
    elif args.command == "report":
        from .report import build_report

        result = build_report(args.scope)
        path = config.DATA / (args.scope + "-report.json")
        path.write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
    elif args.command == "study":
        from .study import build

        result = build(args.refresh)
        path = config.DATA / "study-report.json"
        path.write_text(json.dumps(result, indent=2))
        for universe in result["trend"]["universes"].values():
            universe.pop("weekly_curves")
        print(json.dumps(result, indent=2))
    elif args.command == "backup":
        if args.destination.exists():
            parser.error("Backup destination already exists")
        args.destination.parent.mkdir(parents=True, exist_ok=True)
        with connect() as source, sqlite3.connect(args.destination) as dest:
            source.backup(dest)
        print(f"Consistent SQLite backup written to {args.destination}")


if __name__ == "__main__":
    main()
