import base64
import csv
import io
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import config
from .db import connect, init
from .forecast import metrics
from .laya_news import MODEL as LAYA_MODEL
from .laya_news import VERSION as LAYA_VERSION

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app):
    init()
    yield


app = FastAPI(title="CryptoOracle", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def security(request: Request, call_next):
    password = os.getenv("ORACLE_AUTH_PASSWORD", "")
    if password and request.url.path != "/healthz":
        try:
            scheme, token = request.headers.get("authorization", "").split(" ", 1)
            user, supplied = base64.b64decode(token, validate=True).decode().split(":", 1)
            valid = scheme.lower() == "basic" and secrets.compare_digest(
                user.encode(), os.getenv("ORACLE_AUTH_USER", "oracle").encode()
            )
            valid = valid and secrets.compare_digest(supplied.encode(), password.encode())
        except (ValueError, UnicodeError):
            valid = False
        if not valid:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="CryptoOracle"'})
    if request.method in ("POST", "PUT", "DELETE"):
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-origin mutation rejected"}, status_code=403)
        if request.method != "DELETE" and "application/json" not in request.headers.get("content-type", ""):
            return JSONResponse({"detail": "JSON required"}, status_code=415)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    return response


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/healthz")
def health():
    with connect() as db:
        db.execute("SELECT 1").fetchone()
    return {"ok": True}


@app.get("/api/paper")
def paper_portfolio():
    from .paper import public_snapshot

    return public_snapshot() or {"mode": "paper", "state": "not_started"}


@app.get("/api/dashboard")
def dashboard(
    asset: Literal["BTC", "ETH", "SOL"] = "BTC",
    horizon: Literal["24", "72"] = "24",
    scope: Literal["live", "backtest"] = "live",
):
    horizon = int(horizon)
    now = int(time.time())
    with connect() as db:
        holdings = {r["asset"]: dict(r) for r in db.execute("SELECT * FROM holdings")}
        assets = []
        for a in config.ASSETS:
            candle = db.execute(
                "SELECT ts,close FROM candles WHERE asset=? ORDER BY ts DESC LIMIT 1", (a,)
            ).fetchone()
            old = (
                db.execute(
                    "SELECT close FROM candles WHERE asset=? AND ts=?", (a, candle["ts"] - 86400)
                ).fetchone()
                if candle
                else None
            )
            assets.append(
                {
                    "asset": a,
                    "price": candle["close"] if candle else None,
                    "price_at": candle["ts"] if candle else None,
                    "change": candle["close"] / old["close"] - 1 if old else None,
                    "holding": holdings.get(a),
                }
            )
        chart = [
            dict(r)
            for r in db.execute(
                "SELECT ts,close FROM candles WHERE asset=? ORDER BY ts DESC LIMIT 168", (asset,)
            )
        ][::-1]
        last_origin = db.execute(
            "SELECT MAX(origin) FROM forecasts WHERE asset=? AND scope='live' AND experiment=?",
            (asset, config.EXPERIMENT),
        ).fetchone()[0]
        latest = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM forecasts WHERE asset=? AND origin=? "
                "AND horizon=? AND scope='live' AND experiment=?",
                (asset, last_origin, horizon, config.EXPERIMENT),
            )
        ]
        for r in latest:
            for key in ("path", "features", "provenance"):
                r[key] = json.loads(r[key])
            r["provenance"].pop("input_candles", None)
        news = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM (SELECT *,ROW_NUMBER() OVER(PARTITION BY url "
                "ORDER BY first_seen DESC,rowid DESC) AS version_rank FROM news) AS current_news "
                "WHERE version_rank=1 AND (instr(','||assets||',',','||?||',')>0 OR EXISTS "
                "(SELECT 1 FROM news_evaluations e WHERE e.news_id=current_news.id AND e.version=? "
                "AND json_extract(e.answers,?)>=0.5)) "
                "AND (published_at IS NULL OR published_at>?) "
                "ORDER BY first_seen DESC,published_at DESC LIMIT 30",
                (asset, LAYA_VERSION, "$." + asset + ".probability", now - 7 * 86400),
            )
        ]
        for item in news:
            annotation = db.execute(
                "SELECT answers,evaluated_at,version FROM news_evaluations WHERE news_id=? AND version=?",
                (item["id"], LAYA_VERSION),
            ).fetchone()
            item["laya"] = (
                {
                    "answers": json.loads(annotation["answers"]),
                    "evaluated_at": annotation["evaluated_at"],
                    "version": annotation["version"],
                }
                if annotation
                else None
            )
        laya_totals = db.execute(
            "SELECT COUNT(*),AVG(latency_ms) FROM news_evaluations WHERE version=?",
            (LAYA_VERSION,),
        ).fetchone()
        journal = [
            dict(r)
            for r in db.execute(
                "SELECT f.id,f.asset,f.model,f.origin,f.issued_at,f.target,f.base,f.prediction,"
                "f.lower,f.upper,e.actual,e.absolute_log_error,e.covered "
                "FROM forecasts f LEFT JOIN evaluations e ON e.forecast_id=f.id "
                "WHERE f.asset=? AND f.horizon=? AND f.scope=? AND f.experiment=? "
                "ORDER BY f.origin DESC,f.model LIMIT 60",
                (asset, horizon, scope, config.EXPERIMENT),
            )
        ]
        jobs = [dict(r) for r in db.execute("SELECT * FROM jobs")]
        counts = {
            t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("candles", "news", "forecasts", "evaluations")
        }
        fusion_rows = db.execute(
            "SELECT COUNT(*),MIN(f.origin),MAX(f.origin) FROM forecasts f "
            "JOIN evaluations e ON e.forecast_id=f.id WHERE f.scope='live' "
            "AND f.asset=? AND f.horizon=? AND f.model='timesfm' AND f.experiment=? "
            "AND json_extract(f.features,'$.news_available')=1",
            (asset, horizon, config.EXPERIMENT),
        ).fetchone()
    return {
        "now": now,
        "experiment": config.EXPERIMENT,
        "quote": "USDT",
        "venue": "Binance spot",
        "assets": assets,
        "chart": chart,
        "forecasts": latest,
        "news": news,
        "journal": journal,
        "metrics": metrics(scope, horizon),
        "jobs": jobs,
        "counts": counts,
        "laya": {
            "evaluated": laya_totals[0],
            "mean_latency_ms": laya_totals[1],
            "model": LAYA_MODEL,
            "version": LAYA_VERSION,
        },
        "fusion": {
            "samples": fusion_rows[0],
            "required_samples": 120,
            "required_days": 21,
            "span_days": (fusion_rows[2] - fusion_rows[1]) / 86400 if fusion_rows[0] else 0,
        },
    }


