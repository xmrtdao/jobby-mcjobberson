/**
 * employer.js — the employer page
 *
 * Three jobs, in the order a person does them: read their description, see what
 * was and was not read, then talk it through.
 *
 * ── Two rules this file follows everywhere ────────────────────────────────
 *
 * 1. **Never render the model's claim as a fact.** When the chat returns, the
 *    postings list on screen is rebuilt from the server response, not from
 *    anything the assistant said. If Jobby says "I've published your posting" and
 *    the row is still a draft, the page says it is a draft.
 *
 * 2. **Never show a green tick for a posting that has a problem.** The publish
 *    button is disabled with the reasons shown above it, not enabled and left to
 *    fail. A button that lets you press it and get a refusal is a worse version of
 *    one that tells you why.
 */

const JD_MAX_BYTES = 5 * 1024 * 1024;
const JD_TYPES = new Set([
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'text/plain',
]);

const el = (id) => document.getElementById(id);
const tn = (s) => (window.JobbyI18n ? window.JobbyI18n.tn(s) : s);

/** State the whole page renders from. The server is the only writer. */
const state = {
  employer: null,
  stats: null,
  postings: [],
  /** The posting currently being reviewed after a parse. */
  focusId: null,
  lastParse: null,
  busy: false,
};

// ── small DOM helpers ───────────────────────────────────────────────────────

function node(tag, className, text) {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}

function setStatus(message, kind) {
  const s = el('jd-status');
  if (!s) return;
  s.textContent = message || '';
  s.dataset.kind = kind || 'neutral';
}

function clear(node_) {
  while (node_ && node_.firstChild) node_.removeChild(node_.firstChild);
}

// ── the drop zone ───────────────────────────────────────────────────────────

function initDropZone() {
  const area = el('jd-drop-area');
  const input = el('jd-file');
  if (!area || !input) return;

  const onPick = (file) => { if (file) readJobDescription(file); };

  input.addEventListener('change', () => onPick(input.files && input.files[0]));

  area.addEventListener('click', (e) => {
    // A click that lands on the input is the input's own work.
    if (e.target === input) return;
    input.click();
  });
  area.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
  });

  const stop = (e) => { e.preventDefault(); e.stopPropagation(); };
  ['dragenter', 'dragover'].forEach((ev) => area.addEventListener(ev, (e) => {
    stop(e);
    area.dataset.dragging = 'true';
  }));
  ['dragleave', 'drop'].forEach((ev) => area.addEventListener(ev, (e) => {
    stop(e);
    delete area.dataset.dragging;
  }));
  area.addEventListener('drop', (e) => {
    const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    onPick(file);
  });
}

function validateJdFile(file) {
  if (!file) return 'Choose a PDF, DOCX or TXT job description.';
  if (file.size > JD_MAX_BYTES) return 'That file is larger than 5 MB.';
  if (file.type && !JD_TYPES.has(file.type)) {
    return 'Use a PDF, DOCX or TXT file. A Word document or plain text is fine.';
  }
  return null;
}

// ── reading a description ───────────────────────────────────────────────────

async function readJobDescription(file) {
  const problem = validateJdFile(file);
  if (problem) { setStatus(problem, 'error'); return; }

  setStatus('Reading ' + file.name + '…', 'working');
  try {
    const form = new FormData();
    form.append('jd', file, file.name);
    form.append('format', (file.name.split('.').pop() || '').toLowerCase());
    const response = await fetch('/api/employer/jd/parse', { method: 'POST', body: form });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || 'Could not read that file.');

    // The parsed text goes into the textarea rather than being discarded. The
    // employer can see exactly what was read, correct it, and re-read — which
    // is the whole loop the page exists for.
    const box = el('jd-text');
    if (box) box.value = result.parse && result.parse.sourceText
      ? result.parse.sourceText
      : box.value;

    state.lastParse = result;
    state.focusId = result.posting ? result.posting.id : null;
    renderReview(result);
    setStatus('Read. Check what it could and could not work out below.', 'success');
    await refreshAll();
  } catch (error) {
    setStatus(error.message, 'error');
  }
}

