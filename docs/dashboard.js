/**
 * dashboard.js — the job seeker's progress page
 *
 * The conversation and the dossier stay on the front page. This page is for
 * watching the work: what Jobby decided, what it sent, what it prepared, and what
 * it is stuck on.
 *
 * ── The one rule ───────────────────────────────────────────────────────────
 *
 * Every number and every state on this page comes from an endpoint. Nothing is
 * inferred from a chat message, and nothing is shown optimistically. If the
 * applications endpoint says two are prepared, the page says two, even if a
 * message in the transcript said three.
 *
 * The reason is that this page's whole purpose is to be believed. A progress
 * dashboard that flatters itself is worse than no dashboard: a candidate who
 * trusts it and is wrong about their pipeline stops checking.
 *
 * ── "Needs you" is first, and is allowed to be empty ──────────────────────────────────
 *
 * It is the only section that is allowed to be the answer to "what should I do
 * now". An empty list says so plainly — "nothing is waiting on you" — rather than
 * hiding, because a section that appears and disappears looks like a bug.
 */

const el = (id) => document.getElementById(id);

function node(tag, className, text) {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}

function clear(n) {
  while (n && n.firstChild) n.removeChild(n.firstChild);
}

function ago(iso) {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return '';
  const secs = Math.max(0, (Date.now() - then) / 1000);
  if (secs < 60) return 'just now';
  if (secs < 3600) return `${Math.floor(secs / 60)} min ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)} h ago`;
  if (secs < 604800) return `${Math.floor(secs / 86400)} d ago`;
  return new Date(iso).toLocaleDateString();
}

const state = {
  session: null,
  applications: null,
  outreach: null,
  history: null,
  dossier: null,
  fifo: null,
  errors: [],
};

const money = (n) => (n === null || n === undefined ? '' :
  Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 }));

// ── what needs you ──────────────────────────────────────────────────────────

/**
 * The blocking list, and the other things that are not blocking but are not
 * finished either.
 *
 * Drawn from three places, because "what needs you" is not one thing:
 *  - application notes with severity blocking or needs_answer
 *  - a claim gate that has not been satisfied
 *  - no dossier at all, which blocks everything downstream
 */
