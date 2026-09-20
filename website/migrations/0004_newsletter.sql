-- Newsletter: the only tables of this site that hold personal data (an email address and its consent record).
CREATE TABLE IF NOT EXISTS newsletter_subscribers (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK(status IN ('pending','confirmed')),
  token_hash TEXT NOT NULL,
  requested_at INTEGER NOT NULL,
  confirmed_at INTEGER,
  consent_version TEXT NOT NULL,
  mails INTEGER NOT NULL DEFAULT 1,
  last_mail_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS newsletter_subscriber_status ON newsletter_subscribers(status,id);
CREATE INDEX IF NOT EXISTS newsletter_subscriber_token ON newsletter_subscribers(token_hash);
CREATE TABLE IF NOT EXISTS newsletter_issues (
  id TEXT PRIMARY KEY,
  received_at INTEGER NOT NULL,
  week_end INTEGER NOT NULL,
  title TEXT NOT NULL,
  payload TEXT NOT NULL CHECK(json_valid(payload)),
  payload_hash TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('draft','sending','sent')),
  sent_at INTEGER,
  recipients INTEGER NOT NULL DEFAULT 0
);
-- An approved issue is the issue that was previewed: its content can never change afterwards.
CREATE TRIGGER IF NOT EXISTS frozen_newsletter_issue BEFORE UPDATE ON newsletter_issues
WHEN OLD.payload != NEW.payload OR OLD.payload_hash != NEW.payload_hash OR OLD.id != NEW.id OR (OLD.status = 'sent' AND NEW.status != 'sent')
BEGIN SELECT RAISE(ABORT, 'immutable_newsletter_issue'); END;
CREATE TABLE IF NOT EXISTS newsletter_sends (
  issue_id TEXT NOT NULL REFERENCES newsletter_issues(id),
  subscriber_id TEXT NOT NULL,
  sent_at INTEGER NOT NULL,
  PRIMARY KEY(issue_id, subscriber_id)
);
-- Counters for abuse limits. No address, no network address, nothing about a visitor.
CREATE TABLE IF NOT EXISTS newsletter_events (at INTEGER NOT NULL, kind TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS newsletter_event_time ON newsletter_events(kind,at);