class Holding(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    quantity: float = Field(ge=0, le=1e12)
    average_cost: float | None = Field(default=None, ge=0, le=1e12)


@app.put("/api/holdings/{asset}")
def save_holding(asset: str, holding: Holding):
    if asset not in config.ASSETS:
        raise HTTPException(404, "Unknown asset")
    with connect() as db:
        db.execute(
            "INSERT INTO holdings VALUES(?,?,?,?) ON CONFLICT(asset) DO UPDATE SET "
            "quantity=excluded.quantity,average_cost=excluded.average_cost,updated_at=excluded.updated_at",
            (asset, holding.quantity, holding.average_cost, int(time.time())),
        )
    return {"ok": True}


@app.delete("/api/holdings/{asset}")
def delete_holding(asset: str):
    if asset not in config.ASSETS:
        raise HTTPException(404, "Unknown asset")
    with connect() as db:
        db.execute("DELETE FROM holdings WHERE asset=?", (asset,))
    return {"ok": True}


@app.get("/api/export.csv")
def export(scope: Literal["live", "backtest"] = "live"):
    def records():
        with connect() as db:
            cursor = db.execute(
                "SELECT f.id,f.experiment,f.scope,f.asset,f.model,f.origin,f.issued_at,f.horizon,f.target,"
                "f.base,f.prediction,f.lower,f.upper,e.actual,e.absolute_log_error,e.covered,e.pinball "
                "FROM forecasts f LEFT JOIN evaluations e ON e.forecast_id=f.id "
                "WHERE f.scope=? ORDER BY f.origin",
                (scope,),
            )
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([col[0] for col in cursor.description])
            yield output.getvalue()
            for row in cursor:
                output.seek(0)
                output.truncate(0)
                writer.writerow(tuple(row))
                yield output.getvalue()

    return StreamingResponse(
        records(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="crypto-oracle-{scope}.csv"'},
    )
