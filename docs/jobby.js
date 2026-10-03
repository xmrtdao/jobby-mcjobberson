/* Jobby — the agent panel.
 *
 * Talks to the portal's own origin, which proxies to the relay. The browser
 * never holds a relay key; the relay identifies the client from an HttpOnly
 * session cookie.
 *
 * Every fetch is same-origin and goes through /api/jobby/*, so a failure here
 * is a portal or relay problem, not a CORS one.
 */


/* The mission state is a machine value - the relay sends "seeking", "placed",
 * "advancing" or "paused" - so this is a lookup by key rather than a
 * translation of prose. A value the table does not know falls through to the
 * English text, so a state added relay-side still shows something readable
 * rather than a blank. */
const JOBBY_MISSION_LABELS = {
  seeking:   { en: 'No income secured. Every day counts.', es: 'Todavía no hay ingresos. Cada día cuenta.' },
  placed:    { en: 'Income secured. Onward.', es: 'Ingresos asegurados. Ahora a por más.' },
  advancing: { en: 'Moving up. Keep the pipeline warm.', es: 'Ascendiendo. Mantén el contacto vivo.' },
  paused:    { en: 'Paused. Nothing is being sent.', es: 'En pausa. No se está enviando nada.' },
};

function missionLabel(state) {
  var key = String(state == null ? '' : state).trim().toLowerCase();
  var entry = JOBBY_MISSION_LABELS[key];
  if (!entry) return key;
  return (window.JobbyI18n && window.JobbyI18n.isSpanish()) ? entry.es : entry.en;
}

const jobbyState = {
  clientId: null,
  tracks: [],
  // Track reasons and the track-5 brief come from the relay's decision rather
  // than being re-derived here, so the page cannot disagree with the plan.
  trackReasons: {},
  fifo: null,
  actions: [],
  revision: 0,
  sending: null,
  busy: false,
  historyLoaded: false,
};

const jobbyEls = {};

function cacheJobbyEls() {
  const ids = ['jobby-status', 'jobby-mission', 'jobby-tracks', 'jobby-autonomy',
    'jobby-kill-switch', 'jobby-cap', 'jobby-log', 'jobby-empty', 'jobby-form',
    'jobby-input', 'jobby-send', 'jobby-hint', 'jobby-track-list', 'jobby-plan',
    'jobby-edits',
    'jobby-verify', 'jobby-verify-verified', 'jobby-verify-verified-text',
    'jobby-verify-unverified', 'jobby-verify-lead', 'jobby-verify-form',
    'jobby-verify-email', 'jobby-verify-send', 'jobby-verify-code-form',
    'jobby-verify-code', 'jobby-verify-confirm', 'jobby-verify-status'];
  ids.forEach(id => { jobbyEls[id] = document.getElementById(id); });
}