async function parsePastedText() {
  const box = el('jd-text');
  const text = box && box.value.trim();
  if (!text) { setStatus('Paste the job description first.', 'error'); return; }

  setStatus('Reading it…', 'working');
  try {
    const response = await fetch('/api/employer/parse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || 'Could not read that description.');

    state.lastParse = result;
    state.focusId = result.posting ? result.posting.id : null;
    renderReview(result);
    setStatus('Read. Check what it could and could not work out below.', 'success');
    await refreshAll();
  } catch (error) {
    setStatus(error.message, 'error');
  }
}

// ── the review panel ────────────────────────────────────────────────────────

/**
 * Render the parse.
 *
 * The review queue is the loudest thing on the page when it is non-empty, and
 * near-invisible when it is empty. That asymmetry is deliberate: an employer who
 * has fixed everything should be able to publish without being scolded, and one
 * who has not should not be able to miss it.
 */
function renderReview(result) {
  const host = el('jd-review-body');
  const section = el('jd-review');
  if (!host) return;
  clear(host);
  if (!section) return;

  const parse = result.parse || {};
  const posting = result.posting || {};
  const notes = result.reviewNotes || [];

  section.hidden = false;

  // ── what it read ──
  const read = node('div', 'jd-read');
  read.appendChild(node('h3', 'jd-subhead', 'What it read'));

  const grid = node('dl', 'jd-fields');
  const addField = (label, value, note) => {
    grid.appendChild(node('dt', null, label));
    const dd = node('dd');
    if (value) {
      dd.appendChild(node('span', 'jd-value', value));
    } else {
      // A blank is shown as blank, labelled. Not rendered as absent — a missing
      // field that looks like a rendering bug is indistinguishable from one.
      dd.appendChild(node('span', 'jd-value jd-value-missing', 'not stated'));
    }
    if (note) dd.appendChild(node('span', 'jd-value-note', note));
    grid.appendChild(dd);
  };

  addField('Title', posting.title,
    posting.titleRecognised === false ? 'Jobby does not recognise this title, so few candidates will find it.' : null);
  addField('Location', posting.location,
    posting.locationSpecificity && posting.locationSpecificity !== 'city_and_region' && posting.location
      ? 'Too broad to filter on.' : null);

  const pay = posting.pay || {};
  addField('Pay',
    pay.stated
      ? `${formatMoney(pay.min)}${pay.max ? ' – ' + formatMoney(pay.max) : ''} per ${pay.basis || 'year'}`
      : 'not stated',
    pay.stated ? null : (pay.note || 'Candidates filter on pay.'));

  const reqs = (parse.requirements || []);
  addField('Requirements', reqs.length ? String(reqs.length) : null,
    reqs.length ? reqs.map((r) => r.strength).filter((v, i, a) => a.indexOf(v) === i).join(', ') : null);

  // `grid` is appended here rather than beside its construction. It was built,
  // filled with four fields, and then never attached to the DOM — so the review
  // panel showed the requirements and the tickets and no title, no location and
  // no pay at all. The three fields an employer most needs to check are the ones
  // the parse works hardest to get right, and none of them were on screen.
  if (grid.childNodes.length) read.appendChild(grid);

  const reqList = node('ul', 'jd-req-list');
  for (const r of reqs) {
    const li = node('li', 'jd-req jd-req-' + (r.strength || 'unstated'));
    li.appendChild(node('span', 'jd-req-strength', r.strength || 'unstated'));
    li.appendChild(node('span', 'jd-req-text', r.text));
    reqList.appendChild(li);
  }
  if (reqs.length) read.appendChild(reqList);

  const tickets = node('ul', 'jd-ticket-list');
  for (const t of posting.requiredTickets || []) {
    tickets.appendChild(node('li', 'jd-ticket jd-ticket-required', t + ' — required'));
  }
  for (const t of posting.preferredTickets || []) {
    tickets.appendChild(node('li', 'jd-ticket jd-ticket-preferred', t + ' — preferred'));
  }
  for (const t of posting.unstatedTickets || []) {
    const li = node('li', 'jd-ticket jd-ticket-unstated', t + ' — the posting does not say if this is required');
    tickets.appendChild(li);
  }
  if (tickets.childNodes.length) {
    read.appendChild(node('h4', 'jd-subhead-sm', 'Tickets it mentions'));
    read.appendChild(tickets);
  }

  host.appendChild(read);

  // ── what it could not ──
  if (notes.length) {
    const problems = node('div', 'jd-problems');
    problems.appendChild(node('h3', 'jd-subhead', 'Fix before this goes on the board'));
    const list = node('ul', 'jd-problem-list');
    for (const n of notes) {
      const li = node('li', 'jd-problem');
      li.appendChild(node('span', 'jd-problem-text', n.detail || n.fix || String(n)));
      list.appendChild(li);
    }
    problems.appendChild(list);
    problems.appendChild(node('p', 'jd-problem-note',
      'These are the things a candidate would trip over. Fix them and read it again.'));
    host.appendChild(problems);
  } else {
    const clear_ = node('div', 'jd-allclear');
    clear_.appendChild(node('h3', 'jd-subhead', 'Nothing outstanding'));
    clear_.appendChild(node('p', null,
      'Everything a candidate needs is in there. Check it says what you mean, then publish.'));
    host.appendChild(clear_);
  }

  // ── the two things publication needs and the parse cannot see ──
  const route = node('div', 'jd-route');
  route.appendChild(node('h3', 'jd-subhead', 'Where candidates apply'));
  const row = node('div', 'jd-route-row');
  const urlLabel = node('label', 'field-label', 'Application link');
  const urlInput = node('input');
  urlInput.type = 'url';
  urlInput.id = 'jd-apply-url';
  urlInput.placeholder = 'https://yourats.com/apply/1234';
  urlInput.value = (result.posting && result.posting.applyUrl) || '';
  const mailLabel = node('label', 'field-label', 'Or an email');
  const mailInput = node('input');
  mailInput.type = 'email';
  mailInput.id = 'jd-contact-email';
  mailInput.placeholder = 'hiring@yourcompany.com';
  mailInput.value = (result.posting && result.posting.contactEmail) || '';
  row.appendChild(urlLabel); row.appendChild(urlInput);
  row.appendChild(mailLabel); row.appendChild(mailInput);
  route.appendChild(row);
  const saveRoute = node('button', 'button button-small', 'Save where to apply');
  saveRoute.type = 'button';
  saveRoute.addEventListener('click', () => saveApplyRoute(result.posting && result.posting.id));
  route.appendChild(saveRoute);
  host.appendChild(route);
}

function formatMoney(n) {
  if (n === null || n === undefined) return '';
  const v = Number(n);
  if (!Number.isFinite(v)) return '';
  return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

async function saveApplyRoute(postingId) {
  if (!postingId) return;
  const url = (el('jd-apply-url') || {}).value || null;
  const email = (el('jd-contact-email') || {}).value || null;
  try {
    const response = await fetch('/api/employer/postings/' + postingId, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apply_url: url, contact_email: email }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || 'Could not save that.');
    await refreshAll();
    if (result.summary) {
      setStatus(result.canPublish
        ? 'Saved. This one is ready to publish.'
        : 'Saved. Still to fix: ' + result.summary, result.canPublish ? 'success' : 'error');
    }
  } catch (error) {
    setStatus(error.message, 'error');
  }
}

// ── stats, postings, board ──────────────────────────────────────────────────

function renderStats() {
  const host = el('employer-stats-row');
  if (!host) return;
  clear(host);
  const s = state.stats || {};

  const cells = [
    { label: 'Live', value: s.published ?? 0, note: 'on the board now' },
    { label: 'Drafts', value: s.drafts ?? 0, note: 'not visible to anyone' },
    { label: 'To fix', value: s.needs_review ?? 0, note: 'cannot be published yet' },
    { label: 'Views', value: s.views ?? 0, note: 'across live postings' },
    { label: 'Applicants', value: s.applications ?? 0, note: 'recorded so far' },
  ];

  for (const c of cells) {
    const box = node('div', 'stat-cell');
    box.appendChild(node('span', 'stat-value', c.value));
    box.appendChild(node('span', 'stat-label', c.label));
    box.appendChild(node('span', 'stat-note', c.note));
    host.appendChild(box);
  }

  if (state.employer && !state.employer.verified) {
    const warn = node('p', 'verify-note');
    warn.appendChild(node('strong', null, 'Your postings show as unverified. '));
    warn.appendChild(document.createTextNode(
      'That label is on them until someone at Jobby confirms the company exists. It is not something you can set yourself.'));
    host.appendChild(warn);
  }
}

function renderPostings() {
  const host = el('employer-postings-body');
  if (!host) return;
  clear(host);

  const list = state.postings || [];
  if (!list.length) {
    host.appendChild(node('p', 'empty-note',
      'Nothing yet. Drop a description above, or tell the assistant what the role is.'));
    return;
  }

  const wrap = node('div', 'posting-list');
  for (const p of list) {
    const card = node('article', 'posting-card posting-' + (p.status || 'draft'));
    if (p.id === state.focusId) card.dataset.focus = 'true';

    const head = node('div', 'posting-head');
    head.appendChild(node('h3', 'posting-title', p.title || 'Untitled posting'));
    const badge = node('span', 'posting-badge posting-badge-' + (p.status || 'draft'),
      p.status === 'published' ? 'Live' : (p.status || 'draft'));
    head.appendChild(badge);
    card.appendChild(head);

    const meta = node('p', 'posting-meta');
    const bits = [];
    bits.push(p.location || 'no location');
    bits.push(p.payStated
      ? `${formatMoney(p.payMin)}${p.payMax ? '–' + formatMoney(p.payMax) : ''} per ${p.payBasis || 'year'}`
      : 'pay not stated');
    if (p.arrangement && p.arrangement.length) bits.push(p.arrangement.join(', '));
    meta.textContent = bits.join(' · ');
    card.appendChild(meta);

    if (p.status === 'published') {
      const reach = node('p', 'posting-reach');
      reach.textContent = `${p.views || 0} view${p.views === 1 ? '' : 's'} · `
        + `${p.applications || 0} applicant${p.applications === 1 ? '' : 's'}`;
      card.appendChild(reach);
    }

    // The review queue, on the card. An employer should not have to click into a
    // posting to find out it cannot be published.
    const notes = Array.isArray(p.reviewNotes) ? p.reviewNotes : [];
    if (p.status !== 'published' && notes.length) {
      const list2 = node('ul', 'posting-notes');
      for (const n of notes.slice(0, 4)) {
        list2.appendChild(node('li', null, n.detail || n.fix || String(n)));
      }
      if (notes.length > 4) {
        list2.appendChild(node('li', 'posting-notes-more', `+${notes.length - 4} more`));
      }
      card.appendChild(list2);
    }

    const actions = node('div', 'posting-actions');
    if (p.status === 'published') {
      const close = node('button', 'button button-small', 'Take it down');
      close.type = 'button';
      close.addEventListener('click', () => closePosting(p.id));
      actions.appendChild(close);
    } else {
      const pub = node('button', 'button button-small', 'Publish');
      pub.type = 'button';
      // Disabled with the reason attached, rather than enabled and left to fail.
      if (p.needsReview || notes.length || !p.applyUrl && !p.contactEmail) {
        pub.disabled = true;
        pub.title = 'Fix what is listed on this card first.';
      }
      pub.addEventListener('click', () => publishPosting(p.id, pub));
      actions.appendChild(pub);
    }
    card.appendChild(actions);
    wrap.appendChild(card);
  }
  host.appendChild(wrap);
}

async function publishPosting(id, button) {
  if (state.busy) return;
  state.busy = true;
  if (button) { button.disabled = true; button.textContent = 'Publishing…'; }
  try {
    const response = await fetch('/api/employer/postings/' + id + '/publish', { method: 'POST' });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      // Say what came back. The refusal is the useful part.
      setStatus(result.summary || 'It could not be published.', 'error');
      if (button) { button.disabled = false; button.textContent = 'Publish'; }
    } else {
      setStatus('Live. Candidates can see it now.', 'success');
    }
    // Whatever happened, rebuild from the server.
    await refreshAll();
  } catch (error) {
    setStatus(error.message, 'error');
    if (button) { button.disabled = false; button.textContent = 'Publish'; }
  } finally {
    state.busy = false;
  }
}