function renderNeedsYou() {
  const host = el('needs-you-body');
  const count = el('needs-you-count');
  if (!host) return;
  clear(host);

  const items = [];

  // 1. No dossier. First, because everything else depends on it.
  if (state.session && state.session.hasDossier === false) {
    items.push({
      severity: 'blocking',
      kind: 'no_dossier',
      title: 'Jobby has nothing on file for you yet',
      detail: 'Everything else waits on this. You do not need a resume — open the front page '
        + 'and just start talking, and it will write the record down as you go.',
      href: 'index.html#jobby',
      cta: 'Start the conversation',
    });
  }

  // 2. The send identity.
  //
  //    A candidate with an assigned mailbox on our own domain can send: the
  //    address is derived from their own name and we receive the mail, so there
  //    is no unproved third-party address in the path. That is not a blocker, so
  //    it is not listed here — but it is not nothing either, and a candidate who
  //    has never been told what address they send from is being asked to trust a
  //    detail they cannot see. It gets a line on the mission card instead.
  //
  //    The one case that IS a blocker: no mailbox and no name to derive one from,
  //    because then there is no identity to send as at all.
  //
  //    The shape is `session.email.verified` — an object, not a string. The first
  //    version read `session.claimVerified`, which does not exist, so this check
  //    never fired and the one thing that stops every send was invisible on the
  //    dashboard built to surface blockers.
  const mail = state.session && state.session.email;
  const client = state.session && state.session.client;
  if (client && !client.mailbox) {
    items.push({
      severity: 'blocking',
      kind: 'no_send_identity',
      title: 'Jobby does not know what to send as yet',
      detail: 'Everything it sends needs an address, and it allocates one from the name on your '
        + 'record. Tell it the name you want to be known by and it will give you an address on '
        + 'this service.',
      href: 'index.html#jobby',
      cta: 'Tell it your name',
    });
  }

  // 3. Application notes.
  const apps = (state.applications && state.applications.applications) || [];
  for (const n of (state.applications && state.applications.needsYou) || []) {
    const blocking = n.severity === 'blocking';
    items.push({
      severity: blocking ? 'blocking' : 'needs_answer',
      kind: n.kind,
      title: n.requirement
        ? `${n.requirement} — ${blocking ? 'this job asks for it' : 'the posting asks, your record is silent'}`
        : (blocking ? 'Something blocks this application' : 'This posting asks about something your record does not cover'),
      detail: n.detail || '',
      action: n.action || null,
      url: n.url || null,
      role: n.role || null,
    });
  }

  // 4. A kill switch left on is not "needs you" — it is a state. Skipped here on
  //    purpose; it is on the mission card instead, where a glance catches it.

  if (count) {
    const blocking = items.filter((i) => i.severity === 'blocking').length;
    count.textContent = items.length === 0
      ? 'Nothing is waiting on you right now.'
      : `${items.length} thing${items.length === 1 ? '' : 's'} · ${blocking} blocking`;
  }

  if (!items.length) {
    const ok = node('div', 'all-clear');
    ok.appendChild(node('h3', null, 'Nothing needs you'));
    ok.appendChild(node('p', null,
      'No application is blocked and no question is outstanding. Jobby is working through '
      + 'the plan on its own.'));
    host.appendChild(ok);
    return;
  }

  // Blocking first. A list sorted worst-first is the only ordering a person can act on.
  items.sort((a, b) => (a.severity === 'blocking' ? 0 : 1) - (b.severity === 'blocking' ? 0 : 1));

  const list = node('ul', 'needs-list');
  for (const it of items) {
    const li = node('li', 'need need-' + it.severity);
    const head = node('div', 'need-head');
    head.appendChild(node('span', 'need-severity',
      it.severity === 'blocking' ? 'Blocking' : 'Needs an answer'));
    head.appendChild(node('span', 'need-kind', it.kind));
    li.appendChild(head);
    li.appendChild(node('h3', 'need-title', it.title));
    if (it.detail) li.appendChild(node('p', 'need-detail', it.detail));
    if (it.action) li.appendChild(node('p', 'need-action', it.action));
    if (it.role) li.appendChild(node('p', 'need-role', it.role));
    const link = node('a', 'button button-small', it.cta || 'Open it');
    link.href = it.url || it.href || 'index.html#jobby';
    li.appendChild(link);
    list.appendChild(li);
  }
  host.appendChild(list);
}

// ── mission ─────────────────────────────────────────────────────────────────