async function jobbyApi(method, path, body) {
  const init = { method, headers: {} };
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  const text = await res.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { /* non-JSON error page */ }
  if (!res.ok) {
    const err = new Error(data.error || `request failed (${res.status})`);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

const TRACK_NAMES = {
  1: 'Contract consulting',
  2: 'Temporary & contract',
  3: 'Full-time employment',
  4: 'ATS automation',
  5: 'FIFO & remote-site roles',
};

// Kept as a list rather than derived from Object.keys, because the order is the
// order the plan is presented in and object key order is not a contract.
const TRACK_IDS = [1, 2, 3, 4, 5];
const TRACK_COUNT = TRACK_IDS.length;

const MISSION_LABELS = {
  seeking: missionLabel('seeking'),
  placed: missionLabel('placed'),
  advancing: missionLabel('advancing'),
  paused: missionLabel('paused'),
};

function jobbyEl(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function addJobbyMessage(role, content, toolCalls) {
  const log = jobbyEls['jobby-log'];
  if (!log) return;
  const empty = jobbyEls['jobby-empty'];
  if (empty) empty.remove();

  const wrap = jobbyEl('div', 'jobby-msg jobby-msg-' + role);
  wrap.appendChild(jobbyEl('span', 'jobby-who', role === 'user' ? 'You' : 'Jobby'));
  wrap.appendChild(jobbyEl('p', 'jobby-text', content));
  log.appendChild(wrap);

  // Show what Jobby actually did, not just what it said it did.
  if (Array.isArray(toolCalls) && toolCalls.length) {
    const notes = toolCalls.map(t => {
      if (t.error) return t.tool + ': ' + t.error;
      const r = t.result;
      if (r && r.changes && r.changes.length) return r.changes.join(' ');
      if (r && r.blocked) return `${t.tool} blocked — ${r.reason}`;
      if (r && r.tracks) return `tracks → ${r.tracks.join(', ')}`;
      if (r && typeof r.ok === 'boolean') return `${t.tool} ${r.ok ? 'ok' : 'failed'}`;
      return t.tool + ' ran';
    });
    wrap.appendChild(jobbyEl('p', 'jobby-tools', notes.join(' · ')));
  }
  log.scrollTop = log.scrollHeight;
}

function setJobbyBusy(busy, label) {
  jobbyState.busy = busy;
  if (!jobbyEls['jobby-send'] || !jobbyEls['jobby-input']) return;
  jobbyEls['jobby-send'].disabled = busy;
  jobbyEls['jobby-input'].disabled = busy;
  jobbyEls['jobby-send'].textContent = busy ? (label || 'Working…') : 'Send';
}

function setJobbyHint(text, kind) {
  if (!jobbyEls['jobby-hint']) return;
  jobbyEls['jobby-hint'].textContent = text;
  jobbyEls['jobby-hint'].dataset.kind = kind || 'neutral';
}

async function loadJobbySession() {
  try {
    const s = await jobbyApi('GET', '/api/jobby/session');
    jobbyState.clientId = s.client?.id ?? null;
    jobbyState.tracks = s.client?.tracks ?? [];
    jobbyState.trackReasons = s.client?.trackReasons ?? {};
    jobbyState.fifo = s.fifo ?? null;
    jobbyState.actions = s.actions ?? [];
    jobbyState.sending = s.sending ?? null;
    renderJobbyStatus(s);
    renderJobbyTracks();
    renderJobbyPlan();
    if (s.hasDossier) {
      setJobbyHint('Ask Jobby anything. Tell it facts about yourself and it will write them into your dossier.', 'neutral');
      await loadJobbyHistory();
    } else {
      // Must not tell a resume-less visitor to upload a resume. It contradicted
      // the invitation two inches above it, and uploading is not a precondition
      // — Jobby builds one from conversation.
      setJobbyHint('No resume needed. Tell me what you have done and I will write it down as we go, then build the resume from your own words.', 'neutral');
    }
  } catch (e) {
    setJobbyHint('Jobby is not reachable right now: ' + e.message, 'error');
  }
}

function renderJobbyStatus(s) {
  const c = s.client || {};
  if (jobbyEls['jobby-status']) jobbyEls['jobby-status'].hidden = false;
  if (jobbyEls['jobby-mission']) {
    jobbyEls['jobby-mission'].textContent = MISSION_LABELS[c.missionState] || c.missionState || '—';
  }
  if (jobbyEls['jobby-tracks']) {
    // The total comes from TRACK_COUNT, not a literal. It was 4 while five
    // tracks existed, so a returning candidate was told "4 of 4" with one row
    // silently missing.
    jobbyEls['jobby-tracks'].textContent = (c.tracks || []).length
      ? tn('{n} of {total} tracks active').replace('{n}', (c.tracks || []).length).replace('{total}', TRACK_COUNT)
      : tn('No tracks active');
  }
  if (jobbyEls['jobby-autonomy']) jobbyEls['jobby-autonomy'].checked = c.autonomy === 'auto';
  // Re-translate the dynamic region. The track rows, plan and actions are built
  // in JS after the page's own i18n pass has run, so they arrive in English
  // regardless of the stored language — this walks them so they match the page.
  if (window.JobbyI18n && typeof window.JobbyI18n.applyI18nTo === 'function') {
    window.JobbyI18n.applyI18nTo(document.getElementById('jobby-panel') || document.body);
  }
  if (jobbyEls['jobby-kill-switch']) jobbyEls['jobby-kill-switch'].checked = !!c.killSwitch;
  // The verification panel is part of the status bar, not a separate screen: it
  // is the gate on sending anything, and a gate the candidate cannot see is one
  // they only discover by being refused.
  renderJobbyVerify(s.email);
  renderJobbyCap(s.sending);
}

/* ── Email verification ────────────────────────────────────────────────── */

/**
 * Show whether this person has proved an address, and offer the only thing that
 * can change it.
 *
 * Two states, deliberately worded differently. After a code has been sent the
 * useful sentence is "we sent you a code", not "your email is not verified" -
 * someone looking at an unread message from us has already done the first half of
 * the job and telling them to verify their email reads as though we ignored
 * them.
 *
 * `setJobbyHint` is deliberately not reused here. That is the chat's line, and a
 * verification failure is not part of the conversation with Jobby; the status
 * area has its own so the two cannot overwrite each other.
 */
function renderJobbyVerify(email) {
  const panel = jobbyEls['jobby-verify'];
  if (!panel) return;
  const done = jobbyEls['jobby-verify-verified'];
  const todo = jobbyEls['jobby-verify-unverified'];
  const lead = jobbyEls['jobby-verify-lead'];
  const codeForm = jobbyEls['jobby-verify-code-form'];
  const emailInput = jobbyEls['jobby-verify-email'];
  const status = jobbyEls['jobby-verify-status'];

  panel.hidden = false;

  if (email && email.verified) {
    if (done) {
      done.hidden = false;
      const t = jobbyEls['jobby-verify-verified-text'];
      if (t) t.textContent = 'Email confirmed — ' + email.email;
    }
    if (todo) todo.hidden = true;
    return;
  }

  if (done) done.hidden = true;
  if (todo) todo.hidden = false;
  if (codeForm) codeForm.hidden = !(email && email.pending);

  if (email && email.pending) {
    const mins = email.pendingExpiresAt
      ? Math.max(1, Math.round((new Date(email.pendingExpiresAt) - Date.now()) / 60000))
      : null;
    if (lead) {
      lead.textContent = 'We sent a six-digit code to ' + (email.pendingEmail || 'your inbox')
        + '. It works once'
        + (mins ? ' and stops working in ' + mins + ' minute' + (mins === 1 ? '' : 's') + '.' : '.');
    }
    if (emailInput) emailInput.value = email.pendingEmail || '';
    if (status) { status.textContent = ''; status.removeAttribute('data-kind'); }
    return;
  }

  if (lead) {
    lead.textContent = 'Confirm your email and Jobby can apply to jobs on your behalf. '
      + 'It sends six digits to that inbox and you give them back here.';
  }
  // The address is left as the candidate typed it. A previous version pre-filled
  // it from a jobbyState field that nothing ever set, so it silently did nothing
  // and looked like it was working.
}

function setJobbyVerifyStatus(text, kind) {
  const el = jobbyEls['jobby-verify-status'];
  if (!el) return;
  el.textContent = text || '';
  if (kind) el.dataset.kind = kind; else el.removeAttribute('data-kind');
}

function wireJobbyVerify() {
  const form = jobbyEls['jobby-verify-form'];
  if (form) {
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const input = jobbyEls['jobby-verify-email'];
      const btn = jobbyEls['jobby-verify-send'];
      const addr = input ? input.value.trim() : '';
      if (!addr) return;
      if (btn) { btn.disabled = true; btn.textContent = 'Sending...'; }
      setJobbyVerifyStatus('Sending your code...', 'neutral');
      try {
        await jobbyApi('POST', '/api/jobby/claim', { email: addr });
        // Say what happened, not what was requested. "Sent" is a claim about the
        // world and the user will find out within a minute whether it is true.
        setJobbyVerifyStatus('Sent. Check that inbox.', 'ok');
        await refreshJobbyVerify();
      } catch (e) {
        // The endpoint's own words. It distinguishes "that does not look like an
        // email address" from "that is already in use" and from the hourly cap,
        // and paraphrasing any of them would be less useful than passing it on.
        setJobbyVerifyStatus(e.message, 'error');
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Send me a code'; }
      }
    });
  }

  const codeForm = jobbyEls['jobby-verify-code-form'];
  if (codeForm) {
    codeForm.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const input = jobbyEls['jobby-verify-code'];
      const emailInput = jobbyEls['jobby-verify-email'];
      const btn = jobbyEls['jobby-verify-confirm'];
      const code = input ? input.value.trim() : '';
      const addr = emailInput ? emailInput.value.trim() : '';
      if (!/^\d{6}$/.test(code)) {
        setJobbyVerifyStatus('That is not six digits.', 'error');
        return;
      }
      if (btn) { btn.disabled = true; btn.textContent = 'Checking...'; }
      setJobbyVerifyStatus('Checking...', 'neutral');
      try {
        await jobbyApi('POST', '/api/jobby/claim/verify', { email: addr, code });
        setJobbyVerifyStatus('Confirmed.', 'ok');
        if (input) input.value = '';
        await refreshJobbyVerify();
      } catch (e) {
        setJobbyVerifyStatus(e.message, 'error');
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Confirm'; }
      }
    });
  }
}

