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
    'jobby-edits'];
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
};

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
    jobbyState.actions = s.actions ?? [];
    jobbyState.sending = s.sending ?? null;
    renderJobbyStatus(s);
    renderJobbyTracks();
    renderJobbyPlan();
    if (s.hasDossier) {
      setJobbyHint('Ask Jobby anything. Tell it facts about yourself and it will write them into your dossier.', 'neutral');
      await loadJobbyHistory();
    } else {
      setJobbyHint('Upload a resume and Jobby builds your dossier, picks your tracks, and starts the plan.', 'neutral');
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
    const active = (c.tracks || []).map(t => TRACK_NAMES[t] || ('Track ' + t));
    jobbyEls['jobby-tracks'].textContent = active.length
      ? tn('{n} of {total} tracks active').replace('{n}', active.length).replace('{total}', 4)
      : tn('No tracks active');
  }
  if (jobbyEls['jobby-autonomy']) jobbyEls['jobby-autonomy'].checked = c.autonomy === 'auto';
  if (jobbyEls['jobby-kill-switch']) jobbyEls['jobby-kill-switch'].checked = !!c.killSwitch;
  renderJobbyCap(s.sending);
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
  [1, 2, 3, 4].forEach(id => {
    const active = jobbyState.tracks.includes(id);
    const row = jobbyEl('div', 'jobby-track' + (active ? ' is-active' : ''));
    row.appendChild(jobbyEl('span', 'jobby-track-dot'));
    const body = jobbyEl('div', 'jobby-track-body');
    body.appendChild(jobbyEl('p', 'jobby-track-name', `${id}. ${TRACK_NAMES[id]}`));
    body.appendChild(jobbyEl('p', 'jobby-track-state', active ? 'Active' : 'Closed'));
    row.appendChild(body);
    host.appendChild(row);
  });
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

async function sendJobbyMessage(text) {
  if (jobbyState.busy) return;
  addJobbyMessage('user', text);
  setJobbyBusy(true);
  setJobbyHint('Jobby is working…', 'working');
  try {
    const res = await jobbyApi('POST', '/api/jobby/chat', { message: text });
    addJobbyMessage('jobby', res.reply, res.toolCalls);
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

function initJobby() {
  cacheJobbyEls();
  if (!jobbyEls['jobby-form']) return;

  // Repaint the resume dossier from the server on load.
  //
  // It used to appear only as a side effect of uploading a file, so a refresh
  // emptied the panel and looked exactly like the dossier had been deleted. It
  // had not: the record was in the database the whole time, and the agent panel
  // beside it reloaded correctly, which made the empty resume panel read as data
  // loss rather than as one missing fetch. renderDossier lives in app.js and
  // shares this page's scope, so it is called directly.
  restoreDossierPanel();

  jobbyEls['jobby-form'].addEventListener('submit', async (event) => {
    event.preventDefault();
    const input = jobbyEls['jobby-input'];
    const text = (input.value || '').trim();
    if (!text) return;
    input.value = '';
    await sendJobbyMessage(text);
  });

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
initJobby();
initGoogle();