function renderMission() {
  const host = el('mission-body');
  if (!host) return;
  clear(host);
  const c = state.session && state.session.client;
  if (!c) {
    host.appendChild(node('p', 'empty-note', 'Could not load your mission.'));
    return;
  }

  // The state, in the candidate's terms.
  const card = node('div', 'mission-card');
  card.appendChild(node('h3', 'mission-state',
    c.missionState === 'seeking' ? 'Looking for income' : (c.missionState || '—')));

  // The kill switch is unmissable and says what it is doing, because a candidate
  // who switched it on an hour ago has probably forgotten.
  if (c.killSwitch) {
    const ks = node('div', 'mission-alert');
    ks.appendChild(node('strong', null, 'Emergency stop is on. '));
    ks.appendChild(document.createTextNode('Nothing will be sent until you turn it off.'));
    card.appendChild(ks);
  }

  const rows = node('dl', 'mission-rows');
  const add = (k, v) => { rows.appendChild(node('dt', null, k)); rows.appendChild(node('dd', null, v)); };
  add('Name', c.displayName || 'not set');
  // Which record the name above was read from, said out loud.
  //
  // The card used to show a name held in a column that nothing else wrote, so a
  // candidate could correct their name in chat, watch the dossier panel change,
  // and find this card unchanged — with no way to tell whether the change had
  // been lost or had simply gone somewhere else on the page. Naming the record
  // turns "is this right?" into something the candidate can actually check.
  if (c.nameSource) {
    const src = node('dd', 'mission-source');
    src.textContent = c.nameSource === 'dossier'
      ? 'from your record — the same one Jobby reads, and the one you change in chat'
      : (c.nameSource === 'client'
        ? 'from your account — change it below and your record will follow'
        : 'not set yet');
    rows.appendChild(node('dt', 'mission-source-key', 'Read from'));
    rows.appendChild(src);
  }
  add('Email', (state.session.email && state.session.email.email) || 'not given');
  if (c.mailbox) {
    const isClaimed = !!(state.session.email && state.session.email.verified);
    add(isClaimed ? 'Sending from' : 'Your Jobby address',
      // The exact address, including any collision suffix. A candidate who has
      // never seen this cannot tell whether it is them, and "jordan.ellis2@" is
      // not something to discover from a bounce.
      c.mailbox + (isClaimed ? ' (also verified)' : ''));
  }
  add('Send mode', c.autonomy === 'auto'
    ? `Sends on its own, up to ${c.dailySendCap} a day`
    : 'Drafts and asks before sending');
  add('Sent today', (() => {
    // Never a bare interpolation of two fields that might not be there. This
    // rendered the literal text "undefined of undefined" for any candidate in
    // draft mode, because the send-check omitted the counts on that branch — and
    // a candidate who cannot read their own send count cannot tell whether the
    // cap is working.
    const s = state.session.sending;
    if (!s) return '—';
    const sent = Number.isFinite(s.sent) ? s.sent : null;
    const cap = Number.isFinite(s.cap) ? s.cap : null;
    if (sent === null && cap === null) return '—';
    if (sent === null) return `up to ${cap} a day`;
    if (cap === null) return `${sent} sent`;
    return `${sent} of ${cap}`;
  })());
  card.appendChild(rows);

  // The weaker identity, named. Sending from an assigned address is allowed and
  // is not a problem — but it is a different thing from sending from an address
  // you proved, and a candidate deserves to know which one they have rather than
  // finding out from a reply that landed in the relay.
  const mailState = state.session.email;
  if (c.mailbox && mailState && mailState.verified !== true) {
    const softer = node('div', 'mission-note');
    softer.appendChild(node('strong', null, 'Sending from a Jobby address. '));
    softer.appendChild(document.createTextNode(
      'That is fine and nothing is blocked by it. It is the name on your record, not an inbox you '
      + 'have proved, so replies come back through Jobby rather than to you. Verify an email you '
      + 'own if you would rather send from that.'));
    card.appendChild(softer);
  }
  host.appendChild(card);

  // Tracks, with the reason. The reason matters more than the track: a candidate
  // who does not know why Jobby picked a track will not trust it.
  const tracks = state.session.tracks || [];
  const tHost = node('div', 'mission-tracks');
  tHost.appendChild(node('h3', 'mission-subhead', 'Your tracks'));
  if (!tracks.length) {
    tHost.appendChild(node('p', 'empty-note', 'No tracks are on yet.'));
  } else {
    const list = node('ul', 'track-list');
    for (const t of tracks) {
      const li = node('li', 'track-item');
      li.appendChild(node('span', 'track-name', t.name || `Track ${t.id}`));
      const why = (c.trackReasons || {})[String(t.id)];
      if (why) li.appendChild(node('span', 'track-why', why));
      list.appendChild(li);
    }
    tHost.appendChild(list);
  }
  host.appendChild(tHost);
  host.appendChild(missionEditor(c));
}

/**
 * The save status, held in state rather than in a DOM node.
 *
 * The first version wrote the confirmation into a `.mission-hint` element and then
 * called `renderMission()` — which clears the mission host and rebuilds it, taking
 * the element it had just written into with it. The save succeeded on the server,
 * the card re-rendered with the new value, and the candidate was shown a form
 * sitting there as though nothing had happened: no confirmation, no error, no
 * change they did not have to notice themselves. A working feature that reports
 * nothing is indistinguishable from a broken one, which is the whole problem this
 * work started from.
 *
 * So the message lives here, is set before the re-render, and is read back by
 * whichever copy of the form is on screen afterwards.
 */
let missionSave = null;