/**
 * Re-read the session and repaint the status bar only.
 *
 * Deliberately not loadJobbySession(): that also rewrites the chat hint and
 * reloads the conversation history, so confirming an email in the middle of a
 * message would wipe the hint the candidate was reading and scroll the log. This
 * is the one panel that has to repaint itself on its own.
 */
async function refreshJobbyVerify() {
  try {
    const s = await jobbyApi('GET', '/api/jobby/session');
    renderJobbyVerify(s.email);
  } catch (e) {
    setJobbyVerifyStatus('Could not check: ' + e.message, 'error');
  }
}

function renderJobbyCap(sending) {
  const el = jobbyEls['jobby-cap'];
  if (!el) return;
  jobbyState.sending = sending || jobbyState.sending;
  const s = jobbyState.sending;
  if (!s) { el.textContent = ''; return; }
  if (s.allowed === false) {
    el.textContent = `Sending stopped — ${s.reason}`;
    el.dataset.kind = 'error';
  } else {
    el.textContent = tn('{used} of {cap} sends used in the last 24 hours')
    .replace('{used}', s.sent ?? 0).replace('{cap}', s.cap);
    el.dataset.kind = 'neutral';
  }
}

function renderJobbyTracks() {
  const host = jobbyEls['jobby-track-list'];
  if (!host) return;
  host.replaceChildren();
  TRACK_IDS.forEach(id => {
    const active = jobbyState.tracks.includes(id);
    // Track 5 has a third state. "Closed" and "closed, but this would suit you
    // and you have not said you want it" are different facts, and a candidate
    // reading their own plan needs to be able to tell them apart.
    const offered = id === 5 && !active && jobbyState.fifo && jobbyState.fifo.offeredByExperience;
    const row = jobbyEl('div', 'jobby-track'
      + (active ? ' is-active' : '')
      + (offered ? ' is-offered' : ''));
    row.appendChild(jobbyEl('span', 'jobby-track-dot'));

    const body = jobbyEl('div', 'jobby-track-body');
    body.appendChild(jobbyEl('p', 'jobby-track-name', `${id}. ${TRACK_NAMES[id]}`));
    body.appendChild(jobbyEl('p', 'jobby-track-state',
      active ? 'Active' : offered ? 'Available if you want it' : 'Closed'));

    // Why the track is in the state it is in. The relay already decided this
    // from the resume, so the page does not re-guess it.
    const reason = jobbyState.trackReasons && jobbyState.trackReasons[id];
    if (reason) {
      body.appendChild(jobbyEl('p', 'jobby-track-reason', reason));
    }
    if (offered && jobbyState.fifo.supporting && jobbyState.fifo.supporting.length) {
      body.appendChild(jobbyEl('p', 'jobby-track-reason',
        `Your background fits it: ${jobbyState.fifo.supporting.join('; ')}. `
        + 'Rotations are weeks away from home, so I will not switch it on without you saying so.'));
    }
    if (active && id === 5 && jobbyState.fifo && jobbyState.fifo.open && jobbyState.fifo.roster) {
      body.appendChild(jobbyEl('p', 'jobby-track-reason',
        `${jobbyState.fifo.roster.total} roles across `
        + `${(jobbyState.fifo.roster.sectors || []).length} sectors. `
        + `${jobbyState.fifo.roster.visaSponsoring} will consider a visa, `
        + `${jobbyState.fifo.roster.entryPossible} open without a ticket. `
        + `Only ${jobbyState.fifo.roster.directPostings} link straight to a posting — `
        + 'the rest need finding first. Pay is an estimate, not a quoted figure.'));
    }
    row.appendChild(body);
    host.appendChild(row);
  });
  // Same reason as in renderJobbyStatus: these rows are built after the page's
  // translation pass, so they need their own walk to match the stored language.
  if (window.JobbyI18n && typeof window.JobbyI18n.applyI18nTo === 'function') {
    window.JobbyI18n.applyI18nTo(host);
  }
}

