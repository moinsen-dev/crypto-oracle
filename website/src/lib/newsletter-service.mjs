// Subscriber list, double opt-in, one-click removal and issue delivery. Runs in the Worker against the site's own D1.
// The research server can hand over an issue; it can never read, count or address subscribers.
import { createHash, createHmac, randomBytes, timingSafeEqual } from 'node:crypto';
import { CONSENT_VERSION, normalizeEmail, renderConfirmation, renderIssue, validateIssue, headline } from './newsletter.mjs';

export const LIMITS = { pendingDays: 7, confirmationsPerAddress: 3, resendAfter: 86400, mailsPerHour: 40, mailsPerDay: 300, batch: 100, batchesPerCall: 40 };
const FROM = 'CryptoOracle by Moinsen <business@moinsen.dev>';
const sha = value => createHash('sha256').update(value).digest('hex');

export function createNewsletter({ db, sendBatch, secret, origin, operator, previewTo, now = () => Math.floor(Date.now() / 1000), token = () => randomBytes(24).toString('base64url') }) {
  const mac = value => createHmac('sha256', secret).update(value).digest('hex');
  const same = (a, b) => a.length === b.length && timingSafeEqual(Buffer.from(a), Buffer.from(b));
  // Links in a mail open a page on the site; only the button there changes anything. Link scanners in mail
  // gateways follow links but do not press buttons, so they can neither confirm, remove nor send for anyone.
  const unsubscribeToken = id => `${id}.${mac('unsubscribe:' + id)}`;
  const unsubscribeUrl = id => `${origin}/newsletter/?unsubscribe=${unsubscribeToken(id)}`;
  const oneClickUrl = id => `${origin}/api/newsletter/unsubscribe?token=${unsubscribeToken(id)}`;
  const approveUrl = issue => `${origin}/newsletter/?approve=${issue.id}&token=${mac(`approve:${issue.id}:${issue.payload_hash}`)}`;
  const count = async (kind, since) => (await db.prepare('SELECT COUNT(*) AS n FROM newsletter_events WHERE kind=? AND at>?').bind(kind, since).first()).n;

  async function subscribe({ email: input, consent, website = '' }) {
    const email = normalizeEmail(input), at = now();
    if (!email || consent !== true) return { status: 'invalid' };
    // A filled trap field means a script; answer like a success and do nothing.
    if (website) return { status: 'accepted' };
    await db.batch([
      db.prepare('DELETE FROM newsletter_subscribers WHERE status=? AND requested_at<?').bind('pending', at - LIMITS.pendingDays * 86400),
      db.prepare('DELETE FROM newsletter_events WHERE at<?').bind(at - 2 * 86400),
    ]);
    const existing = await db.prepare('SELECT * FROM newsletter_subscribers WHERE email=?').bind(email).first();
    // The answer never reveals whether an address is known, pending or confirmed.
    if (existing?.status === 'confirmed') return { status: 'accepted' };
    if (existing && (existing.mails >= LIMITS.confirmationsPerAddress || at - existing.last_mail_at < LIMITS.resendAfter)) return { status: 'accepted' };
    if (await count('confirmation', at - 3600) >= LIMITS.mailsPerHour || await count('confirmation', at - 86400) >= LIMITS.mailsPerDay) return { status: 'busy' };
    const secretToken = token(), id = existing?.id || randomBytes(16).toString('hex');
    const mail = renderConfirmation({ confirmUrl: `${origin}/newsletter/?confirm=${secretToken}`, operator });
    // Mail first, record second: if the provider refuses, nothing is stored and the person can simply try again.
    await sendBatch([{ from: FROM, to: [email], reply_to: operator.email, subject: mail.subject, html: mail.html, text: mail.text }], `confirmation/${sha(secretToken).slice(0, 32)}`);
    await db.batch([
      db.prepare('INSERT INTO newsletter_subscribers(id,email,status,token_hash,requested_at,consent_version,mails,last_mail_at) VALUES(?,?,?,?,?,?,1,?) ON CONFLICT(email) DO UPDATE SET token_hash=excluded.token_hash,consent_version=excluded.consent_version,mails=newsletter_subscribers.mails+1,last_mail_at=excluded.last_mail_at WHERE newsletter_subscribers.status=?')
        .bind(id, email, 'pending', sha(secretToken), at, CONSENT_VERSION, at, 'pending'),
      db.prepare('INSERT INTO newsletter_events(at,kind) VALUES(?,?)').bind(at, 'confirmation'),
    ]);
    return { status: 'accepted' };
  }

  async function confirm(secretToken) {
    if (typeof secretToken !== 'string' || !/^[A-Za-z0-9_-]{20,64}$/.test(secretToken)) return { status: 'invalid' };
    const at = now();
    const row = await db.prepare('SELECT id,status FROM newsletter_subscribers WHERE token_hash=? AND requested_at>=?').bind(sha(secretToken), at - LIMITS.pendingDays * 86400).first();
    if (!row) return { status: 'invalid' };
    await db.prepare('UPDATE newsletter_subscribers SET status=?,confirmed_at=COALESCE(confirmed_at,?) WHERE id=?').bind('confirmed', at, row.id).run();
    return { status: 'confirmed' };
  }

  async function unsubscribe(value) {
    const [id, signature] = typeof value === 'string' ? value.split('.') : [];
    if (!/^[a-f0-9]{32}$/.test(id || '') || !/^[a-f0-9]{64}$/.test(signature || '') || !same(signature, mac('unsubscribe:' + id))) return { status: 'invalid' };
    // Removal deletes the address and its delivery records; a second click is just as successful.
    await db.batch([db.prepare('DELETE FROM newsletter_sends WHERE subscriber_id=?').bind(id), db.prepare('DELETE FROM newsletter_subscribers WHERE id=?').bind(id)]);
    return { status: 'removed' };
  }

  async function storeIssue(data) {
    const issue = validateIssue(data), at = now(), payload = JSON.stringify(issue), payload_hash = sha(payload);
    const known = await db.prepare('SELECT status,payload_hash FROM newsletter_issues WHERE id=?').bind(issue.id).first();
    if (known) return { status: known.payload_hash === payload_hash ? 'unchanged' : 'conflict' };
    await db.prepare('INSERT INTO newsletter_issues(id,received_at,week_end,title,payload,payload_hash,status) VALUES(?,?,?,?,?,?,?)').bind(issue.id, at, issue.end, headline(issue), payload, payload_hash, 'draft').run();
    // Nothing reaches subscribers until the operator has seen exactly this payload and approved it.
    const mail = renderIssue(issue, { unsubscribeUrl: `${origin}/newsletter/`, archiveUrl: `${origin}/newsletter/?issue=${issue.id}`, operator });
    const note = `PREVIEW — not sent to subscribers yet.\nApprove and send: ${approveUrl({ id: issue.id, payload_hash })}\n\n`;
    await sendBatch([{ from: FROM, to: [previewTo], subject: `[preview] ${mail.subject}`, text: note + mail.text, html: mail.html.replace('<body', `<body data-preview="1"`).replace(/(<table role="presentation" width="600"[^>]*><tr><td>)/, `$1<p style="font:14px/1.5 sans-serif;background:#fff0de;border:1px solid #d7b793;padding:12px 14px;margin:0 0 22px">Preview. Not sent to subscribers yet. <a href="${approveUrl({ id: issue.id, payload_hash })}">Approve and send this issue</a></p>`) }], `preview/${issue.id}/${payload_hash.slice(0, 16)}`);
    return { status: 'draft' };
  }

  async function approve(id, signature) {
    const issue = typeof id === 'string' && /^\d{4}-W\d{2}$/.test(id) ? await db.prepare('SELECT * FROM newsletter_issues WHERE id=?').bind(id).first() : null;
    if (!issue || typeof signature !== 'string' || !same(signature, mac(`approve:${issue.id}:${issue.payload_hash}`))) return { status: 'invalid' };
    if (issue.status === 'sent') return { status: 'sent', recipients: issue.recipients };
    const data = JSON.parse(issue.payload);
    let delivered = 0;
    for (let round = 0; round < LIMITS.batchesPerCall; round++) {
      const rows = (await db.prepare('SELECT id,email FROM newsletter_subscribers s WHERE status=? AND NOT EXISTS (SELECT 1 FROM newsletter_sends d WHERE d.issue_id=? AND d.subscriber_id=s.id) ORDER BY id LIMIT ?').bind('confirmed', issue.id, LIMITS.batch).all()).results;
      if (!rows.length) break;
      const mails = rows.map(r => {
        const mail = renderIssue(data, { unsubscribeUrl: unsubscribeUrl(r.id), archiveUrl: `${origin}/newsletter/?issue=${issue.id}`, operator });
        return { from: FROM, to: [r.email], reply_to: operator.email, subject: mail.subject, html: mail.html, text: mail.text, headers: { 'List-Unsubscribe': `<${oneClickUrl(r.id)}>`, 'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click' } };
      });
      // The key names the exact recipients, so a retried request cannot mail them twice.
      await sendBatch(mails, `issue/${issue.id}/${sha(rows.map(r => r.id).join(',')).slice(0, 32)}`);
      const at = now();
      await db.batch(rows.map(r => db.prepare('INSERT OR IGNORE INTO newsletter_sends(issue_id,subscriber_id,sent_at) VALUES(?,?,?)').bind(issue.id, r.id, at)));
      delivered += rows.length;
    }
    const left = (await db.prepare('SELECT COUNT(*) AS n FROM newsletter_subscribers s WHERE status=? AND NOT EXISTS (SELECT 1 FROM newsletter_sends d WHERE d.issue_id=? AND d.subscriber_id=s.id)').bind('confirmed', issue.id).first()).n;
    const total = (await db.prepare('SELECT COUNT(*) AS n FROM newsletter_sends WHERE issue_id=?').bind(issue.id).first()).n;
    await db.prepare('UPDATE newsletter_issues SET status=?,sent_at=?,recipients=? WHERE id=?').bind(left ? 'sending' : 'sent', now(), total, issue.id).run();
    return { status: left ? 'sending' : 'sent', recipients: total, delivered, remaining: left };
  }

  async function issues() {
    return (await db.prepare('SELECT id,week_end,title FROM newsletter_issues WHERE status=? ORDER BY week_end DESC LIMIT 60').bind('sent').all()).results;
  }

  async function issue(id) {
    if (typeof id !== 'string' || !/^\d{4}-W\d{2}$/.test(id)) return null;
    const row = await db.prepare('SELECT payload FROM newsletter_issues WHERE id=? AND status=?').bind(id, 'sent').first();
    return row ? JSON.parse(row.payload) : null;
  }

  return { subscribe, confirm, unsubscribe, storeIssue, approve, issues, issue };
}