/**
 * The mission card, made editable.
 *
 * This card was a `<dl>` of text with no controls on it at all, and the fields it
 * showed lived on a table that no tool in the agent's surface could write. So the
 * honest description of this screen was "you can read your mission, nothing can
 * change it" — including the parts that are unambiguously the candidate's to set,
 * like their own name.
 *
 * It saves through the same PATCH the front page's toggles use, and the name goes
 * to the dossier as well as the card, because those were two records and are now
 * one. A save re-reads both the session and the dossier snapshot and re-renders
 * them together: if they ever disagreed again, the candidate would see it in the
 * same glance rather than having to go looking for it.
 */
function missionEditor(c) {
  const wrap = node('div', 'mission-editor');
  const form = node('form', 'mission-form');
  form.setAttribute('aria-label', 'Change your details');

  const field = (labelText, input) => {
    const l = node('label', 'mission-field');
    l.appendChild(node('span', 'mission-field-label', labelText));
    l.appendChild(input);
    return l;
  };

  const name = document.createElement('input');
  name.type = 'text';
  name.id = 'mission-edit-name';
  name.value = c.displayName || '';
  name.placeholder = 'The name you want to be known by';
  name.autocomplete = 'name';

  const phone = document.createElement('input');
  phone.type = 'tel';
  phone.id = 'mission-edit-phone';
  phone.value = c.phone || '';
  phone.placeholder = 'not given';
  phone.autocomplete = 'tel';

  const where = document.createElement('input');
  where.type = 'text';
  where.id = 'mission-edit-location';
  where.value = c.location || '';
  where.placeholder = 'Where you are based';

  const stateSel = document.createElement('select');
  stateSel.id = 'mission-edit-state';
  for (const [v, t] of [['seeking', 'Looking for income'], ['advancing', 'Interviews'],
    ['placed', 'Placed'], ['paused', 'Paused']]) {
    const o = node('option', null, t);
    o.value = v;
    if (c.missionState === v) o.selected = true;
    stateSel.appendChild(o);
  }

  const modeSel = document.createElement('select');
  modeSel.id = 'mission-edit-mode';
  for (const [v, t] of [['auto', 'Send on its own'], ['draft', 'Draft and ask me first']]) {
    const o = node('option', null, t);
    o.value = v;
    if ((c.autonomy || 'draft') === v) o.selected = true;
    modeSel.appendChild(o);
  }

  const cap = document.createElement('input');
  cap.type = 'number';
  cap.id = 'mission-edit-cap';
  cap.min = '0';
  cap.max = '500';
  cap.value = String(c.dailySendCap ?? 15);

  form.appendChild(field('Name', name));
  form.appendChild(field('Phone', phone));
  form.appendChild(field('Where you are based', where));
  form.appendChild(field('Your situation', stateSel));
  form.appendChild(field('Send mode', modeSel));
  form.appendChild(field('Sends per day', cap));

  // The emergency stop, in the one place a candidate looks when they want it.
  // Checkbox rather than a select, because it is a switch and reads as one.
  const stopLabel = node('label', 'mission-field mission-switch');
  const stop = document.createElement('input');
  stop.type = 'checkbox';
  stop.id = 'mission-edit-stop';
  stop.checked = !!c.killSwitch;
  stopLabel.appendChild(stop);
  stopLabel.appendChild(node('span', null, 'Emergency stop — nothing is sent while this is on'));
  form.appendChild(stopLabel);

  const bar = node('div', 'mission-form-bar');
  const save = node('button', 'button button-small', 'Save');
  save.type = 'submit';
  bar.appendChild(save);
  // The status line, seeded from the last save rather than from nothing, because
  // the form is rebuilt underneath it every time the card re-renders.
  const hint = node('span', 'mission-hint');
  hint.setAttribute('role', 'status');
  if (missionSave) {
    hint.className = 'mission-hint is-' + missionSave.kind;
    hint.textContent = missionSave.text;
  }
  bar.appendChild(hint);
  form.appendChild(bar);
  wrap.appendChild(form);

  // The address, and what it will do when the name changes.
  //
  // It follows the name now. It used to be frozen at the address first assigned,
  // on the grounds that mail had already gone out from it — which left a candidate
  // named Joe Lee applying as `jordan.ellis@`, a mismatch every recruiter can see
  // and nobody can explain.
  //
  // Said out loud anyway, because the old address keeps working for a while and a
  // candidate who has just been renamed will get a reply at the old one. They
  // should know it is expected rather than assume the rename went wrong.
  if (c.mailbox) {
    const note = node('p', 'mission-note');
    note.appendChild(node('strong', null, 'Your address follows your name. '));
    note.appendChild(document.createTextNode(
      'Change the name above and this becomes the address you send from. Anything already sent '
      + 'from ' + c.mailbox + ' keeps working — replies to it still reach you — so a recruiter '
      + 'answering an application you made under your old name is not a mistake on your part.'));
    wrap.appendChild(note);
  }

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    save.disabled = true;
    missionSave = { kind: 'busy', text: 'Saving…' };
    hint.className = 'mission-hint';
    hint.textContent = 'Saving…';
    try {
      const res = await fetch('/api/jobby/client', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          display_name: name.value.trim(),
          phone: phone.value.trim(),
          location: where.value.trim(),
          mission_state: stateSel.value,
          autonomy: modeSel.value,
          daily_send_cap: Number(cap.value),
          kill_switch: stop.checked,
        }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error((body && body.error) || 'could not save');
      if (body.fieldErrors && body.fieldErrors.length) {
        throw new Error(body.fieldErrors.map((e) => e.error).join('; '));
      }

      // Read both records back rather than trusting what was typed, so what the
      // page shows next is what is actually on file.
      const [session, dossier] = await Promise.all([
        getJson('/api/jobby/session'),
        getJson('/api/jobby/dossier'),
      ]);
      if (session) state.session = session;
      if (dossier) state.dossier = dossier;

      // Set before the re-render, so the rebuilt form can pick it up. Setting it
      // after is what threw the message away the first time.
      const LABEL = {
        name: 'your name', phone: 'your phone', location: 'where you are based',
        mission_state: 'your situation', autonomy: 'the send mode',
        daily_send_cap: 'the daily cap', kill_switch: 'the emergency stop',
        tracks: 'your tracks', track_reasons: 'your tracks', notes: 'your notes',
      };
      const moved = (body.changed || []).map((f) => LABEL[f] || f);
      missionSave = {
        kind: 'good',
        text: !moved.length
          ? 'Nothing needed changing — everything you typed was already on file.'
          : 'Saved: ' + moved.join(', ') + '. Your record and this card now agree.',
      };

      renderMission();
      renderDossier();
      renderNeedsYou();
    } catch (e) {
      // Says what did not save, and that the rest was left alone — a failed save
      // that looks like a successful one is the same bug as the one being fixed.
      missionSave = { kind: 'bad', text: 'That did not save: ' + e.message + ' Nothing was changed.' };
      hint.className = 'mission-hint is-bad';
      hint.textContent = missionSave.text;
    } finally {
      save.disabled = false;
    }
  });

  return wrap;
}