function renderJobbyPlan() {
  const host = jobbyEls['jobby-plan'];
  if (!host) return;
  host.replaceChildren();
  const open = jobbyState.actions.filter(a => a.status !== 'done' && a.status !== 'skipped');
  if (!open.length) {
    host.appendChild(jobbyEl('p', 'jobby-muted', 'No plan yet — upload a resume.'));
    return;
  }
  open.slice(0, 12).forEach(a => {
    const row = jobbyEl('div', 'jobby-action');
    row.appendChild(jobbyEl('span', 'jobby-action-prio', 'P' + a.priority));
    const body = jobbyEl('div', 'jobby-action-body');
    body.appendChild(jobbyEl('p', 'jobby-action-title', a.title));
    if (a.detail) body.appendChild(jobbyEl('p', 'jobby-action-detail', a.detail));
    row.appendChild(body);
    host.appendChild(row);
  });
  if (open.length > 12) {
    host.appendChild(jobbyEl('p', 'jobby-muted', `+${open.length - 12} more`));
  }
}

async function loadJobbyHistory() {
  if (jobbyState.historyLoaded) return;
  try {
    const h = await jobbyApi('GET', '/api/jobby/history?limit=30');
    (h.messages || []).forEach(m => {
      if (m.role === 'user' || m.role === 'jobby') {
        addJobbyMessage(m.role, m.content, m.tool_calls);
      }
    });
    jobbyState.historyLoaded = true;
  } catch (e) {
    /* history is a nicety; a failure must not break the panel */
  }
}

async function loadJobbyEdits() {
  const host = jobbyEls['jobby-edits'];
  if (!host) return;
  try {
    const d = await jobbyApi('GET', '/api/jobby/dossier?limit=15');
    jobbyState.revision = d.revision || 0;
    host.replaceChildren();
    const edits = d.edits || [];
    if (!edits.length) {
      host.appendChild(jobbyEl('p', 'jobby-muted', 'Nothing changed yet.'));
      return;
    }
    edits.forEach(e => {
      const row = jobbyEl('div', 'jobby-edit');
      const verb = { set: 'set', add: 'added', update: 'changed', delete: 'removed' }[e.op] || e.op;
      row.appendChild(jobbyEl('span', 'jobby-edit-verb', verb));
      const body = jobbyEl('div', 'jobby-edit-body');
      body.appendChild(jobbyEl('p', 'jobby-edit-path', e.path));
      if (e.reason) body.appendChild(jobbyEl('p', 'jobby-edit-reason', e.reason));
      body.appendChild(jobbyEl('p', 'jobby-edit-meta',
        `${e.actor} · rev ${e.revision}${e.confirmed_by_user ? ' · you confirmed this' : ''}`));
      row.appendChild(body);
      host.appendChild(row);
    });
  } catch (e) {
    host.replaceChildren(jobbyEl('p', 'jobby-muted', 'Could not load the change log.'));
  }
}

async function sendJobbyMessage(text, files) {
  if (jobbyState.busy) return;
  const attached = Array.isArray(files) ? files : [];

  // The document goes first, so the words that follow describe what was just
  // read rather than arriving before it. The candidate watches the parse, and
  // then their own message lands in the transcript above a dossier that already
  // knows about the file they attached to it.
  if (attached.length) {
    setJobbyBusy(true);
    try {
      await ingestAttachments(attached);
    } finally {
      setJobbyBusy(false);
    }
    if (jobbyState.busy) return; // a parse left it busy; do not double-send
  }

  addJobbyMessage('user', text || (attached.length ? `Attached ${attached.map(f => f.name).join(', ')}` : ''));
  setJobbyBusy(true);
  setJobbyHint('Jobby is working…', 'working');
  try {
    const res = await jobbyApi('POST', '/api/jobby/chat', { message: text });
    addJobbyMessage('jobby', res.reply, res.toolCalls);
    // Read back only if the candidate asked for it, and never for an empty
    // reply — some turns are tool-only and saying nothing aloud is correct.
    if (res.reply) speakReply(res.reply);
    if (res.client) {
      jobbyState.tracks = res.client.tracks || jobbyState.tracks;
      renderJobbyTracks();
      renderJobbyCap(res.client.sending);
      if (jobbyEls['jobby-mission']) {
        jobbyEls['jobby-mission'].textContent =
          MISSION_LABELS[res.client.missionState] || res.client.missionState;
      }
      if (jobbyEls['jobby-kill-switch']) {
        jobbyEls['jobby-kill-switch'].checked = !!res.client.killSwitch;
      }
    }
    // Any turn can change the dossier or the plan, so refresh both.
    if (res.toolCalls && res.toolCalls.length) {
      await Promise.all([loadJobbyEdits(), loadJobbySessionQuiet()]);
    }
    setJobbyHint('Ask Jobby anything. Tell it facts about yourself and it will write them into your dossier.', 'neutral');
  } catch (e) {
    addJobbyMessage('jobby', `I could not reach the relay: ${e.message}`, null);
    setJobbyHint('That message did not send. Try again.', 'error');
  } finally {
    setJobbyBusy(false);
  }
}

async function loadJobbySessionQuiet() {
  try {
    const s = await jobbyApi('GET', '/api/jobby/session');
    jobbyState.actions = s.actions || [];
    renderJobbyPlan();
  } catch (e) { /* the plan is a nicety */ }
}

async function patchJobbyClient(patch) {
  try {
    const res = await jobbyApi('PATCH', '/api/jobby/client', patch);
    renderJobbyStatus({
      client: {
        missionState: res.client.mission_state,
        tracks: res.client.tracks,
        autonomy: res.client.autonomy,
        killSwitch: res.client.kill_switch,
      },
      sending: await jobbyApi('GET', '/api/jobby/outreach').then(o => o.sending).catch(() => null),
    });
    return true;
  } catch (e) {
    setJobbyHint('That setting did not save: ' + e.message, 'error');
    return false;
  }
}

