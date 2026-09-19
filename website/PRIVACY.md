# Privacy implementation and operating record

Scope: the English public CryptoOracle research notebook, virtual-portfolio API and forecast journal (updated 19 September 2026). This record describes the current deployment; it is not a claim that technical checks certify all GDPR obligations.

## Implemented minimisation

- Static HTML/CSS/SVG plus three same-origin scripts for benchmark and virtual-portfolio views. System fonts. No embedded remote media, pixels, analytics, ads, consent platform, registration or contact form.
- Selections remain in page memory and shareable URLs. Forecast filters, pagination and forecast IDs are sent to the same-origin API; the portfolio API receives the experiment ID. Portfolio account and decision filters run in the browser. No application cookies, localStorage, sessionStorage, IndexedDB, visitor profiles or service worker.
- The portfolio fetches the same public `GET /api/paper` snapshot approximately once a minute while visible, and on manual refresh. Fetches omit credentials and use no-store. The JSON download uses this same endpoint. These are ordinary delivery requests, not analytics events.
- `connect-src 'self'`, same-origin scripts/styles, no framing or forms, no-referrer, MIME-sniffing protection, HTTPS/HSTS and restricted browser permissions. Public API responses also specify no-store and no-referrer.
- No browser or Cloudflare access to the private dashboard, research database, manual holdings or model APIs. The historical file and current virtual-portfolio export use separate narrow field allowlists. Raw news titles/URLs, private positions and credentials are excluded.
- The AX41 worker pushes the virtual snapshot to machine-authenticated `POST /api/publish` and forecast data to `POST /api/publish-forecasts`. A dedicated D1 database, created with EU jurisdiction, retains the latest snapshots per paper experiment and the learning summary. The forecast journal retains frozen public claims and their original outcomes; later numeric quality reviews can update the public record while the private research ledger retains every review version. It stores no visitor records. Database jurisdiction does not imply EU-only processing of all Cloudflare delivery/security traffic.
- Worker observability is disabled; application code does not log requests, bodies or authentication headers, and no visitor-level log export is configured. Cloudflare may still process operational/security metadata; do not promise zero provider processing, zero cookies in every security challenge, or EU-only processing.
- Public operator details, an English privacy notice and legal notice are reachable from every page. No promotional claim of GDPR certification.

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
