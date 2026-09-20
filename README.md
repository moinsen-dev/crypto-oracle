# CryptoOracle

A public technology proof of concept for crypto forecasting, timestamped news analysis and accountable paper trading.

**[Live website](https://cryptooracle.moinsen.dev/) · [Paper portfolios](https://cryptooracle.moinsen.dev/paper-portfolio/) · [Forecast journal](https://cryptooracle.moinsen.dev/forecasts/) · [How it was built](https://cryptooracle.moinsen.dev/build-notes/)**

CryptoOracle observes BTC, ETH and SOL, preserves each forecast before its target time, then compares the prediction with the observed outcome. Three virtual strategies make their decisions and evidence visible. No real orders are placed.

## What runs today

- **TimesFM 2.5:** 512 completed hourly log closes; 24-hour and 72-hour forecasts, pinned model revision, immutable inputs/outputs and persistence/momentum baselines.
- **News:** local FinBERT classification and optional JEV evaluation through Vercel AI Gateway. Publication, collection and classification times stay distinct. JEV can veto a simulated buy; it does not numerically revise a price forecast.
- **Virtual portfolios:** separate USD 10,000 accounts with costs, later execution quotes, allocation limits and an append-only journal. V2 gives all three accounts the same initial allocation; V1 remains a separate experiment.
- **Outcome checks:** exact target closes, Coinbase/Kraken references and same-hour USDT/USD conversion. Missing, revised or unverifiable evidence is excluded from the calibration learner without rewriting the original score.
- **Controlled learning:** a versioned calibration shadow waits for at least 120 qualified examples spanning 21 days. It preserves fitted artifacts and later receives a fixed 28-day comparison. It does not automatically change trading policies.
- **Public notebook:** an English Astro site on Cloudflare, including forecasts, outcomes, portfolio trails, the method and development history. No advertising, visitor analytics, external assets or public trading endpoint.

A working pipeline is not a demonstrated forecasting edge. The first exploratory historical study found that TimesFM did worse than persistence. The new learner is initially collecting evidence; improved prospective accuracy or profit has not been established. Hourly forecasts overlap and are not independent successes.

## Architecture

```text
Market candles + timestamped news
                  |
       Python research worker ---- FastAPI private dashboard
                  |
        SQLite WAL / immutable evidence
                  |
       authenticated, allowlisted exports
                  |
       Cloudflare D1 + read-only public APIs
                  |
             Astro website
```

The public site cannot query the private research database or call model services. Model weights, credentials, raw databases, manual holdings and private operational records are not included in this repository. Public test fixtures contain synthetic or already-published numeric research data.

| Directory | Purpose |
| --- | --- |
| `oracle/` | Collection, forecasting, evaluation, paper accounting, learning and private dashboard |
| `jev/` | Small pinned AI SDK adapter for structured headline evaluation |
| `tests/` | Data integrity, chronology, accounting and publication checks |
| `website/` | Astro pages, Cloudflare Worker, D1 migrations and public schema checks |
| `PAPER.md` | Frozen virtual-trading rules and their limitations |
| `LEARNING.md` | Learning contract, source checks and prospective comparison rules |
| `RESEARCH_FORECAST_LEARNING.md` | Primary-source research and related approaches |

## Local research service

Requires **Python 3.12**, [uv](https://docs.astral.sh/uv/), and network access for market data and the initial model downloads. JEV additionally needs Node.js 24 and your own Vercel AI Gateway key. The optional paid API is disabled by default.

```sh
git clone https://github.com/moinsen-dev/crypto-oracle.git
cd crypto-oracle
uv sync --frozen
cp .env.example .env
uv run crypto-oracle init
uv run crypto-oracle serve
```

Set a unique `ORACLE_AUTH_PASSWORD` in the private `.env`. The dashboard defaults to `http://127.0.0.1:8787`; it uses the configured HTTP Basic credentials. In a separate terminal, start **one** worker for this database:

```sh
uv run crypto-oracle worker
```

The first run downloads the pinned TimesFM and FinBERT weights. Missing model results remain missing; there is no substitute presented as TimesFM. The worker preserves gaps and does not invent historical predictions or missing news coverage.

Optional features are explicit in `.env.example`: `ORACLE_PAPER_ENABLED`, `ORACLE_PAPER_V2_ENABLED`, `ORACLE_PAPER_V3_ENABLED` (the frozen trend rule, see [PAPER.md](PAPER.md)), `ORACLE_LEARNING_ENABLED`, `ORACLE_VOLBAND_ENABLED` (the volatility-band shadow experiment, see [LEARNING.md](LEARNING.md)), `ORACLE_NEWSLETTER_ENABLED` (the weekly digest handed to the website; subscriber data never reaches this server, see [website/README.md](website/README.md)) and `ORACLE_JEV_ENABLED`. For JEV, first run `npm ci --prefix jev` and privately configure `AI_GATEWAY_API_KEY`. Its request cap counts failed attempts too and is not a monetary spending limit.

Useful read-only reports:

```sh
uv run crypto-oracle status
uv run crypto-oracle report --scope live
uv run crypto-oracle paper-report
uv run crypto-oracle forecast-report
uv run crypto-oracle newsletter-report
```

`uv run crypto-oracle newsletter-preview` mails the operator, and nobody else, a preview of the last seven days through the public site; it needs the publication token and records nothing.

`uv run crypto-oracle study` reproduces the exploratory field notes behind the public [evidence page](https://cryptooracle.moinsen.dev/evidence/): forecast skill at every stored path step, the raw model band against a volatility band, and a fixed-rule trend filter on public Binance daily closes since 2020, with delayed-execution, doubled-cost and ten-coin variants. It makes no model calls, writes `data/study-report.json` and caches the daily closes in `data/study-daily.json` (`--refresh` fetches them again). These are backtests, reported in full; none is a forward claim.

## Docker operation

After configuring `.env`:

```sh
docker compose up -d --build
docker compose ps
```

The web service and the single worker share the same persistent `oracle-data` volume. The web port binds to server loopback, not the public Internet. For remote access use your own verified SSH target, for example `ssh -N -L 8789:127.0.0.1:8787 USER@HOST`. Never launch a second worker against the same database.

Create consistent backups with `crypto-oracle backup DESTINATION` inside the container, and retain a separate copy outside the volume. Do not copy a live SQLite database without its WAL or replace a current ledger with an old backup during routine deployment. Health checks cover enabled research, paper and learning jobs; external monitoring and backups remain operator responsibilities.

## Public website

See [website/README.md](website/README.md) for local preview, deployment, D1 setup and the boundary between the public and private systems. The repository's Cloudflare configuration identifies the existing Moinsen deployment. For your own installation, use your own Worker, account, database, domain and operator details.

## Verification

```sh
uv run pytest -q
uv run ruff check oracle tests
npm ci --prefix jev
node --test jev/evaluate.test.mjs
cd website
npm ci
npm run check
npx tsc --noEmit
npm run build
```

Tests protect immutable evidence, point-in-time information, exact-target settlement, cash accounting, restart idempotency and the public data allowlist. Desktop/mobile browser and live deployment checks complement these checks; passing tests does not establish model accuracy or investment performance.

## Project and rights

A [Moinsen](https://www.moinsen.dev/en) project by Ulrich Diedrichsen, developed with Codex assistance. Model weights and third-party dependencies are not redistributed and retain their respective licences. No project-wide software licence has been granted by this publication.
