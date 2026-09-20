(() => {
  const root = document.querySelector('[data-newsletter]');
  if (!root) return;
  const $ = name => root.querySelector(`[data-${name}]`);
  const node = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  async function call(path, body) {
    const response = await fetch('/api/newsletter/' + path, { method: body ? 'POST' : 'GET', cache: 'no-store', credentials: 'omit', signal: AbortSignal.timeout(20000), headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
    return { ok: response.ok, status: response.status, data: await response.json().catch(() => ({})) };
  }
  // Tokens arrive in the address once; take them out of the address bar and the history straight away.
  const params = new URL(location.href).searchParams;
  const action = ['confirm', 'unsubscribe', 'approve'].find(name => params.has(name));
  const secret = action && { kind: action, value: params.get(action), token: params.get('token') };
  const wanted = params.get('issue');
  if (action) history.replaceState(null, '', wanted ? `/newsletter/?issue=${encodeURIComponent(wanted)}` : '/newsletter/');

  const actions = {
    confirm: { eyebrow: 'ONE STEP LEFT', title: 'Confirm your subscription.', text: 'Press the button and the field notes arrive about once a week. You can unsubscribe through the link in every mail.', button: 'Yes, send me the field notes', done: { confirmed: 'Confirmed. The next issue comes to your inbox.', invalid: 'This link is no longer valid. Links expire after seven days; sign up again below.' }, body: s => ({ token: s.value }) },
    unsubscribe: { eyebrow: 'UNSUBSCRIBE', title: 'Stop the field notes?', text: 'Pressing the button deletes your address from the list. Nothing else is kept.', button: 'Unsubscribe and delete my address', done: { removed: 'Done. Your address has been deleted.', invalid: 'This link is not valid. If mails keep arriving, reply to one of them and we remove you by hand.' }, body: s => ({ token: s.value }) },
    approve: { eyebrow: 'OPERATOR', title: 'Send this issue to all subscribers?', text: 'This sends the previewed issue exactly as it was shown. It cannot be recalled.', button: 'Approve and send', done: { sent: 'Sent.', sending: 'Partly sent. Press again to continue with the remaining subscribers.', invalid: 'This approval link does not match the stored issue.' }, body: s => ({ issue: s.value, token: s.token }) },
  };
  if (secret) {
    const a = actions[secret.kind], panel = $('action-panel'), button = $('action-button');
    $('action-eyebrow').textContent = a.eyebrow; $('action-title').textContent = a.title; $('action-text').textContent = a.text; button.textContent = a.button; panel.hidden = false;
    button.addEventListener('click', async () => {
      button.disabled = true; $('action-status').textContent = 'Working…';
      try {
        const result = await call(secret.kind, a.body(secret));
        const status = result.data.status;
        $('action-status').textContent = (a.done[status] || 'That did not work. Please try again in a few minutes.') + (status === 'sent' || status === 'sending' ? ` ${result.data.recipients} recipients so far.` : '');
        button.hidden = status !== 'sending'; button.disabled = false;
      } catch { $('action-status').textContent = 'The service did not answer. Please try again in a few minutes.'; button.disabled = false; }
    });
  }

  const form = $('newsletter-form'), started = Date.now();
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const status = $('signup-status'), data = new FormData(form), submit = form.querySelector('button');
    if (!form.email.validity.valid) { status.textContent = 'Please enter a valid email address.'; form.email.focus(); return; }
    if (!form.consent.checked) { status.textContent = 'Please tick the box to agree before we send the confirmation mail.'; form.consent.focus(); return; }
    submit.disabled = true; status.textContent = 'Sending…';
    try {
      // People need a few seconds to read and type; a form completed instantly is treated like the trap field.
      const result = await call('subscribe', { email: data.get('email'), consent: true, website: String(data.get('website') || '') || (Date.now() - started < 1500 ? 'too-fast' : '') });
      status.textContent = result.ok ? 'Almost there. If the address is new to us, a confirmation mail is on its way. Please check your inbox and spam folder.' : result.status === 400 ? 'That address does not look right. Please check it.' : result.status === 429 ? 'Too many sign-ups right now. Please try again in an hour.' : 'Sign-up is unavailable at the moment. Please try again later.';
      if (result.ok) form.reset();
    } catch { status.textContent = 'The service did not answer. Please try again in a few minutes.'; }
    submit.disabled = false;
  });

  function showIssue(view) {
    const box = $('issue'); box.hidden = false;
    box.replaceChildren(node('p', `FIELD NOTES ${view.id} · ${view.period.toUpperCase()}`, 'eyebrow'), node('h3', view.title), node('p', view.lead, 'newsletter-lead'));
    for (const block of view.blocks) {
      box.append(node('h4', block.title));
      const list = node('dl');
      for (const row of block.rows) { list.append(node('dt', row.label)); const dd = node('dd', row.main); for (const sub of row.subs) dd.append(node('small', sub)); if (row.link) { const a = node('a', row.link.text + ' →'); a.href = new URL(row.link.url).pathname + new URL(row.link.url).search; dd.append(node('small')); dd.lastChild.append(a); } list.append(dd); }
      box.append(list, node('p', block.note, 'fine-print'));
    }
    const links = (title, items, note) => { if (!items.length && !note) return; box.append(node('h4', title)); for (const item of items) { const p = node('p', undefined, 'newsletter-link'); const a = node('a', item.title); a.href = item.url; a.rel = 'external noreferrer'; p.append(a, node('small', item.meta || item.summary)); box.append(p); } if (note) box.append(node('p', note, 'fine-print')); };
    links('News radar', view.news.items, view.news.note); links('What changed in the system', view.changes);
    const idea = node('a', 'Read more on the site →'); idea.href = new URL(view.explainer.url).pathname + new URL(view.explainer.url).hash;
    box.append(node('h4', 'One idea from the notebook'), node('p', view.explainer.title, 'newsletter-idea'), node('p', view.explainer.text), idea);
    if (wanted) box.scrollIntoView({ block: 'start' });
  }
  async function open(id) { const result = await call('issues?id=' + encodeURIComponent(id)); if (result.ok) showIssue(result.data.issue); else $('archive-note').textContent = 'That issue is not in the archive.'; }
  (async () => {
    try {
      const result = await call('issues');
      const open_ = result.data.enabled === true;
      form.hidden = !open_; $('signup-closed').hidden = open_;
      const issues = result.data.issues || [];
      $('archive-note').textContent = issues.length ? 'Each issue is published here when it is sent.' : 'No issue has been sent yet.';
      for (const issue of issues) { const li = node('li'), a = node('a', `${issue.id} · ${issue.title}`); a.href = '/newsletter/?issue=' + issue.id; a.addEventListener('click', event => { event.preventDefault(); history.replaceState(null, '', a.href); open(issue.id); }); li.append(a); $('issues').append(li); }
      if (wanted) await open(wanted);
    } catch { $('archive-note').textContent = 'The archive is unavailable at the moment.'; }
  })();
})();