async function closePosting(id) {
  try {
    const response = await fetch('/api/employer/postings/' + id + '/close', { method: 'POST' });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || 'Could not take it down.');
    setStatus('Taken down. The record is kept.', 'success');
    await refreshAll();
  } catch (error) {
    setStatus(error.message, 'error');
  }
}

async function renderBoard() {
  const host = el('board-body');
  if (!host) return;
  const q = (el('board-q') || {}).value || '';
  const ticket = (el('board-ticket') || {}).value || '';
  const remote = (el('board-remote') || {}).checked ? '1' : '';

  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (ticket) params.set('ticket', ticket);
  if (remote) params.set('remote', remote);

  try {
    const response = await fetch('/api/employer/jobs?' + params.toString());
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || 'Could not load the board.');
    clear(host);

    if (!result.jobs.length) {
      host.appendChild(node('p', 'empty-note',
        ticket || q ? 'Nothing matches that filter.' : 'The board is empty. Yours would be the first.'));
      return;
    }
    host.appendChild(node('p', 'board-count',
      `${result.total} posting${result.total === 1 ? '' : 's'}`));

    const list = node('div', 'board-list');
    for (const j of result.jobs) {
      const card = node('article', 'board-card');
      const h = node('h3', 'board-title');
      h.appendChild(document.createTextNode(j.title || 'Untitled'));
      if (!j.verified) {
        h.appendChild(node('span', 'board-unverified', 'unverified employer'));
      }
      card.appendChild(h);
      card.appendChild(node('p', 'board-meta',
        [j.company, j.location, (j.arrangement || []).join(', ')].filter(Boolean).join(' · ')));
      const pay = j.pay || {};
      card.appendChild(node('p', 'board-pay' + (pay.stated ? '' : ' board-pay-missing'),
        pay.stated
          ? `${formatMoney(pay.min)}${pay.max ? ' – ' + formatMoney(pay.max) : ''} per ${pay.basis || 'year'}`
          : 'Pay not stated'));
      if ((j.tickets || []).length) {
        const t = node('ul', 'board-tickets');
        for (const ticketName of j.tickets) t.appendChild(node('li', null, ticketName));
        card.appendChild(t);
      }
      list.appendChild(card);
    }
    host.appendChild(list);
  } catch (error) {
    clear(host);
    host.appendChild(node('p', 'empty-note', error.message));
  }
}

