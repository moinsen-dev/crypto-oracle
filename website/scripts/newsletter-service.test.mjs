import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import { createNewsletter, LIMITS } from '../src/lib/newsletter-service.mjs';

const issue = JSON.parse(readFileSync(new URL('./fixtures/newsletter-issue.json', import.meta.url)));
const operator = JSON.parse(readFileSync(new URL('../src/data/operator.json', import.meta.url)));
const migration = readFileSync(new URL('../migrations/0004_newsletter.sql', import.meta.url), 'utf8');

// The same prepare/bind/first/run/all/batch surface the Worker gets from D1, on an in-memory SQLite.
function setup({ failAt } = {}) {
  const sqlite = new DatabaseSync(':memory:'); sqlite.exec(migration);
  const prepare = sql => { let args = []; const s = { bind: (...a) => { args = a; return s; }, first: async () => sqlite.prepare(sql).get(...args) ?? null, run: async () => { sqlite.prepare(sql).run(...args); return {}; }, all: async () => ({ results: sqlite.prepare(sql).all(...args) }) }; return s; };
  const db = { prepare, batch: async list => { sqlite.exec('BEGIN'); try { for (const s of list) await s.run(); sqlite.exec('COMMIT'); } catch (e) { sqlite.exec('ROLLBACK'); throw e; } } };
  const clock = { now: 1_790_000_000 }, sent = [];
  let tokens = 0;
  const service = createNewsletter({ db, secret: 'test-secret', origin: 'https://cryptooracle.moinsen.dev', operator, previewTo: 'operator@example.org', now: () => clock.now, token: () => `token-${String(++tokens).padStart(20, '0')}`,
    sendBatch: async (mails, key) => { if (failAt && sent.length + 1 === failAt.call) { failAt.call = 0; throw new Error('provider down'); } sent.push({ mails, key }); } });
  return { service, sqlite, clock, sent };
}
const confirmToken = mail => mail.text.match(/[?&]confirm=([A-Za-z0-9_-]+)/)[1];
async function member(s, email) { await s.service.subscribe({ email, consent: true }); await s.service.confirm(confirmToken(s.sent.at(-1).mails[0])); }

