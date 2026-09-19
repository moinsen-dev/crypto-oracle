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

Browser requests use the website's own origin and omit credentials. Forecast filters and record IDs are sent as API query parameters; account and decision filters run in the browser. There is no application cookie, browser storage, analytics, advertising or contact form. See [PRIVACY.md](PRIVACY.md) for implementation and operator responsibilities.

## Content and checks

`src/data/research.json` is a dated historical result file, separate from the live journals. `src/data/study.json` is the unedited output of `crypto-oracle study` behind `/evidence/`; publish a new measurement by copying a fresh `data/study-report.json` over it, never by editing numbers. Its schema requires the backtest label, the frozen lookbacks and all eight trend variants, so a selective or relabelled export fails the build. Charts on that page are drawn at build time; it ships no script. Visual rules live in [DESIGN.md](DESIGN.md). Keep historical and future evidence distinct. The release check verifies English HTML, required legal links, an asset allowlist, strict research schema and security headers. Also exercise the live APIs and actual browser at desktop and mobile widths after deployment. A successful build alone does not verify delivery, data freshness or research performance.