async function refreshAll() {
  try {
    const response = await fetch('/api/employer/session');
    if (response.status === 404) {
      // No employer session yet. The page still works — the first parse or chat
      // message creates one — so this is not an error state, it is an empty one.
      state.employer = null;
      state.stats = null;
      state.postings = [];
      renderStats();
      renderPostings();
      return;
    }
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || 'Could not load your account.');
    state.employer = result.employer;
    state.stats = result.stats;
    state.postings = result.postings || [];
    renderStats();
    renderPostings();
  } catch (error) {
    const host = el('employer-stats-row');
    if (host) {
      clear(host);
      host.appendChild(node('p', 'empty-note',
        'Could not reach your account: ' + error.message));
    }
  }
}

// ── the conversation ────────────────────────────────────────────────────────

function appendEmployerMessage(who, text, extra) {
  const log = el('employer-log');
  if (!log) return;
  const emptyEl = el('employer-empty');
  if (emptyEl) emptyEl.remove();

  const row = node('div', 'chat-row chat-row-' + who);
  row.appendChild(node('span', 'chat-who', who === 'you' ? 'You' : 'Jobby'));
  row.appendChild(node('div', 'chat-text', text));
  if (extra) row.appendChild(node('p', 'chat-extra', extra));
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
}

function setHint(message, kind) {
  const h = el('employer-hint');
  if (!h) return;
  h.textContent = message || '';
  h.dataset.kind = kind || 'neutral';
}