// ── applications ────────────────────────────────────────────────────────────

function renderApplications() {
  const host = el('applications-body');
  if (!host) return;
  clear(host);
  const data = state.applications;
  if (!data) {
    host.appendChild(node('p', 'empty-note', 'Could not load your applications.'));
    return;
  }
  const apps = data.applications || [];
  if (!apps.length) {
    const empty = node('div', 'empty-block');
    empty.appendChild(node('p', null, 'No applications prepared yet.'));
    empty.appendChild(node('p', 'empty-note',
      'When you ask Jobby about a specific job it builds a packet for that job — checked against '
      + 'what the posting actually asks for — and it appears here.'));
    host.appendChild(empty);
    return;
  }

  // Counts, each labelled so none can be misread. "Prepared" is emphatically not
  // "sent", and putting them in one sentence with an "and" would invite it.
  const counts = node('div', 'app-counts');
  const cell = (v, label, note) => {
    const c = node('div', 'stat-cell');
    c.appendChild(node('span', 'stat-value', v));
    c.appendChild(node('span', 'stat-label', label));
    c.appendChild(node('span', 'stat-note', note));
    counts.appendChild(c);
  };
  cell((data.counts || {}).prepared || 0, 'Prepared', 'a packet exists');
  cell((data.counts || {}).submitted || 0, 'Submitted', 'actually sent to an employer');
  cell((data.counts || {}).blocked || 0, 'Blocked', 'cannot go out as written');
  cell((data.counts || {}).unconfirmedOpenings || 0, 'Unconfirmed', 'the link was not a specific job');
  host.appendChild(counts);

  const list = node('div', 'app-list');
  for (const a of apps) {
    const card = node('article', 'app-card');

    const head = node('div', 'app-head');
    head.appendChild(node('h3', 'app-title', a.role || (a.company ? a.company : 'Untitled')));
    // The status is stated in words. A dot coloured by CSS class is not readable
    // by a screen reader and is not precise to a person either.
    const status = a.submittedAt ? 'submitted' : (a.status === 'running' ? 'running' : 'prepared');
    head.appendChild(node('span', 'app-status app-status-' + status,
      status === 'submitted' ? 'Submitted' : status === 'running' ? 'Being worked on' : 'Prepared, not sent'));
    card.appendChild(head);

    const meta = node('p', 'app-meta');
    meta.textContent = [a.company, a.url ? shortUrl(a.url) : null]
      .filter(Boolean).join(' · ');
    card.appendChild(meta);

    if (a.viewUsed) {
      const v = node('p', 'app-view');
      const view = (state.session.views || []).find((x) => x.view === a.viewUsed);
      v.textContent = 'Read as: ' + (view ? view.label : a.viewUsed);
      card.appendChild(v);
    }

    if (a.eligibility) {
      const el2 = node('p', 'app-eligibility app-eligibility-' + a.eligibility.verdict);
      el2.textContent = eligibilityLine(a.eligibility);
      card.appendChild(el2);
    }

    if (a.packet && a.packet.leadingWith && a.packet.leadingWith.length) {
      const lead = node('p', 'app-lead');
      lead.textContent = 'Leads with: ' + a.packet.leadingWith.join(', ');
      card.appendChild(lead);
    }

    if (a.validation && a.validation.verdict !== 'direct_posting') {
      const warn = node('p', 'app-warn');
      warn.textContent = 'Opening not confirmed: ' + (a.validation.reasons[0] || a.validation.verdict);
      card.appendChild(warn);
    }

    // Validated-at: only ever set by a real fetch of the posting. It is null in
    // practice, and the page says "not confirmed live" rather than showing a
    // date that would imply a check nobody made.
    card.appendChild(node('p', 'app-validated',
      a.validatedAt ? 'Posting confirmed live ' + ago(a.validatedAt) : 'Posting has not been confirmed live'));

    const notes = a.notes || [];
    if (notes.length) {
      const ul = node('ul', 'app-notes');
      for (const n of notes) {
        const li = node('li', 'app-note app-note-' + (n.severity || 'info'));
        li.appendChild(node('span', 'app-note-severity', n.severity || 'info'));
        li.appendChild(node('span', 'app-note-text', n.detail || ''));
        ul.appendChild(li);
      }
      card.appendChild(ul);
    }

    if (a.url) {
      const link = node('a', 'app-link', 'Open the posting');
      link.href = a.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      card.appendChild(link);
    }
    list.appendChild(card);
  }
  host.appendChild(list);
}

