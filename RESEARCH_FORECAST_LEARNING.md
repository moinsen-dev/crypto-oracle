# CryptoOracle: forecast accountability and controlled learning

Research date: 19 September 2026. Primary sources were checked on that date. This report proposes research changes; it does not activate another model, change a trading policy, or report a new performance result. Implementation status and proposed work are separated below.

The useful next step is a visible, immutable prediction scorecard and a controlled challenger process. Recording errors establishes accountability. Updating a small model from previously settled errors establishes actual learning. Better future performance remains a hypothesis that must survive comparison with persistence, the frozen model, and the market reference.

## What CryptoOracle already contains

The inspected repository already stores forecasts and evaluates them after target observations arrive. It records absolute log error, directional correctness, interval coverage and quantile loss, and pairs model results with persistence at matching origins. These are implemented capabilities, not evidence of predictive advantage. See [forecast evaluation](oracle/forecast.py), [database schema](oracle/db.py) and the previously documented findings in [STATE.md](STATE.md).

The existing [fusion implementation](oracle/fusion.py) also contains two prospective ridge residual models: market features alone, and the same features plus FinBERT news features. Training requires at least 120 eligible observations, a 21-day origin span and ten news IDs; the chronological 75/25 split purges training targets overlapping calibration origins. Labels must have been evaluated by the new forecast origin. Artifacts preserve training/calibration IDs and fitted parameters. These minimums permit an experiment to run; they do not establish adequate statistical power or justify promotion. Raw news IDs are also not a count of independent events.

TimesFM weights remain fixed. Re-running that model on a newer price window is inference, not retraining. The ridge layer can learn new coefficients once eligible data exists. JEV currently supplies paper-trading news context and a buy veto; it is not the numeric news feature source for these ridge corrections. Numerical JEV fusion would therefore be a separately versioned experiment. [System scope](README.md), [paper policy](PAPER.md).

## Make each prediction a testable claim

“Bitcoin −1.3% by tomorrow at 17:00” is incomplete without its reference price, venue, quote currency and precise target definition. The same predicted endpoint implies a different percentage when compared with a later market price. Store the originally displayed claim instead of recomputing its starting point during evaluation.

Recommended contract for the public scorecard:

| Field | Required meaning |
| --- | --- |
| Identity | Forecast ID, experiment, asset, model/checkpoint, configuration and prompt versions where applicable. |
| Time | Input cutoff, forecast origin, actual issue time, explicit target close time, and target observation/settlement time. Store UTC; display a labelled local timezone. |
| Market | Venue, instrument, quote currency, reference close and its input hash. A Binance BTC/USDT forecast and a Coinbase BTC/USD decision are distinct claims. |
| Prediction | Frozen price target, return from that reference, interval/quantiles and method. Record a later decision-time return separately if used. |
| Information set | Feature values, news-version IDs, first-seen and classification times, data-quality state and artifact ID. |
| Outcome | Exact target observation and hash, actual return from the original reference, signed and absolute error, direction, and interval result. |
| Status | Pending; target reached but valid data missing; evaluated; or excluded with a reason. Never turn missing observations into a successful forecast. |

Verify whether a provider labels candles by opening or closing time before presenting the due time. “Target reached” is insufficient when its required completed candle has not yet been observed. Preserve late-arriving or corrected outcomes as explicit versions rather than rewriting the original judgment.

For clarity, display simple returns as percentages and their difference in **percentage points**, while retaining log-return loss as the research metric. An illustrative prediction of −1.3% followed by +2.0% has a 3.3 percentage-point directional miss. That is not a claim about the actual result of our quoted forecast.

## Relevant existing work

### Price-model candidates