async function sendEmployerMessage(text) {
  if (!text || !text.trim()) return;
  appendEmployerMessage('you', text.trim());
  setHint('Thinking…', 'working');

  try {
    const response = await fetch('/api/employer/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text.trim(),
        posting_id: state.focusId,
        company: state.employer ? state.employer.company : null,
      }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || 'The assistant is not reachable.');

    appendEmployerMessage('jobby', result.reply || '');

    if (result.providerError) {
      setHint('The model was not reachable, so nothing was changed.', 'error');
    } else {
      // What the tools actually did, in the employer's terms.
      const done = (result.toolCalls || [])
        .filter((c) => c.ok || c.saved || c.updated || c.published)
        .map((c) => c.tool.replace(/^employer_/, '').replace(/_/g, ' '));
      if (done.length) {
        setHint('Just did: ' + done.join(', ') + '. Check it below.', 'success');
      } else {
        setHint('', 'neutral');
      }
    }

    // The list is rebuilt from the response, never from the reply's claims.
    if (result.postings) {
      const stats = await refreshFromPostings(result.postings, result.stats);
      renderStats();
      renderPostings();
      void stats;
    } else {
      await refreshAll();
    }
  } catch (error) {
    setHint(error.message, 'error');
  }
}

async function refreshFromPostings(postings, stats) {
  state.postings = postings;
  if (stats) state.stats = stats;
  // Keep the full record so the cards can show review notes and apply routes.
  try {
    const response = await fetch('/api/employer/postings');
    const result = await response.json().catch(() => ({}));
    if (response.ok) {
      state.postings = result.postings || postings;
      state.stats = result.stats || stats;
    }
  } catch { /* the chat response is enough to render */ }
}

function initChat() {
  const form = el('employer-form');
  const input = el('employer-input');
  const send = el('employer-send');
  if (!form || !input) return;

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = input.value;
    input.value = '';
    sendEmployerMessage(text);
  });
  if (send) {
    send.addEventListener('click', (e) => {
      e.preventDefault();
      const text = input.value;
      input.value = '';
      sendEmployerMessage(text);
    });
  }
  // Enter sends, Shift+Enter breaks the line. A textarea that needs a button
  // press for every follow-up is a textarea people stop using.
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      form.dispatchEvent(new Event('submit'));
    }
  });
}

// ── boot ────────────────────────────────────────────────────────────────────

function init() {
  initDropZone();
  initChat();

  const parseBtn = el('jd-parse');
  if (parseBtn) parseBtn.addEventListener('click', parsePastedText);

  for (const id of ['board-q', 'board-ticket', 'board-remote']) {
    const control = el(id);
    if (!control) continue;
    control.addEventListener('change', renderBoard);
    if (control.tagName === 'INPUT' && control.type === 'search') {
      control.addEventListener('input', renderBoard);
    }
  }

  refreshAll();
  renderBoard();
  setHint('Drop a description, paste one, or just tell me the role.', 'neutral');
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