function shortUrl(u) {
  try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return u; }
}

function eligibilityLine(e) {
  switch (e.verdict) {
    case 'eligible': return 'Checked against the posting: nothing outstanding';
    case 'gaps': return `${(e.missing || []).length} gap(s) against what the posting asks for`;
    case 'unknown_requirements':
      return 'The posting does not state its requirements, so nothing could be checked';
    default: return e.verdict;
  }
}

// ── outreach ────────────────────────────────────────────────────────────────

function renderOutreach() {
  const host = el('outreach-body');
  if (!host) return;
  clear(host);
  const rows = (state.outreach && state.outreach.outreach) || [];
  if (!rows.length) {
    const empty = node('div', 'empty-block');
    empty.appendChild(node('p', null, 'Nothing sent yet.'));
    const s = state.session && state.session.sending;
    if (s) {
      empty.appendChild(node('p', 'empty-note',
        `${s.remaining} of ${s.cap} sends left today. Jobby will use them when it has something worth sending.`));
    }
    host.appendChild(empty);
    return;
  }
  const list = node('ul', 'outreach-list');
  for (const o of rows) {
    const li = node('li', 'outreach-item outreach-' + (o.status || 'unknown'));
    li.appendChild(node('span', 'outreach-status', o.status || 'unknown'));
    const main = node('div', 'outreach-main');
    main.appendChild(node('span', 'outreach-to', o.recipient || ''));
    main.appendChild(node('span', 'outreach-subject', o.subject || ''));
    if (o.error) main.appendChild(node('span', 'outreach-error', o.error));
    li.appendChild(main);
    li.appendChild(node('span', 'outreach-when', ago(o.created_at || o.createdAt)));
    list.appendChild(li);
  }
  host.appendChild(list);
}

