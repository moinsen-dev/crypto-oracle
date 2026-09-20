# CryptoOracle public website

English Astro pages, a Cloudflare Worker, and a narrowly validated public D1 journal.

**Site:** https://cryptooracle.moinsen.dev/
**Source:** https://github.com/moinsen-dev/crypto-oracle

The public APIs serve frozen forecasts and outcomes, learning readiness, and virtual portfolio snapshots. They cannot query the private research service, access manual holdings or place trades. GitHub is linked directly; no remote widget or tracking script is embedded.

## Local preview

Requires Node.js 24. Dependencies are pinned in `package-lock.json`.

```sh
npm ci
npx wrangler d1 migrations apply crypto-oracle-public --local
npm run check
npx tsc --noEmit
npm run build
npm run preview
```

Preview runs at `http://127.0.0.1:4321`. The D1 binding has `remote: false`; local preview does not read production data. An empty database displays an honest waiting state. `npm run dev` provides the Astro editing server but does not implement the Worker APIs.

If testing publication, create a private `.dev.vars` containing a **local-only** `PUBLISH_TOKEN`. Send only allowlisted fixture data to the local API with that bearer token and a current publication timestamp. Never publish synthetic fixtures to production. Tests in `scripts/` validate private-field rejection, chronology and accounting constraints.

## Deploy

`wrangler.jsonc` describes the existing Moinsen deployment: the `crypto-oracle-public` Worker, dedicated public D1 database and `cryptooracle.moinsen.dev` Custom Domain. These identifiers are not credentials. Authentication and the publication secret are configured privately and are excluded from this repository.

```sh
npx wrangler whoami
npx wrangler d1 migrations apply crypto-oracle-public --remote
npm run deploy:dry-run
npm run deploy
```

Before an update, record the existing deployment with `npx wrangler deployments list`; `npx wrangler rollback VERSION_ID` restores that Worker version without replacing research evidence. Migrations here are additive. Never delete the research volume or public journal as part of an application rollback.

For an independent deployment:

1. Replace the Worker/account/database identifiers and Custom Domain with your own Cloudflare resources. Create a D1 database and apply the migrations.
2. Set `SITE_ORIGIN` for your build and replace `src/data/operator.json` with the actual operator details. Review the privacy/legal content for your operation; the supplied notice describes the Moinsen site.
3. Provision a fresh `PUBLISH_TOKEN` with `wrangler secret put PUBLISH_TOKEN`; privately configure the matching `ORACLE_PUBLIC_TOKEN` only in your research worker.
4. Before enabling publication, replace the publication endpoint URLs in `oracle/paper.py` and `oracle/public_forecasts.py` with your own Worker URL. The current defaults support the existing Moinsen server. Never reuse this site's key.

Only `dist/` is uploaded as static assets. The Worker and schema validators are bundled separately. Raw research data, model weights, environment files and the private dashboard are not deployed here. `npm run build` rejects unknown public files, private fields, credential markers and external embedded assets.

## Data and routes

- `/api/paper/runs` lists independent paper experiments; `/api/paper?run=RUN_ID` selects one.
- `/api/forecasts` provides bounded pagination with asset, horizon, model and status filters; `?id=HASH` retrieves one forecast.
- `/api/learning` contains readiness counts and the frozen learning policy.
- `/api/publish` and `/api/publish-forecasts` require the private publication credential. Bodies are size-bounded and validated. Frozen claims and first outcomes cannot be replaced by a later publication.

The existing server can keep publishing to the `workers.dev` address; the new domain serves the same Worker and D1 data. The canonical website origin is `cryptooracle.moinsen.dev`.

Browser requests use the website's own origin and omit credentials. Forecast filters and record IDs are sent as API query parameters; account and decision filters run in the browser. There is no application cookie, browser storage, analytics, third-party advertising or contact form. The newsletter sign-up described below is the only form and the only place personal data is stored. See [PRIVACY.md](PRIVACY.md) for implementation and operator responsibilities.

## Content and checks