| Candidate | Verified primary-source facts | Recommendation for this PoC |
| --- | --- | --- |
| TimesFM 2.5 | Google documents 200M parameters, quantile forecasting and XReg covariates. Weights through 2.5 remain Apache-2.0. [Google repository](https://github.com/google-research/timesfm). | Keep the deployed checkpoint as the frozen comparison. Existing local deployment evidence supports CPU feasibility; it does not establish forecast skill. |
| TimesFM 3.0 | Google's current repository describes native multivariate and past-only covariate support, but explicitly restricts the default weights to non-commercial, non-production use. [Google repository](https://github.com/google-research/timesfm). | Do not treat it as an automatic upgrade for this public service. The general benchmark rankings do not establish Bitcoin profitability. |
| Chronos-Bolt Tiny | Amazon's model card specifies Apache-2.0 and explicitly supports `device_map="cpu"` through `BaseChronosPipeline`. [Official model card](https://huggingface.co/amazon/chronos-bolt-tiny). | Recommended first alternative foundation-model challenger: small, distinct from TimesFM and suitable for a bounded CPU trial. Measure latency, memory and skill locally before activation. |
| Chronos-2 | Amazon lists a 120M model with univariate, multivariate and covariate forecasting; its current API example uses `Chronos2Pipeline` and `predict_df`. The same repository lists Bolt Tiny at approximately 9M and Chronos-2 Small at 28M. [Amazon repository](https://github.com/amazon-science/chronos-forecasting). | A later challenger for aligned market and past news covariates. Never supply future news as if known. The larger feature space needs more usable history. |

CPU priority is an engineering recommendation, not a measured speed comparison: persistence and a small regularized correction first, Bolt Tiny second, richer multivariate models later. Pin dependency versions and checkpoint revisions when implementing each candidate. No package or model was installed or benchmarked during this research.

### Three closely related crypto studies

**CryptoTrade, Li et al., EMNLP 2024.** This is unusually close to our proposal: BTC/ETH/SOL, market and news analysts, a trading agent, and reflection over prior decisions and returns. Its published paper uses daily trading and selected 2023 bullish, sideways and bearish test periods. Reflection changes subsequent context; the experiment is zero-shot rather than model-weight fine-tuning. Crucially, the published conclusion reports improvement over tested neural time-series baselines, not general superiority over traditional signals. In the BTC bullish test, GPT-4o returns 28.47% against 39.66% for buy-and-hold. The authors identify the limited dataset and daily frequency as limitations. This supports testing a reflection component, not treating an articulate post-mortem as proof of learning or profit. [Published ACL paper, especially Tables 1–2 and Limitations](https://aclanthology.org/2024.emnlp-main.63.pdf).

**CryptoBERT, Kulakowski and Frasincar, 2023.** The authors adapt BERTweet to cryptocurrency social text and evaluate sentiment classification. On their StockTwits test, CryptoBERT XL reports 58.49% accuracy and 58.83% macro F1, compared with FinBERT's 52.74% and 52.79%. These are sentiment-label results, not price-direction accuracy or trading returns. Social posts also differ from our news headlines. The transferable idea is to benchmark the extractor on our own held-out labelled headlines before replacing FinBERT or comparing it with JEV. Then measure downstream forecast improvement independently. [Author-hosted paper, Table 1](https://personal.eur.nl/frasincar/papers/ACSA2023/acsa2023.pdf).

**Garcia and Schweitzer, 2015.** The authors combine economic signals with tweet valence, disagreement/polarization and attention, using earlier data for analysis and a 2014 holdout for trading tests. Their results motivate features beyond a single positive/negative score. However, the historical setting includes short positions and a falling market; their cost sensitivity also removes profitability above approximately 0.25% under their assumptions. Our long-only 2026 paper portfolio is a different experiment. The useful transfer is matched ablation and execution-cost sensitivity, not the reported historical return. [Author-hosted published paper, Sections 2–3](https://www.sg.ethz.ch/publications/2015/garcia2015social-signals-and/150288.full_0eXyF50.pdf).

## How controlled learning should work

### Evaluate before updating, with real label delays

Prequential or test-then-train evaluation first saves a prediction, scores it when its label becomes available, and only then permits that observation to influence later training. River explicitly supports delayed progressive validation because real labels often arrive later than inputs. [River documentation](https://riverml.xyz/latest/api/evaluate/progressive-val-score/).

For our 24h/72h horizons, eligibility must use actual outcome availability, not merely `origin < now`. Preserve the existing stricter availability checks. If an outage delays a candle or a label, a reconstructed replay must reproduce that delay. Score the old artifact's stored prediction before generating the next artifact. An after-the-fact fit on the same outcome cannot retroactively improve the score.

### Use chronological, matched tests

Rolling-origin validation trains only on earlier observations and supports multi-step forecast errors; fitted residual accuracy is a different, more optimistic quantity. [Hyndman and Athanasopoulos, Forecasting: Principles and Practice](https://otexts.com/fpp3/tscv.html).

Recommended evaluation design: compare candidates on the intersection of valid asset/origin/horizon observations, publish candidate availability separately, and purge any training label whose outcome overlaps the next validation origin. Fit scalers and feature selections on training data only. Keep an untouched forward observation period after choosing a candidate.

Hourly 24-hour forecasts overlap for 23 hours; a thousand rows are not a thousand independent trials. Report both forecast count and calendar coverage. For inference about differences, use time blocks at least as long as the evaluated horizon, check sensitivity to longer blocks, and retain contemporaneous BTC/ETH/SOL observations in the same block. Regime breakdowns should use rules fixed in advance and features available at the origin; a hindsight “bull market” label may describe results but cannot be an input known then. These are proposed safeguards for this PoC, not a new significance result.

### Score uncertainty and direction separately

Proper scoring rules reward honest probabilistic forecasts; quantile scores and interval scores evaluate more than binary coverage alone. Interval width matters because an extremely broad band can cover outcomes while being uninformative. [Gneiting and Raftery, 2007](https://sites.stat.washington.edu/raftery/Research/PDF/Gneiting2007jasa.pdf).

Keep the existing log-return MAE, pinball loss, coverage and width. Add a visible signed bias and an interval score when the stored endpoints support it. If a future model emits a probability of a price increase, evaluate it with a Brier score and reliability bins. A JEV probability about an article's relevance or tone is not that price-event probability and must never be scored or labelled as such. Preserve “uncalibrated” until forward evidence exists.

### Treat adaptive calibration as a candidate, not a guarantee

Adaptive conformal inference (ACI) adjusts prediction sets using past misses under changing distributions. Its long-run coverage result is not a probability guarantee for tomorrow's individual price. The 2021 paper explicitly distinguishes marginal coverage at a single time and identifies delayed/batched outcomes as an extension beyond its immediate-feedback setting. [Gibbs and Candès, 2021, Sections 4.2.3 and 7](https://papers.nips.cc/paper/2021/file/0d441de75945e5acbc865406fc9a2559-Paper.pdf).

For CryptoOracle, first evaluate trailing residual bands against the current raw bands. Test any adaptive method in shadow with the actual 24h/72h feedback delay, and publish recent as well as cumulative coverage and width. The existing empirical residual quantiles are not automatically conformal intervals. A coverage alarm should trigger investigation or wider uncertainty according to a frozen rule; it should not silently lower trading safeguards.

### Keep candidate selection auditable

Repeatedly choosing the best historical configuration can overfit the selection process. Bailey et al. also emphasize that overfitting diagnostics do not fix wrong transaction costs or unavailable-at-decision-time inputs, and cannot reveal regimes absent from the dataset. [The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).

Use a small, declared candidate budget and retain losing experiments. Set evaluation dates and success criteria before looking at the new outcomes. The existing proposed 5% relative MAE gain is a research threshold, not a profit target or sufficient evidence by itself. Require uncertainty around paired differences, coverage checks, and a separate paper execution comparison after fees, spread, slippage and latency. No promotion merely because a candidate won yesterday.

Champion/challenger versioning is a standard operational pattern: MLflow documents version aliases and validation-status tags. These manage which artifact is served; they do not prove it is better. [MLflow registry workflow](https://www.mlflow.org/docs/latest/ml/model-registry/workflow/). For this small PoC, an artifact manifest and append-only promotion record in the existing database can express the same policy without deploying MLflow. Resolve and record the immutable artifact ID for every issued forecast, even if a mutable alias is used operationally.

## News correction as an isolated experiment

The following is a proposed implementation design, extending the repository's existing information boundaries:

1. Preserve `published_at`, `first_seen_at`, `classified_at`, source URL, content hash, annotation version and deduplication cluster. Set eligibility to the latest required availability timestamp; an old publication date must not make an article found today available yesterday. Late classification must not be backfilled into earlier decisions.
2. Derive asset-specific trailing features: relevant event count, source diversity, novelty, polarity, disagreement, event type and age. Preserve separate indicators for feed outage, extractor outage and no observed event. Syndicated copies contribute one event, not many independent confirmations.
3. Keep the existing frozen TimesFM forecast. Train a low-dimensional market-only residual correction and an otherwise matched market-plus-news correction. Their difference estimates incremental news value under the chosen protocol. Keep JEV and FinBERT feature versions separately identifiable.
4. Fit corrections against out-of-sample residuals whose outcomes were known by the training cutoff. Avoid a manually chosen rule such as “positive sentiment adds 1%.” Re-estimate the corrected forecast's uncertainty; simply shifting an unvalidated original band is insufficient.
5. Begin with prospective captured headlines. Historical retrieval and a contemporary LLM may leak revised information or remembered outcomes; treat retrospective news extraction as exploratory unless point-in-time availability and contamination controls can be demonstrated. This is an experimental risk to test, not a claim that a particular source is contaminated.
6. Give reflection a bounded role: it may summarize scored evidence and propose a versioned hypothesis, such as “negative bias increased in high-volatility periods.” Code computes the metrics. Reflection cannot relabel failures, assert an unobserved cause, edit prices, change risk limits, or rewrite the trading prompt in place.

Market-input quality remains an independent gate. A well-calibrated predictor on the wrong price does not repair a delayed feed, an outlier venue or an unexecutable order book. Keep failed validation periods visible so strict filters and data outages cannot disappear from the reported success rate.

## Recommended next sequence

1. **Expose the existing accountability loop.** Show original forecast versus observed endpoint, settled/pending/unavailable status, matching persistence error, and a link from each paper decision to its forecast. Include all eligible forecasts, including those that caused no trade.
2. **Observe current shadow corrections before adding complexity.** Publish readiness counts and exact reasons they are unavailable. When they become eligible, compare market-only versus news correction prospectively. The 21-day threshold starts technical eligibility; it does not graduate a model.
3. **Add one bounded model challenger.** Benchmark Chronos-Bolt Tiny on the same closed candles and origins, with pinned weights and a latency/memory limit suitable for the shared AX41. Preserve TimesFM and persistence. Introduce richer Chronos-2 covariates or adaptive calibration only as subsequent, separately measurable candidates.
4. **Promote only through a recorded new experiment.** Freeze selection criteria and the next forward evaluation window, retain the previous artifact and policy, and publish better/worse/inconclusive outcomes. Prediction-quality promotion and trading-policy promotion are separate decisions. A model may reduce forecast error without increasing net portfolio return.

The intended public claim is therefore: **“Every forecast is recorded and checked after its horizon. Candidate improvements learn only from previously available outcomes and are compared prospectively before they influence a new strategy version.”** That is a testable development method, not a promise of autonomous improvement or profit.