// ── activity ────────────────────────────────────────────────────────────────

/**
 * Recent activity, from the chat history.
 *
 * Tool calls are what makes this a progress view rather than a transcript: a
 * list of what Jobby actually did, so a candidate who comes back after a day can
 * see it worked rather than having to read what it said about working.
 */
function renderActivity() {
  const host = el('activity-body');
  if (!host) return;
  clear(host);
  const messages = (state.history && state.history.messages) || [];
  if (!messages.length) {
    host.appendChild(node('p', 'empty-note', 'No activity yet.'));
    return;
  }

  const events = [];
  for (const m of messages) {
    for (const t of m.tool_calls || []) {
      events.push({
        when: m.created_at,
        tool: t.tool,
        ok: t.ok !== false && !t.error,
        error: t.error || (t.result && t.result.error) || null,
        detail: describeTool(t),
      });
    }
  }

  if (!events.length) {
    host.appendChild(node('p', 'empty-note',
      'Nothing has needed doing yet. Start a conversation on the front page.'));
    return;
  }

  events.sort((a, b) => new Date(b.when || 0) - new Date(a.when || 0));
  const list = node('ol', 'activity-list');
  for (const e of events.slice(0, 40)) {
    const li = node('li', 'activity-item ' + (e.ok ? 'activity-ok' : 'activity-failed'));
    li.appendChild(node('span', 'activity-when', ago(e.when)));
    li.appendChild(node('span', 'activity-tool', (e.tool || 'tool').replace(/^jobby_/, '').replace(/_/g, ' ')));
    li.appendChild(node('span', 'activity-state', e.ok ? 'done' : 'failed'));
    if (e.detail) li.appendChild(node('span', 'activity-detail', e.detail));
    if (e.error) li.appendChild(node('span', 'activity-error', e.error));
    list.appendChild(li);
  }
  host.appendChild(list);
}

/** A one-line description of what a tool call actually did. */
function describeTool(t) {
  const r = t.result || {};
  if (t.error) return String(t.error).slice(0, 120);
  if (r.error) return String(r.error).slice(0, 120);
  if (r.changes && r.changes.length) return r.changes.join('; ').slice(0, 120);
  if (r.notes && r.notes.length) return `${r.notes.length} note(s) on the application`;
  if (r.tracks) return 'tracks → ' + r.tracks.join(', ');
  if (typeof r.saved === 'boolean') return r.saved ? 'saved' : 'not saved';
  if (r.published) return 'published';
  if (r.mailbox) return String(r.mailbox);
  return '';
}

// ── dossier snapshot ────────────────────────────────────────────────────────