test('double opt-in: one mail, nothing sent to the list before the click, consent version stored', async () => {
  const s = setup();
  assert.deepEqual(await s.service.subscribe({ email: ' Reader@Example.org ', consent: true }), { status: 'accepted' });
  assert.equal(s.sent.length, 1); assert.deepEqual(s.sent[0].mails[0].to, ['reader@example.org']); assert.equal(s.sent[0].mails[0].from, 'CryptoOracle by Moinsen <business@moinsen.dev>');
  const row = s.sqlite.prepare('SELECT * FROM newsletter_subscribers').get();
  assert.equal(row.status, 'pending'); assert.equal(row.consent_version, '2026-09-19.1'); assert.ok(!JSON.stringify(row).includes('token-0'), 'only a hash of the token is stored');
  assert.deepEqual(await s.service.confirm('token-99999999999999999999'), { status: 'invalid' });
  assert.deepEqual(await s.service.confirm(confirmToken(s.sent[0].mails[0])), { status: 'confirmed' });
  assert.equal(s.sqlite.prepare('SELECT status FROM newsletter_subscribers').get().status, 'confirmed');
});
test('refused input writes nothing and mails nobody', async () => {
  const s = setup();
  for (const input of [{ email: 'not-an-address', consent: true }, { email: 'a@example.org', consent: false }, { email: 'a@example.org' }, { email: 'a@example.org\r\nBcc: x@y.z', consent: true }]) assert.deepEqual(await s.service.subscribe(input), { status: 'invalid' });
  assert.deepEqual(await s.service.subscribe({ email: 'bot@example.org', consent: true, website: 'https://spam.example' }), { status: 'accepted' });
  assert.equal(s.sent.length, 0); assert.equal(s.sqlite.prepare('SELECT COUNT(*) AS n FROM newsletter_subscribers').get().n, 0);
});
test('the answer never reveals whether an address is known, and nobody can be mail-bombed through the form', async () => {
  const s = setup();
  await member(s, 'known@example.org');
  assert.deepEqual(await s.service.subscribe({ email: 'known@example.org', consent: true }), { status: 'accepted' });
  assert.deepEqual(await s.service.subscribe({ email: 'new@example.org', consent: true }), { status: 'accepted' });
  assert.deepEqual(await s.service.subscribe({ email: 'new@example.org', consent: true }), { status: 'accepted' });
  assert.equal(s.sent.length, 2, 'one confirmation each; repeats stay silent');
  for (let day = 1; day <= 5; day++) { s.clock.now += LIMITS.resendAfter + 1; await s.service.subscribe({ email: 'new@example.org', consent: true }); }
  assert.equal(s.sent.filter(x => x.mails[0].to[0] === 'new@example.org').length, LIMITS.confirmationsPerAddress);
});
test('a global cap stops a flood of confirmation mails', async () => {
  const s = setup();
  for (let i = 0; i < LIMITS.mailsPerHour; i++) assert.equal((await s.service.subscribe({ email: `u${i}@example.org`, consent: true })).status, 'accepted');
  assert.deepEqual(await s.service.subscribe({ email: 'late@example.org', consent: true }), { status: 'busy' });
  assert.equal(s.sent.length, LIMITS.mailsPerHour);
  assert.ok(!JSON.stringify(s.sqlite.prepare('SELECT * FROM newsletter_events').all()).includes('@'), 'limit counters hold no addresses');
});
test('an unconfirmed address expires after seven days', async () => {
  const s = setup();
  await s.service.subscribe({ email: 'slow@example.org', consent: true });
  const late = confirmToken(s.sent[0].mails[0]);
  s.clock.now += LIMITS.pendingDays * 86400 + 1;
  assert.deepEqual(await s.service.confirm(late), { status: 'invalid' });
  await s.service.subscribe({ email: 'other@example.org', consent: true });
  assert.deepEqual(s.sqlite.prepare('SELECT email FROM newsletter_subscribers').all().map(r => r.email), ['other@example.org']);
});
test('one click removes the address for good; a forged link removes nobody', async () => {
  const s = setup();
  await member(s, 'a@example.org'); await member(s, 'b@example.org');
  await s.service.storeIssue(issue); const approve = new URL(s.sent.at(-1).mails[0].text.match(/Approve and send: (\S+)/)[1]);
  await s.service.approve(approve.searchParams.get('approve'), approve.searchParams.get('token'));
  const mailA = s.sent.at(-1).mails.find(m => m.to[0] === 'a@example.org');
  const link = new URL(mailA.headers['List-Unsubscribe'].slice(1, -1)).searchParams.get('token');
  const [id, signature] = link.split('.');
  assert.deepEqual(await s.service.unsubscribe(`${id}.${'0'.repeat(64)}`), { status: 'invalid' });
  assert.deepEqual(await s.service.unsubscribe(`${'f'.repeat(32)}.${signature}`), { status: 'invalid' });
  assert.deepEqual(await s.service.unsubscribe(link), { status: 'removed' });
  assert.deepEqual(await s.service.unsubscribe(link), { status: 'removed' });
  assert.deepEqual(s.sqlite.prepare('SELECT email FROM newsletter_subscribers').all().map(r => r.email), ['b@example.org']);
  assert.equal(s.sqlite.prepare('SELECT COUNT(*) AS n FROM newsletter_sends WHERE subscriber_id=?').get(id).n, 0);
});
test('an issue reaches subscribers only after the operator approved exactly that content', async () => {
  const s = setup();
  await member(s, 'a@example.org'); await s.service.subscribe({ email: 'pending@example.org', consent: true });
  const before = s.sent.length;
  assert.deepEqual(await s.service.storeIssue(issue), { status: 'draft' });
  assert.equal(s.sent.length, before + 1); const preview = s.sent.at(-1).mails[0];
  assert.deepEqual(preview.to, ['operator@example.org']); assert.ok(preview.subject.startsWith('[preview] '));
  assert.deepEqual(await s.service.storeIssue(issue), { status: 'unchanged' });
  assert.deepEqual(await s.service.storeIssue({ ...issue, changes: [] }), { status: 'conflict' });
  assert.equal(s.sent.length, before + 1, 'no second preview, no overwrite');
  assert.equal(await s.service.issue(issue.id), null, 'a draft is not public');
  const approve = new URL(preview.text.match(/Approve and send: (\S+)/)[1]);
  assert.deepEqual(await s.service.approve(issue.id, 'f'.repeat(64)), { status: 'invalid' });
  const result = await s.service.approve(approve.searchParams.get('approve'), approve.searchParams.get('token'));
  assert.deepEqual(result, { status: 'sent', recipients: 1, delivered: 1, remaining: 0 });
  const delivery = s.sent.at(-1).mails;
  assert.deepEqual(delivery.map(m => m.to[0]), ['a@example.org']);
  assert.equal(delivery[0].headers['List-Unsubscribe-Post'], 'List-Unsubscribe=One-Click');
  const removal = new URL(delivery[0].headers['List-Unsubscribe'].slice(1, -1));
  assert.equal(removal.pathname, '/api/newsletter/unsubscribe', 'mail clients post to the API');
  assert.ok(delivery[0].html.includes(`/newsletter/?unsubscribe=${removal.searchParams.get('token')}`) && !delivery[0].html.includes('Approve and send'), 'the visible link opens the page with a button');
  assert.deepEqual(await s.service.approve(issue.id, approve.searchParams.get('token')), { status: 'sent', recipients: 1 });
  assert.equal(s.sent.at(-1).mails, delivery, 'a second click sends nothing');
  assert.throws(() => s.sqlite.prepare("UPDATE newsletter_issues SET payload='{}'").run(), /immutable_newsletter_issue/);
  assert.deepEqual((await s.service.issues()).map(i => i.id), [issue.id]);
  assert.ok(!JSON.stringify([await s.service.issues(), await s.service.issue(issue.id)]).includes('@example.org'));
});
test('large lists go out in batches and a provider failure never mails anyone twice', async () => {
  const s = setup({ failAt: { call: 0 } });
  const insert = s.sqlite.prepare('INSERT INTO newsletter_subscribers(id,email,status,token_hash,requested_at,confirmed_at,consent_version,last_mail_at) VALUES(?,?,?,?,?,?,?,?)');
  for (let i = 0; i < 250; i++) insert.run(i.toString(16).padStart(32, '0'), `r${i}@example.org`, 'confirmed', 'h' + i, 1, 2, '2026-09-19.1', 1);
  await s.service.storeIssue(issue); const approve = new URL(s.sent.at(-1).mails[0].text.match(/Approve and send: (\S+)/)[1]).searchParams.get('token');
  const base = s.sent.length;
  // The second delivery batch fails once.
  const original = s.service; let calls = 0;
  const flaky = createFlaky(s, () => ++calls === 2);
  await assert.rejects(flaky.approve(issue.id, approve), /provider down/);
  assert.equal(s.sqlite.prepare('SELECT COUNT(*) AS n FROM newsletter_sends').get().n, 100);
  const done = await original.approve(issue.id, approve);
  assert.equal(done.status, 'sent'); assert.equal(done.recipients, 250); assert.equal(done.delivered, 150);
  const recipients = s.sent.slice(base).flatMap(x => x.mails.map(m => m.to[0]));
  assert.equal(recipients.length, 250); assert.equal(new Set(recipients).size, 250);
  assert.equal(new Set(s.sent.slice(base).map(x => x.key)).size, 3, 'each batch has its own idempotency key');
});
function createFlaky(s, shouldFail) {
  const sqlite = s.sqlite;
  const prepare = sql => { let args = []; const st = { bind: (...a) => { args = a; return st; }, first: async () => sqlite.prepare(sql).get(...args) ?? null, run: async () => { sqlite.prepare(sql).run(...args); return {}; }, all: async () => ({ results: sqlite.prepare(sql).all(...args) }) }; return st; };
  const db = { prepare, batch: async list => { for (const x of list) await x.run(); } };
  return createNewsletter({ db, secret: 'test-secret', origin: 'https://cryptooracle.moinsen.dev', operator, previewTo: 'operator@example.org', now: () => s.clock.now, sendBatch: async (mails, key) => { if (shouldFail()) throw new Error('provider down'); s.sent.push({ mails, key }); } });
}
