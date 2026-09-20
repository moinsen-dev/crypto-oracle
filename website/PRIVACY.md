# Privacy implementation and operating record

Scope: the English public CryptoOracle research notebook, virtual-portfolio API, forecast journal and email newsletter (updated 20 September 2026). This record describes the current deployment; it is not a claim that technical checks certify all GDPR obligations.

## Implemented minimisation

- Static HTML/CSS/SVG plus three same-origin scripts for benchmark and virtual-portfolio views. System fonts. No embedded remote media, pixels, analytics, third-party ads, consent platform, account registration or contact form. The newsletter sign-up is the only form.
- Selections remain in page memory and shareable URLs. Forecast filters, pagination and forecast IDs are sent to the same-origin API; the portfolio API receives the experiment ID. Portfolio account and decision filters run in the browser. No application cookies, localStorage, sessionStorage, IndexedDB, visitor profiles or service worker.
- The portfolio fetches the same public `GET /api/paper` snapshot approximately once a minute while visible, and on manual refresh. Fetches omit credentials and use no-store. The JSON download uses this same endpoint. These are ordinary delivery requests, not analytics events.
- `connect-src 'self'`, same-origin scripts/styles, no framing, `form-action 'none'` (the single sign-up form is submitted by the page's own script to the same origin), no-referrer, MIME-sniffing protection, HTTPS/HSTS and restricted browser permissions. Public API responses also specify no-store and no-referrer.
- No browser or Cloudflare access to the private dashboard, research database, manual holdings or model APIs. The historical file and current virtual-portfolio export use separate narrow field allowlists. Raw news titles/URLs, private positions and credentials are excluded.
- The AX41 worker pushes the virtual snapshot to machine-authenticated `POST /api/publish` and forecast data to `POST /api/publish-forecasts`. A dedicated D1 database, created with EU jurisdiction, retains the latest snapshots per paper experiment and the learning summary. The forecast journal retains frozen public claims and their original outcomes; later numeric quality reviews can update the public record while the private research ledger retains every review version. Apart from the newsletter tables described below, it stores no visitor records. Database jurisdiction does not imply EU-only processing of all Cloudflare delivery/security traffic.
- Worker observability is disabled; application code does not log requests, bodies or authentication headers, and no visitor-level log export is configured. Cloudflare may still process operational/security metadata; do not promise zero provider processing, zero cookies in every security challenge, or EU-only processing.
- Public operator details, an English privacy notice and legal notice are reachable from every page. No promotional claim of GDPR certification.

## Newsletter (added 20 September 2026; not active until the operator configures the mail secrets)

- **Purpose and basis.** Weekly English newsletter with project updates, market and forecast summaries, linked headlines and information about Moinsen's products and services. Consent, Article 6(1)(a) GDPR and section 7 UWG. The promotional part is named in the consent wording because every issue carries it.
- **Data.** Email address; time of request; time of confirmation; version of the consent wording (`CONSENT_VERSION`, pinned to the exact text by a test); number and time of confirmation mails; per issue the fact and time of delivery. No IP address, no user agent, no open or click data. Abuse counters hold timestamps only.
- **Double opt-in.** One confirmation mail; confirmation happens by pressing a button on the site, not by opening the link, so automated link scanners cannot confirm for a third party. Unconfirmed rows are deleted after seven days.
- **Storage and recipients.** Cloudflare D1 (EU jurisdiction) as the list of record. Resend (Plus Five Five, Inc., 2261 Market Street #5039, San Francisco, CA 94114, USA) receives address and content for delivery only, as processor; its DPA relies on the EU SCCs and states compliance with the EU-U.S. Data Privacy Framework; primary processing in the United States (checked 20 September 2026, https://resend.com/legal/dpa). The operator must have accepted that DPA in the Resend account. The research server is not a recipient.
- **Withdrawal and deletion.** Unsubscribe link in every mail, `List-Unsubscribe` one-click header, or email to the operator. Removal deletes the address and its delivery records immediately. **Operator decision to revisit with legal advice:** no proof of the former consent is kept after deletion; some controllers keep a minimal record for the limitation period.
- **Operator duties the code cannot fulfil.** Keep open and click tracking switched off for the sending domain at Resend; add the newsletter to the record of processing activities; answer access and deletion requests that arrive by email; review Resend's suppression list and retention. Issue content is approved by the operator before every send.
- **Changed statements.** The site no longer says "no advertising" or "no forms": the footer reads "No third-party ads", the privacy notice names the newsletter, and the build check allows exactly one reviewed form.

## Necessary delivery and security processing

Purpose: make the public research material and virtual-portfolio updates available securely. Necessary request metadata includes IP address, URL, time, browser and routing information. Proposed legal basis reflected in the notice: Article 6(1)(f) GDPR. Delivery cannot work without a network address; eliminating analytics, visitor accounts and application logs reduces processing. Visitors reasonably expect an information page to process the connection needed to display and refresh it. No behavioural targeting or decisions about visitors are made.

Cloudflare is the hosting provider. Its DPA addresses processor duties, subprocessors and safeguards for restricted transfers. Actual account/service terms and provider retention remain operational responsibilities of the controller. The notice links the DPA and provider privacy policy and does not invent a fixed infrastructure log-retention period. Provider-side security settings must be reconsidered if changed.

Email contact is handled by the operator's existing mailbox, outside this application. Requests require a working process for access/deletion/objection and retention review. The website cannot enforce mailbox deletion or establish the actual cloud contract by itself. Review these arrangements when introducing new processing or changing providers. Do not enable Web Analytics, Zaraz, Logpush or a third-party widget without updating the assessment, notice and consent treatment where required.

## Evidence and sources (checked 18 September 2026)

- Operator name, address and VAT ID: https://www.moinsen.dev/en/impressum (user-authorised source). The operator supplied `uli@moinsen.dev` as the public contact email on 18 September 2026.
- Transparency/minimisation: https://commission.europa.eu/law/law-topic/data-protection/information-business-and-organisations/principles-gdpr_en
- Individual rights: https://commission.europa.eu/law/law-topic/data-protection/information-individuals_en
- Cloudflare DPA: https://www.cloudflare.com/cloudflare-customer-dpa/
- Cloudflare processing/retention: https://www.cloudflare.com/privacypolicy/
- Operator notice: https://www.gesetze-im-internet.de/ddg/__5.html
- Terminal storage/access: https://www.gesetze-im-internet.de/ttdsg/__25.html

Use current DDG terminology rather than the old TMG reference on the source legal page. The source's generic liability and dispute-resolution boilerplate is not copied. This site's actual scope is described, and the operator is named as editorially responsible.

Record actual browser/network/header checks in the project VALIDATION.md after running them. Technical evidence and controller/legal responsibilities must remain distinguishable.