// Repopulate the resume dossier from the server.
//
// The dossier panel was only ever filled as a side effect of an upload, so a
// refresh left it blank and read as though the record had been deleted. Nothing
// had been deleted: the dossier is in the database and GET /api/jobby/dossier
// returns it, it was simply never asked for on load. A candidate who refreshed
// the page lost the visible copy of their own profile and had to upload their
// resume again to see it, which is also how 23 duplicate client rows for one
// person accumulated.
function restoreDossierPanel() {
  const body = document.getElementById('dossier-body');
  const heading = document.getElementById('dossier-heading');
  if (!body || typeof renderDossier !== 'function') return;
  jobbyApi('GET', '/api/jobby/dossier')
    .then((d) => {
      if (!d || !d.dossier) return;
      renderDossier(d.dossier);
      if (heading) heading.textContent = 'Your dossier';
    })
    .catch(() => {
      // No dossier, or the relay is down. The upload panel is still there, and
      // a failed fetch is not worth an error banner over an empty page.
    });
}

// ── Attachments ────────────────────────────────────────────────────────────
//
// Files staged on the message, not sent with it. The browser's FormData already
// carries the text; adding files to the same request is what makes "attach a
// resume and say why" one action rather than two.
//
// Reuses the drop zone's parse path (POST /api/resume/parse) rather than adding
// an upload route of its own. A second document type is a second parser, and a
// second parser is a second set of ways to quietly return nothing from a scanned
// page. And the merge on the far side already augments the dossier instead of
// replacing it, reporting conflicts rather than resolving them.
const ATTACH_MAX_BYTES = 10 * 1024 * 1024;
const ATTACH_TYPES = new Set([
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'text/plain',
]);

let pendingAttachments = [];
let resizeInput = null;

function renderAttachments() {
  const row = document.getElementById('attach-row');
  const list = document.getElementById('attach-list');
  if (!row || !list) return;
  list.replaceChildren();
  for (const f of pendingAttachments) {
    const li = document.createElement('li');
    li.className = 'attach-chip';

    const name = document.createElement('span');
    name.className = 'attach-name';
    name.textContent = f.file.name;
    li.appendChild(name);

    const size = document.createElement('span');
    size.className = 'attach-size';
    size.textContent = Math.max(1, Math.round(f.file.size / 1024)) + ' KB';
    li.appendChild(size);

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'attach-remove';
    remove.setAttribute('aria-label', 'Remove ' + f.file.name);
    remove.textContent = '×';
    remove.addEventListener('click', () => {
      pendingAttachments = pendingAttachments.filter((x) => x !== f);
      renderAttachments();
    });
    li.appendChild(remove);
    list.appendChild(li);
  }
  row.hidden = pendingAttachments.length === 0;
}

function addAttachment(file) {
  const error = validateAttachment(file);
  if (error) {
    appendJobbyNote(error, 'error');
    return;
  }
  if (pendingAttachments.some((f) => f.file.name === file.name && f.file.size === file.size)) return;
  pendingAttachments.push({ file, id: 'att_' + Math.random().toString(36).slice(2) });
  renderAttachments();
}

function validateAttachment(file) {
  if (!file) return null;
  if (file.size > ATTACH_MAX_BYTES) return `${file.name} is larger than 10 MB.`;
  // An empty MIME type is a .txt or a file the browser cannot classify. Allowed,
  // because refusing it would block a plain text file on some platforms.
  if (file.type && !ATTACH_TYPES.has(file.type)) {
    return `${file.name} is not a PDF, DOCX or TXT file.`;
  }
  return null;
}

function takePendingAttachments() {
  const out = pendingAttachments.map((a) => a.file);
  pendingAttachments = [];
  renderAttachments();
  return out;
}

function initAttachments() {
  const input = document.getElementById('jobby-attach');
  if (!input) return;
  input.addEventListener('change', () => {
    for (const f of Array.from(input.files || [])) addAttachment(f);
    // Cleared so choosing the same file twice in a row still fires a change.
    input.value = '';
  });
  // Drag onto the chip row, which is where the pointer already is.
  const row = document.getElementById('attach-row');
  if (row) {
    const stop = (e) => { e.preventDefault(); e.stopPropagation(); };
    ['dragenter', 'dragover'].forEach((ev) => row.addEventListener(ev, (e) => {
      stop(e); row.dataset.dragging = 'true';
    }));
    ['dragleave', 'drop'].forEach((ev) => row.addEventListener(ev, (e) => {
      stop(e); delete row.dataset.dragging;
    }));
    row.addEventListener('drop', (e) => {
      for (const f of Array.from((e.dataTransfer && e.dataTransfer.files) || [])) addAttachment(f);
    });
  }
}

/**
 * Parse an attached document and fold it into the dossier.
 *
 * Sequential, not parallel. Each parse triggers a server-side dossier build that
 * runs the model several times; three at once on one relay is three builds
 * competing and three progress bars writing to the same panel.
 */
async function ingestAttachments(files) {
  for (const file of files) {
    appendJobbyNote(`Reading ${file.name}…`, 'working');
    try {
      const form = new FormData();
      form.append('lang', (typeof currentLang === 'function' ? currentLang() : 'en'));
      form.append('resume', file, file.name);
      form.append('format', (file.name.split('.').pop() || '').toLowerCase());
      const response = await fetch('/api/resume/parse', { method: 'POST', body: form });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || 'Could not read that file.');

      if (typeof renderParsedProfile === 'function') renderParsedProfile(result);

      const pending = result.dossier;
      if (pending && pending.request_id) {
        if (typeof showDossierPending === 'function') showDossierPending();
        if (typeof pollDossier === 'function') await pollDossier(pending.request_id);
      }
      appendJobbyNote(
        `Read ${file.name}. Anything in it that disagrees with what I already had is flagged, not overwritten.`,
        'success',
      );
    } catch (e) {
      appendJobbyNote(`${file.name}: ${e.message}`, 'error');
    }
  }
  // The panel and the agent's own view of the candidate are both now stale.
  if (typeof restoreDossierPanel === 'function') restoreDossierPanel();
  if (typeof jobbyRefreshAfterDossier === 'function' && window.JobbyI18n) {
    try { await jobbyRefreshAfterDossier(null); } catch (e) { /* not fatal */ }
  }
}

