# Prospective paper-trading experiment

Running on the AX41 since **2026-09-18 09:56:07 UTC**, run `paper-v1-12b50e70aff6`.
Public view: https://cryptooracle.moinsen.dev/paper-portfolio/

This is virtual USD accounting. There are no broker credentials, real-order endpoints, leverage, shorts or transfers of real money. Manual holdings and the original forecast/fusion experiment remain separate.

## Second experiment: common start

`paper-v2-a782a0f058cb`, activated on **2026-09-18 at 15:32:42 UTC**, adds an independent prospective comparison. V1 continues with its original policy and journal; V2 never imports its holdings, profits or past decisions. Each V2 account receives a new virtual USD 10,000 at a common inception.

V2 targets USD 2,000 in each of BTC, ETH and SOL and USD 4,000 cash. The setup ignores forecast direction and the JEV veto deliberately: it is a fixed common starting allocation, not an AI-generated trade. Forecasts and news are recorded as context. All market-data, execution, budget and allocation gates still apply. All nine orders use the same decision observation and then the same **new** execution observation, identical per-coin quantities, assumed fees and slippage. They commit in one database transaction, or all are cancelled. A process interruption cannot leave one account partly initialized. Failed setup attempts retry at the next hourly decision with new prices; no historical fills are invented. The quantity reserve and costs leave actual initial investment slightly below 60%.

After initialization the active strategies use the original buy/exit rules below, including the six-hour regular-trade cooldown measured from their actual initial fills. Stops and allocation reductions can act earlier. The reference holds. A durable initialization event prevents sold positions from being seeded again. The public view separates the three setup buys per account from later trades.

V2 changes only the version and initial allocation policy. It does not lower thresholds to chase the observed V1 rally. It tests management of equal initial holdings; later exposure and paths can still differ, and common inception does not by itself establish a causal JEV benefit. Compare portfolios within a run. V1 and V2 start at different market times and their total returns are not directly comparable.

Enable alongside V1 using `ORACLE_PAPER_V2_ENABLED=1` in the existing worker (also requires `ORACLE_PAPER_ENABLED=1`). Disabling only V2 pauses its decisions and valuations, while V1 continues. Re-enabling resumes the same ledger. Never launch another worker. Public snapshots are retained per run; `/api/paper` returns the latest experiment, `/api/paper/runs` lists published runs, and `/api/paper?run=RUN_ID` selects one explicitly.

## Third experiment: a fixed trend rule