`src/data/research.json` is a dated historical result file, separate from the live journals. `src/data/study.json` is the unedited output of `crypto-oracle study` behind `/evidence/`; publish a new measurement by copying a fresh `data/study-report.json` over it, never by editing numbers. Its schema requires the backtest label, the frozen lookbacks and all eight trend variants, so a selective or relabelled export fails the build. Charts on that page are drawn at build time; it ships no script. Visual rules live in [DESIGN.md](DESIGN.md). Keep historical and future evidence distinct. The release check verifies English HTML, required legal links, an asset allowlist, strict research schema and security headers. Also exercise the live APIs and actual browser at desktop and mobile widths after deployment. A successful build alone does not verify delivery, data freshness or research performance.

## Newsletter

`/newsletter/` is the only place on the site that accepts personal data: an email address for the weekly field notes. Everything else about the site's privacy posture is unchanged.

- **Open or closed.** `src/data/site.json` holds `newsletterOpen`. While it is `false` the sign-up API answers `signup_closed`, the form is not shown, and neither the navigation, the footer, the page band nor the sitemap mention the newsletter. Weekly drafts and operator previews keep working, so the content can be judged before anyone is asked for an address. Opening it is a one-word change and a deploy.
- **Boundary.** The research server builds one issue per completed ISO week from its ledger (`crypto-oracle newsletter-report` shows it) and posts it to `POST /api/newsletter/issue` with the existing publication token. An issue holds the market week with its context (30 days, largest hourly move, how busy the week was against the twelve before it), the claims that are still open and already locked in the public journal, the scored forecasts, the range experiment, the paper portfolios with the reason for every trade, the classified headlines with the week's mix of topics and tone, what changed in the system, and one standing idea from `oracle/explainers.json`. `crypto-oracle newsletter-preview` posts the last seven days up to the current hour to `POST /api/newsletter/preview` instead: that mail goes to the operator only, is stored nowhere and can never become an issue. It never receives, counts or addresses subscribers. `src/lib/newsletter.mjs` validates the issue with exact keys, fixed link hosts and length limits, and renders the mail (HTML and text) and the archive view; headline text is always escaped.
- **Sign-up.** Double opt-in. `POST /api/newsletter/subscribe` stores a pending row and sends one confirmation mail; the answer never reveals whether an address is known. Links in mails open `/newsletter/?confirm=…`, `?unsubscribe=…` or `?approve=…`; only the button on that page changes anything, so link scanners in mail gateways cannot confirm, remove or send. The page removes tokens from the address bar at once. Mail clients use the `List-Unsubscribe` one-click post. Unsubscribing deletes the row and its delivery records.
- **Abuse limits without visitor data.** Trap field, a minimum fill time, at most three confirmation mails per address (one per day), and global caps per hour and day counted in a table that holds no addresses. No IP address is stored.
- **Sending.** A new issue is a draft and goes to `NEWSLETTER_PREVIEW_TO` only. The approval link is bound to the hash of that exact payload; the stored payload is frozen by a trigger. Delivery runs in batches of 100 with idempotency keys derived from the recipients, records each delivery, and can be resumed after a provider failure without mailing anyone twice. Only sent issues appear in the archive API.
- **Configuration (Cloudflare secrets).** `RESEND_API_KEY`, `NEWSLETTER_SECRET` (any long random string; it signs unsubscribe and approval links, so changing it invalidates links in mails already sent) and `NEWSLETTER_PREVIEW_TO`. Without all three the API answers `newsletter_not_configured`, the form stays hidden and nothing is stored. Apply `migrations/0004_newsletter.sql` before deploying. The sender is `business@moinsen.dev`; **open and click tracking are domain settings at Resend and must be off for that domain**, otherwise the privacy notice is wrong. `RESEND_API_URL` exists only so that the local end-to-end test can talk to a stand-in instead of the real provider.
- **Checks.** `scripts/newsletter.test.mjs` (boundary, rendering, escaping, consent wording pinned to its version) and `scripts/newsletter-service.test.mjs` (the whole list lifecycle on an in-memory SQLite with the D1 surface). The build check allows exactly one form on the site, only on this page, without an `action`.