// ── Voice ───────────────────────────────────────────────────────────────────

/**
 * The read-aloud toggle.
 *
 * Added to the compose bar rather than the settings, because a candidate who has
 * just asked a question and wants the answer read back is not going to hunt for
 * a preference. Off until pressed, because a browser will not start audio without
 * a gesture and pretending otherwise gives a button that does nothing.
 */
function initVoiceToggle() {
  const tts = window.JobbyTTS;
  if (!tts) return;

  if (!tts.supported()) return; // No control at all rather than one that cannot work.

  const bar = document.querySelector('.compose-bar');
  if (!bar) return;

  const wanted = window.JobbyChat ? window.JobbyChat.restoreAudioPreference() : false;

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'voice-button';
  button.id = 'jobby-voice';
  button.setAttribute('aria-pressed', 'false');
  button.title = 'Read Jobby\'s replies aloud';
  button.textContent = '🔊';

  const setOn = (on) => {
    button.setAttribute('aria-pressed', on ? 'true' : 'false');
    button.classList.toggle('is-on', on);
    button.title = on ? 'Stop reading replies aloud' : 'Read Jobby\'s replies aloud';
  };

  button.addEventListener('click', async () => {
    if (tts.isEnabled()) {
      tts.disable();
      setOn(false);
      return;
    }
    const r = await tts.enable();
    if (r.ok) {
      setOn(true);
      // A candidate who has just turned it on wants to know it works, and the
      // only proof is a sound.
      tts.speak('Voice is on.');
    } else {
      button.disabled = true;
      button.title = 'This browser cannot read text aloud.';
    }
  });

  setOn(false);
  // A stored preference is not "on": the browser still needs this click, and the
  // button says so by being visibly off.
  if (wanted) button.classList.add('is-wanted');
  bar.appendChild(button);
}

/** Speak a reply, if the candidate asked for that. */
function speakReply(text) {
  const tts = window.JobbyTTS;
  if (!tts || !tts.isEnabled()) return;
  tts.speak(text, { lang: (typeof currentLang === 'function' ? currentLang() : 'en') });
}

/**
 * A line in the transcript that is neither the candidate nor Jobby: a file being
 * read, a merge that conflicted, a refusal.
 *
 * Added because attachment progress has to go somewhere the candidate can see,
 * and putting it in the chat as though Jobby said it would be a lie about who
 * said it. The existing `addJobbyMessage` takes a role, and a third role for
 * these is all this needs.
 */
function appendJobbyNote(text, kind) {
  const log = jobbyEls['jobby-log'];
  if (!log || !text) return;
  const empty = jobbyEls['jobby-empty'];
  if (empty) empty.remove();

  const wrap = jobbyEl('div', 'jobby-msg jobby-msg-note' + (kind ? ' jobby-msg-' + kind : ''));
  wrap.appendChild(jobbyEl('span', 'jobby-who', 'Note'));
  wrap.appendChild(jobbyEl('p', 'jobby-text', text));
  log.appendChild(wrap);
  log.scrollTop = log.scrollHeight;
}

/**
 * Put a line in the transcript from outside jobby.js.
 *
 * The widget needs to add Jobby's own introduction to the log, and the log is
 * built and owned here. Exposed rather than the widget reaching into `jobbyEls`,
 * because a widget that pokes at another module's element cache is one refactor
 * away from silently writing into a detached node — which is precisely how the
 * save confirmation on the mission card went missing earlier.
 *
 * `where` is 'top' or 'bottom'. The introduction has to go at the top: appended,
 * it lands under eight messages of history and reads as a reply to the last thing
 * the candidate said, which is the opposite of an introduction. That is not a
 * cosmetic preference — a greeting in the wrong position is a reply to something
 * that was never asked.
 */
function jobbyAddMessage(role, content, toolCalls, where) {
  if (where === 'top') {
    const log = jobbyEls['jobby-log'];
    const empty = jobbyEls['jobby-empty'];
    if (!log) return false;
    if (empty) empty.remove();
    const wrap = jobbyEl('div', 'jobby-msg jobby-msg-' + role + ' is-greeting');
    wrap.appendChild(jobbyEl('span', 'jobby-who', role === 'user' ? 'You' : 'Jobby'));
    wrap.appendChild(jobbyEl('p', 'jobby-text', content));
    log.insertBefore(wrap, log.firstChild);
    return true;
  }
  addJobbyMessage(role, content, toolCalls);
  return true;
}