function renderDossier() {
  const host = el('dossier-body');
  if (!host) return;
  clear(host);
  const d = state.dossier && state.dossier.dossier;
  if (!d) {
    host.appendChild(node('p', 'empty-note',
      'No record yet. Jobby builds it as you talk — it does not need a resume.'));
    return;
  }

  const card = node('div', 'dossier-snapshot');
  if (d.name) card.appendChild(node('h3', 'dossier-name', d.name));
  if (d.current_title) card.appendChild(node('p', 'dossier-title', d.current_title));

  const rows = node('dl', 'dossier-rows');
  const add = (k, v) => { rows.appendChild(node('dt', null, k)); rows.appendChild(node('dd', null, v)); };

  const employment = Array.isArray(d.employment) ? d.employment : [];
  add('Roles on file', employment.length ? String(employment.length) : 'none yet');
  const certs = Array.isArray(d.certifications) ? d.certifications : [];
  add('Certifications', certs.length ? String(certs.length) : 'none yet');
  const tickets = Array.isArray(d.tickets) ? d.tickets : [];
  add('Tickets', tickets.length ? String(tickets.length) : 'none yet');
  const skills = Array.isArray(d.skills) ? d.skills : [];
  add('Skills', skills.length ? String(skills.length) : 'none yet');
  const edu = Array.isArray(d.education) ? d.education : [];
  add('Education', edu.length ? String(edu.length) : 'none yet');
  if (state.session && state.session.dossierRevision) {
    add('Last updated', state.session.dossierRevision);
  }
  card.appendChild(rows);

  // What it cannot show, per the default view. A record that looks complete when
  // it is not is the exact failure this product keeps having to catch.
  const viewId = state.session && state.session.defaultView;
  const view = (state.session.views || []).find((v) => v.view === viewId);
  // The field is `whatItCannotShow` — read from the live payload, not guessed.
  // `cannotShow` returns undefined, so the one panel explaining what a record is
  // silent on silently showed nothing.
  if (view && view.whatItCannotShow && view.whatItCannotShow.length) {
    const gaps = node('div', 'dossier-gaps');
    gaps.appendChild(node('h4', null, `Your record cannot show: ${view.label.toLowerCase()}`));
    const ul = node('ul');
    for (const g of view.whatItCannotShow) ul.appendChild(node('li', null, g));
    gaps.appendChild(ul);
    gaps.appendChild(node('p', 'empty-note',
      'Those are not gaps in you. They are things your record is silent on, and Jobby will not '
      + 'fill them in for you.'));
    card.appendChild(gaps);
  }

  const link = node('a', 'button button-small', 'Open the full record');
  link.href = 'index.html#dossier-panel';
  card.appendChild(link);
  host.appendChild(card);
}

// ── loading ─────────────────────────────────────────────────────────────────

async function getJson(path) {
  const response = await fetch(path, { headers: { Accept: 'application/json' } });
  if (response.status === 401 || response.status === 404) return null;
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error((body && body.error) || 'could not load ' + path);
  return body;
}

async function load() {
  // Every panel renders from whatever arrived, and a failed one says it failed.
  // Rendering nothing for an endpoint that errored would look identical to an
  // empty account.
  const jobs = [
    ['session', '/api/jobby/session', renderMission],
    ['applications', '/api/jobby/applications', renderApplications],
    ['outreach', '/api/jobby/outreach', renderOutreach],
    ['history', '/api/jobby/history', renderActivity],
    ['dossier', '/api/jobby/dossier', renderDossier],
  ];

  const results = await Promise.allSettled(jobs.map(([, path]) => getJson(path)));
  results.forEach((r, i) => {
    const [key, , render] = jobs[i];
    if (r.status === 'fulfilled') {
      state[key] = r.value;
      // The mission renderer also has to see the other payloads.
      if (key === 'session') render();
    } else {
      state.errors.push(key + ': ' + r.reason.message);
      const host = el(key === 'session' ? 'mission-body' : key + '-body');
      if (host) {
        clear(host);
        host.appendChild(node('p', 'empty-note', 'Could not load: ' + r.reason.message));
      }
    }
  });

  renderNeedsYou();
  renderMission();
  renderApplications();
  renderOutreach();
  renderActivity();
  renderDossier();
}

function init() {
  load();
  // Refreshing the counts is not a feature — it is the difference between a
  // dashboard and a snapshot. 60s, not 5s: this page is not a trading screen,
  // and a candidate leaving it open all day should not be hammering the relay.
  setInterval(() => { load(); }, 60000);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