`paper-v3-a30412605673` is a separate prospective run with its own deposits, journal and hash chain. It uses **no forecast, no news and no fitted parameter**. Its rule was frozen from the published backtest on the [evidence page](https://cryptooracle.moinsen.dev/evidence/) (`crypto-oracle study`) before the run began; the backtest halved the deepest loss at similar growth and did not earn more. This run tests that prospectively. It is not enabled until the operator sets the flag below.

Three accounts, USD 10,000 each: `trend`, `rebalanced` and `reference`.

- **Signal.** At each completed daily close (the Binance hourly candle closing at 00:00 UTC) the rule compares that close with the closes exactly 7, 14, 28 and 56 days earlier. The share of positive comparisons (0, ¼, ½, ¾, 1) times 20% is the wanted weight per coin; the rest is cash. All five closes must already be in the database. A missing close blocks the trend account with `trend_input_missing`; nothing is interpolated and yesterday's signal is not reused. Later intraday candles never enter today's signal.
- **Acting.** Decisions are recorded hourly like the other runs. An account acts only when current and wanted weights differ by more than five points in total, decided once per account and hour before any of its orders moves the weights, and at most once per coin and UTC day (a cancelled order may retry within the day). Buys respect the 60% crypto and 25% per-coin limits; orders under USD 25 are skipped. Execution, costs, order age and the seven market checks are identical to the first two runs.
- **Comparisons.** `rebalanced` always wants 20% per coin and follows the same five-point and once-per-day rules, which is the benchmark the backtest used. `reference` buys 20% per coin once and holds; its purchase is retried hourly until it has actually filled, so a thin book at the start cannot leave the benchmark under-invested.
- **Deliberately absent.** No position stop and no drawdown brake: the backtested rule had neither, and adding them would test a different rule. There is no common atomic start either; each account follows its own rule from the first hour, so the trend account may begin partly or fully in cash.

Decision reasons: `trend_up`, `trend_down`, `rebalance`, `reference_entry`, `reference_hold`, `within_band`, `cooldown`, `allocation_limit`, `data_quality`, `execution_invalid`, `trend_input_missing`, `pending_order`. Each decision stores the five closes with their payload hashes, the share, the wanted and the current weight.

Enable with `ORACLE_PAPER_V3_ENABLED=1` next to `ORACLE_PAPER_ENABLED=1` in the existing single worker. **Deploy the website first**: the public schema must know the third run, its accounts and its frozen rule (`lookback_days`, `asset_weight`, `total_cap`, `rebalance_band` are checked literally) before the server publishes it. Disabling the flag pauses only this run; re-enabling continues the same ledger. One month of this run will contain at most a handful of trend changes. It can show that the machinery works and what the rule costs; it cannot confirm or refute a drawdown benefit that the backtest measured over two long declines in six years.

## Explained trades

Every published trade carries the `reason` of the decision behind it and that decision's journal number. The export keeps the 90 most recent decisions **plus** up to 40 older decisions that ended in a fill, so hours of later holds no longer push the explanation of a trade out of the public window. The public schema accepts a trade reason only together with its decision, and when that decision is in the snapshot, account, coin, side, reason and execution price must match it. Snapshots written before this change remain valid.

**A label that was wrong in the first days.** A sell reason names what set the quantity. A stop or a negative forecast sells the whole position; `allocation_limit` is a trim back to a cap. The first version named `allocation_limit` whenever a cap was exceeded by any amount, even when the forecast had triggered a full exit. Coins are decided in a fixed order, so the first coin of such a round carried the wrong label: the two BTC sales of 18 September 2026, 22:06 UTC in the second experiment (journal entries 449 for `news-guarded` and 458 for `price-only`) sold the entire position on an expected return of −0.67% against an exit threshold of about −0.58%, exactly like the ETH and SOL sales in the same minute, which are labelled `negative_forecast`. Actions, quantities and prices were never affected. Recorded entries are not rewritten; the correction of 20 September 2026 applies to every entry written after it reached the research server.

## Fixed policies

`oracle/paper.py:POLICY` is hashed into the run identifier and stored at inception. Changing its financial parameters creates a separate run, with a separate history and deposit; do not combine its performance with an earlier run. Preserve the source archive alongside each experiment. Fixes to presentation or enforcement of existing limits do not rewrite past events.

- Each of `news-guarded`, `price-only`, and `reference` starts with its own virtual USD 10,000 at the same timestamp. Cash is an additional constant USD 10,000 baseline.
- Both active policies use eligible, already-issued TimesFM 24-hour forecasts. USD target = forecast USDT price × observed Coinbase USDT/USD midpoint. Gross return is measured against the contemporary Coinbase USD midpoint.
- Entry hurdle = two assumed fees of 0.10%, two slippage allowances of 0.05%, the observed spread, plus the largest of 0.25%, 20% of trailing daily volatility, and 5% of log(raw upper/lower forecast interval). These heuristic thresholds and raw intervals are not calibrated success probabilities.
- Each signal-driven buy spends at most 5% of equity (after V2's common setup). Scale this down by `min(1, 0.03 / daily_volatility)`. Allocation caps: 25% per asset, 60% total crypto. Minimum order budget: USD 25. Six-hour cooldown per asset after regular trades; risk reduction can bypass it.
- Sell an active position on a 6% loss against average acquisition cost including fees, reduce excessive allocations, or exit when the gross forecast return falls below `-(0.003 + margin/2)` after the cooldown. Orders still require valid executable quotes.
- An observed reliable drawdown of 8% permanently latches the buy brake for that active policy. Valuation cycles enforce the brake even between hourly decisions; later price recovery does not reset it. No automatic restart of risk taking in that version.
- `news-guarded` applies an additional veto: a deduplicated headline from the last six hours has asset relevance and materiality scores >=0.70, negative tone and an event classified as security, regulation, network or exchange. Its publication, observation and JEV evaluation must all precede the decision. No sentiment-to-price multiplier. Missing JEV evidence is explicitly unknown and does not disable the bounded price-only part of the experiment. Existing JEV rate limits and request budgets remain unchanged.
- In V1 the reference attempts one entry per asset with up to 20% of initial capital, then holds without rebalancing or the active policies' stops. An unfilled entry is not retrospectively repaired. Execution and liquidity constraints can keep its actual allocation below 60%.

Decision checks are hourly in the existing single worker. Market observations, valuations, risk-brake checks and publication happen on its roughly 15-minute cycle. The comparison uses the same inception and assumptions, but execution times, exposure and paths can differ; it does not isolate a causal JEV effect.

## Data quality and simulated execution

Public Coinbase USD books are checked against Kraken USD books and Binance USDT books, with explicit USDT/USD conversion. Freshness limit: 45 seconds, using observation and available source/HTTP timestamps; request duration <=10 seconds. Coinbase auction books, malformed/non-finite values, empty/crossed/unordered books and stale responses fail. HTTP timestamps for Kraken/Binance are delivery evidence, not a guarantee of market truth.

New buys require all three sources, <=1% converted price divergence, USDT within 1% of USD parity and Coinbase spread <=30 bps. Reducing sales require fresh Coinbase/Kraken agreement and an executable Coinbase book. Marks use the two agreeing USD venues; otherwise last marks are retained and identified as unreliable. This cannot prove that every historical Binance input or every news statement is true.

The input artifact hash, pinned model revision, full consecutive 512-hour closing-price history, positive finite closes, finite nonnegative volumes, input observation/issue times and valid raw forecast interval are checked. No historical forecasts or hindsight news are used to backfill decisions.

A persisted order is filled only from a **new request started after its decision**. Walk the visible Coinbase book within 30 bps of the best quote, add 0.05% adverse slippage and charge 0.10% of notional. Quantity is fixed at decision and its USD budget includes cost and movement allowances. Cash, holdings, data and risk caps are checked again under a SQLite write transaction. All-or-none fills; insufficient depth, risk changes or an order age over 120 seconds cause an immutable cancellation. These are simulation assumptions, not the operator's actual fee tier. Queue priority, full market impact, exchange lot-size rules and real-account behaviour are not reproduced.

## Journal and public boundary

Additive SQLite tables: `paper_runs`, `paper_observations`, `paper_events`. SQL triggers reject updates/deletes. Unique event keys make deposits, hourly decisions, settlements and valuation slots idempotent. Cash, units, acquisition cost, fees and realised P/L are derived from immutable deposits/fills. Every event links its predecessor with SHA-256; export verifies the full chain. Server-admin tampering or false source data cannot be ruled out by this chain alone.

The public export contains only these virtual accounts, aggregate metrics, up to 30 calendar days of hourly chart values, 90 recent decisions and 60 recent fills. The full history and original books remain in the private research database. No manual holdings, raw titles/URLs, visitor data, credentials or private endpoints are included. `website/src/lib/paper-schema.mjs` rejects unknown nested fields, inconsistent balances, non-finite values and future decision inputs before accepting a publication.

The AX41 pushes to the authenticated Cloudflare `/api/publish` endpoint. A dedicated D1 database holds the latest public snapshot per experiment. Guarded SQL updates reject older publication timestamps, changed inception timestamps and journal-count regression within a run. Public `GET /api/paper` has no write capability, uses `no-store` and makes no call to the AX41. Visitors fetch this same-origin snapshot about once a minute while visible; filter choices remain in memory. Unavailable updates preserve the previous display with a warning; valuations older than 35 minutes or flagged unreliable are marked stale.

## Operation and recovery

```sh
# On the AX41, in ~/crypto-oracle
docker compose ps
docker compose exec worker crypto-oracle paper-report
docker compose exec worker crypto-oracle paper-publish
docker compose exec web crypto-oracle backup /data/paper-backup-UNIQUE.sqlite3
```

`paper-report` reads the journal; `paper-publish` only republishes. Neither runs trades or starts a second worker. The existing worker owns the collection/process lock. Its healthcheck now includes `paper-trading` and, when configured, `paper-publication`, in addition to research collection.

Server `.env`: `ORACLE_PAPER_ENABLED=1`. `ORACLE_PUBLIC_TOKEN` is present only in the worker, never the web container. Its matching Cloudflare secret is `PUBLISH_TOKEN`. Provision keys through private environment configuration; do not print, package or commit them. `.dev.vars` contains a separate local-only test value. Neither it nor local D1 data is deployed.

To pause the simulation, set `ORACLE_PAPER_ENABLED=0` in the private server `.env`, then `docker compose up -d --no-deps worker`. This stops paper decisions/valuations/publication while keeping the research collector running. The public timestamp becomes stale. Re-enable the same run to continue; expired pending orders are cancelled and deposits are not repeated. Never reset or delete the ledger to obtain a cleaner result.

Before the initial extension: consistent `/data/pre-paper-20260918.sqlite3`, `~/crypto-oracle/pre-paper-20260918-source.tar.gz`, and image `crypto-oracle:pre-paper-20260918` were retained. Prefer disabling paper trading over reverting the full research service. If reverting code, preserve the expanded database; its new tables are additive. Cloudflare's earlier static site can be restored with the recorded version in STATE.md without deleting D1 or the source journal.

## Evidence and limitations

See the [public development journal](https://cryptooracle.moinsen.dev/build-notes/) for dated deployment evidence; private operator records are excluded from this repository. The first run filled three reference purchases; both AI policies initially stayed in cash because the recorded entry hurdle was not met. No trade quota is forced, thresholds are not tuned to make a demonstration trade, and simulated fills are not proof of investment advantage.

API references checked for this implementation: [Coinbase books](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-book), [Kraken books](https://docs.kraken.com/api-reference/market-data/get-order-book), [Binance market data](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market), [paper/live limitations](https://docs.alpaca.markets/us/docs/paper-trading), [Cloudflare D1](https://developers.cloudflare.com/d1/worker-api/prepared-statements/).