function initJobby() {
  cacheJobbyEls();
  // The form now lives in the floating widget, which mounts on every candidate
  // page. This used to bail out when the form was missing, which was the right
  // guard when the chat was a section on the front page and nothing else had one —
  // and became the reason the dashboard had no way to talk to Jobby at all. The
  // guard is kept, but it now means "the widget did not mount", not "wrong page".
  if (!jobbyEls['jobby-form']) return;
  // Wired before the first session read, so the panel is live the moment the
  // status bar renders. Calling it after would leave a visible gap where the
  // buttons looked real and did nothing.
  wireJobbyVerify();

  // Repaint the resume dossier from the server on load.
  //
  // It used to appear only as a side effect of uploading a file, so a refresh
  // emptied the panel and looked exactly like the dossier had been deleted. It
  // had not: the record was in the database the whole time, and the agent panel
  // beside it reloaded correctly, which made the empty resume panel read as data
  // loss rather than as one missing fetch. renderDossier lives in app.js and
  // shares this page's scope, so it is called directly.
  //
  // Front page only. app.js is not loaded on the dashboard, so the call is a
  // no-op there at best; it used to be reached at all only because the chat was
  // never mounted on that page.
  if (typeof restoreDossierPanel === 'function' && document.getElementById('dossier-panel')) {
    restoreDossierPanel();
  }

  jobbyEls['jobby-form'].addEventListener('submit', async (event) => {
    event.preventDefault();
    const input = jobbyEls['jobby-input'];
    const text = (input.value || '').trim();
    // A message with a file attached is worth sending even with no words: the
    // document is the message. Requiring text would mean attaching a second
    // resume silently does nothing, which is the opposite of the point.
    const files = takePendingAttachments();
    if (!text && !files.length) return;
    input.value = '';
    if (typeof resizeInput === 'function') resizeInput();
    await sendJobbyMessage(text, files);
  });

  // Enter sends, Shift+Enter breaks the line, and neither fires mid-composition
  // on a non-Latin keyboard. Handled here rather than by the form's own submit
  // because a keydown is what can be intercepted; the form submit above still
  // catches the button and any assistive technology that fires it directly.
  if (window.JobbyChat) {
    resizeInput = window.JobbyChat.wireTextEntry(
      jobbyEls['jobby-input'],
      () => jobbyEls['jobby-form'].requestSubmit(),
    ) || null;
    // The widget restores a draft into the textarea when the panel opens, and the
    // textarea's height is set by the entry helper rather than by the browser. A
    // restored three-line draft in a one-line box reads as broken, so the helper is
    // published for the widget to re-run. Held here because this closure is the
    // only thing that has it.
    window.JobbyWidgetResize = resizeInput;
  }

  initAttachments();
  initVoiceToggle();

  if (jobbyEls['jobby-autonomy']) {
    jobbyEls['jobby-autonomy'].addEventListener('change', async (e) => {
      const ok = await patchJobbyClient({ autonomy: e.target.checked ? 'auto' : 'draft' });
      if (!ok) e.target.checked = !e.target.checked;
      else setJobbyHint(e.target.checked
        ? 'Jobby will send outreach on its own, within the daily cap. Everything it sends is logged.'
        : 'Draft mode. Jobby will prepare outreach and ask before anything goes out.', 'neutral');
    });
  }

  if (jobbyEls['jobby-kill-switch']) {
    jobbyEls['jobby-kill-switch'].addEventListener('change', async (e) => {
      const on = e.target.checked;
      if (on && !window.confirm('Stop all outreach immediately? Jobby will not send anything until you switch this back off.')) {
        e.target.checked = false;
        return;
      }
      const ok = await patchJobbyClient({ kill_switch: on });
      if (!ok) e.target.checked = !on;
      else setJobbyHint(on
        ? 'Stopped. Nothing will send until you turn this back off.'
        : 'Resumed. Jobby can send again.', on ? 'error' : 'neutral');
    });
  }

  loadJobbySession();
}

/* When a resume finishes parsing, the relay has already onboarded the client.
 * Refresh so the plan, tracks and change log appear without a page reload. */
function jobbyRefreshAfterDossier(profile) {
  if (!profile) return;
  jobbyState.historyLoaded = false;
  const onboarding = profile.onboarding;
  if (onboarding && onboarding.ok === false) {
    setJobbyHint('Your dossier is ready, but Jobby could not be reached: ' +
      (onboarding.error || 'unknown error') + '. The chat will pick up once the relay is back.', 'error');
    return;
  }
  const on = profile.onboarding;
  if (on && on.tracks) {
    jobbyState.tracks = on.tracks;
    renderJobbyTracks();
  }
  loadJobbySession().then(loadJobbyEdits);
}

/* ------------------------------------------------------------------ Google */

const googleEls = {};

function cacheGoogleEls() {
  ['google-hint', 'google-actions', 'google-detail', 'google-drive-btn',
    'google-replies-btn', 'google-disconnect'].forEach(id => {
    googleEls[id] = document.getElementById(id);
  });
}

function googlePanel(msg, kind) {
  const hint = googleEls['google-hint'];
  if (!hint) return;
  hint.textContent = msg;
  hint.dataset.kind = kind || 'neutral';
}

async function loadGoogleStatus() {
  cacheGoogleEls();
  if (!googleEls['google-hint']) return;
  googlePanel('Checking…');
  try {
    const s = await jobbyApi('GET', '/api/jobby/google/status');
    const actions = googleEls['google-actions'];

    if (!s.configured) {
      googlePanel('Google sign-in is not set up on this server yet.', 'error');
      if (actions) actions.hidden = true;
      return;
    }
    if (!s.encryption || !s.encryption.available) {
      googlePanel('Server is missing its token encryption key, so accounts cannot be stored.', 'error');
      if (actions) actions.hidden = true;
      return;
    }
    if (s.connection && s.connection.connected) {
      googlePanel('Connected as ' + s.connection.email, 'ok');
      applyGoogleControls(true);
      if (s.connection.lastError) {
        const detail = googleEls['google-detail'];
        if (detail) {
          detail.hidden = false;
          detail.textContent = 'Last error: ' + s.connection.lastError;
        }
      }
    } else {
      googlePanel('Connect a Google account so Jobby can send from your own address and read your Drive.', 'neutral');
      applyGoogleControls(false);
    }
  } catch (e) {
    googlePanel('Could not check Google: ' + e.message, 'error');
    if (googleEls['google-actions']) googleEls['google-actions'].hidden = true;
  }
}

async function connectGoogle() {
  try {
    googlePanel('Redirecting to Google…', 'working');
    const { url } = await jobbyApi('GET', '/api/jobby/google/auth-url');
    // Full navigation: Google is a consent screen, not a fetch.
    window.location.href = url;
  } catch (e) {
    const body = e.data || {};
    const detail = body.missing ? ' (' + body.missing.join(', ') + ')' : '';
    googlePanel('Could not start sign-in' + detail + ': ' + e.message, 'error');
  }
}

async function disconnectGoogle() {
  if (!window.confirm('Disconnect this Google account? Jobby will stop sending from your address and lose access to your Drive. Applications will go back through the relay sender.')) return;
  try {
    await jobbyApi('POST', '/api/jobby/google/disconnect', {});
    if (googleEls['google-detail']) {
      googleEls['google-detail'].hidden = true;
      googleEls['google-detail'].textContent = '';
    }
    await loadGoogleStatus();
  } catch (e) {
    googlePanel('Could not disconnect: ' + e.message, 'error');
  }
}

function googleDetail(title, lines) {
  const detail = googleEls['google-detail'];
  if (!detail) return;
  detail.replaceChildren();
  detail.hidden = false;
  detail.appendChild(jobbyEl('p', 'jobby-edit-path', title));
  const list = jobbyEl('div', 'google-list');
  lines.forEach(l => list.appendChild(jobbyEl('p', 'google-row', l)));
  detail.appendChild(list);
}

async function browseDrive() {
  googlePanel('Reading your Drive…', 'working');
  try {
    const { files } = await jobbyApi('GET', '/api/jobby/google/drive/files?limit=15');
    if (!files || !files.length) {
      googlePanel('No files found.', 'neutral');
      return;
    }
    googleDetail('Drive (most recently changed)', files.map(f =>
      `${f.name} — ${f.mimeType || 'file'}${f.webViewLink ? ' — ' + f.webViewLink : ''}`));
    googlePanel(`Showing ${files.length} file(s).`, 'ok');
  } catch (e) {
    const body = e.data || {};
    googlePanel(body.code === 'GOOGLE_NOT_CONNECTED'
      ? 'Connect a Google account first.'
      : 'Could not read Drive: ' + (body.detail || e.message), 'error');
  }
}

async function checkReplies() {
  googlePanel('Checking for replies…', 'working');
  try {
    const { messages } = await jobbyApi('GET', '/api/jobby/google/gmail/messages?limit=15');
    if (!messages || !messages.length) {
      googlePanel('No mail matched.', 'neutral');
      return;
    }
    googleDetail('Recent mail', messages.map(m =>
      `${m.subject || '(no subject)'} — from ${m.from || '?'}`));
    googlePanel(`${messages.length} message(s).`, 'ok');
  } catch (e) {
    const body = e.data || {};
    googlePanel(body.code === 'GOOGLE_NOT_CONNECTED'
      ? 'Connect a Google account first.'
      : 'Could not read mail: ' + (body.detail || e.message), 'error');
  }
}

function initGoogle() {
  cacheGoogleEls();
  if (!googleEls['google-hint']) return;

  // A connect/disconnect round trip comes back as a query flag on the portal.
  const params = new URLSearchParams(window.location.search);
  const googleResult = params.get('google');
  if (googleResult) {
    if (googleResult === 'connected') {
      googlePanel('Connected as ' + (params.get('email') || 'your account') + '.', 'ok');
    } else {
      googlePanel('Could not connect: ' + (params.get('reason') || 'unknown') +
        (params.get('detail') ? ' — ' + params.get('detail') : ''), 'error');
    }
    // Clean the URL so a refresh does not replay the message.
    const clean = new URL(window.location.href);
    ['google', 'email', 'reason', 'detail'].forEach(k => clean.searchParams.delete(k));
    window.history.replaceState({}, '', clean.toString());
  }

  if (googleEls['google-drive-btn']) googleEls['google-drive-btn'].addEventListener('click', browseDrive);
  if (googleEls['google-replies-btn']) googleEls['google-replies-btn'].addEventListener('click', checkReplies);
  if (googleEls['google-disconnect']) googleEls['google-disconnect'].addEventListener('click', disconnectGoogle);

  if (!googleResult) loadGoogleStatus();
}

/**
 * Show the right buttons for the current state: a single Connect button when
 * nothing is linked, or Drive / replies / disconnect once it is.
 */
function applyGoogleControls(connected) {
  const actions = googleEls['google-actions'];
  if (!actions) return;
  actions.hidden = false;
  const existing = document.getElementById('google-connect');
  if (connected) {
    if (existing) existing.remove();
  } else if (!existing) {
    const btn = jobbyEl('button', 'google-btn google-btn-primary', 'Connect Google account');
    btn.id = 'google-connect';
    btn.type = 'button';
    btn.addEventListener('click', connectGoogle);
    actions.insertBefore(btn, actions.firstChild);
  }
  if (googleEls['google-drive-btn']) googleEls['google-drive-btn'].hidden = !connected;
  if (googleEls['google-replies-btn']) googleEls['google-replies-btn'].hidden = !connected;
  if (googleEls['google-disconnect']) googleEls['google-disconnect'].hidden = !connected;
}

// Loaded with `defer`, so the document is parsed by the time this runs and
// app.js (which loads first) has already bound the upload handlers.

  // The widget owns the panel but not the transcript: it needs to put Jobby's own
  // introduction into the log, and the log is built here. Published rather than
  // reached into, because a widget that writes to another module's element cache is
  // one refactor away from appending to a detached node - which is exactly how the
  // mission card's save confirmation went missing earlier in this session.
  window.jobbyAddMessage = jobbyAddMessage;

  // So the widget can tell "audio is wanted" from "audio is wanted and the browser
  // has actually allowed it to speak". Those are different states and it draws a
  // line between them, rather than showing a toggle that is on and a page that is
  // silent.
  if (window.JobbyTTS && typeof window.JobbyTTS.onState === 'function') {
    window.JobbyTTS.onState(function (st) { window.JobbyAudioWanted = !!st.enabled; });
  }
initJobby();
initGoogle();