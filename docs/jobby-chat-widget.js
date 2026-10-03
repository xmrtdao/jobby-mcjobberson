/**
 * The conversation with Jobby, as a floating panel that follows you round the site.
 *
 * Why it moved
 * ------------
 * The chat was a section halfway down the front page. Everything else — the drop
 * zone, the dossier, the plan, the change log — is a page you read once. The
 * conversation is not: it is the thing a candidate comes back to all day, and
 * every question they wanted to ask it required scrolling past four sections and
 * then navigating back to find the answer to the last one. The dashboard, which
 * is where you go *because* Jobby did something, had no way to talk to it at all.
 *
 * So the chat is now a widget, and the pages are pages.
 *
 * What this file is responsible for
 * ---------------------------------
 * The shell only: the launcher, the panel, the open/close behaviour, the unread
 * badge, and remembering a half-typed message across a navigation. It builds its
 * own DOM rather than being pasted into three HTML files, so a new page gets the
 * conversation by adding one script tag and cannot get a stale copy of the markup.
 *
 * What it is deliberately not responsible for
 * --------------------------------------------
 * Sending, rendering messages, the transcript, attachments, text entry, voice.
 * All of that stays in jobby.js and chat-experience.js, unchanged. This file wires
 * a container around work that already existed, which is why the ids inside it are
 * exactly the ids jobby.js already looks for: `jobby-log`, `jobby-form`,
 * `jobby-input`, `jobby-send`, `jobby-hint`, and the attachment row. Nothing
 * downstream had to be taught a new name.
 *
 * Ordering
 * --------
 * Both scripts are `defer`, which means they run in document order, so this must
 * be listed before jobby.js. jobby.js caches its elements once on init and wires
 * listeners to them; if this mounted afterwards, every listener would be attached
 * to a detached form and the widget would look perfect and send nothing.
 */
(function () {
  'use strict';

  // Where the conversation begins rather than a page it lives on. The front page
  // opens the panel, because arriving there and being met by a closed box in the
  // corner is a worse first meeting than a conversation already in progress.
  var OPENS_ON_ARRIVAL = /(index\.html|\/)$/;

  var DRAFT_KEY = 'jobby-chat-draft';
  var SEEN_KEY = 'jobby-chat-last-seen';
  // One small request a minute, and only while the panel is shut and the tab is
  // actually being looked at. Not a websocket: the relay has no push channel, and
  // adding one to deliver a badge would be a poor trade. Stated plainly so nobody
  // later assumes the badge is instant.
  var BADGE_POLL_MS = 60000;

  var mounted = false;
  var els = {};
  var lastSeenAt = null;
  var pollTimer = null;

  function el(tag, className, text) {
    var n = document.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }

  // ── the DOM ──────────────────────────────────────────────────────────────
  //
  // The ids and classes inside `.jobby-chat` are the ones jobby.js, app.js and
  // styles.css already use. Copied deliberately rather than renamed: renaming them
  // would mean teaching three files a vocabulary they do not have, for no gain.

  function buildChat() {
    var chat = el('div', 'jobby-chat');

    var log = el('div', 'jobby-log');
    log.id = 'jobby-log';
    log.setAttribute('role', 'log');
    log.setAttribute('aria-live', 'polite');
    log.setAttribute('aria-label', 'Conversation with Jobby');
    var empty = el('p', 'jobby-empty');
    empty.id = 'jobby-empty';
    empty.textContent = 'No resume? Good — start here. Tell me what you have done and I will '
      + 'write it down as we go, then turn it into a resume you can send. I will not invent '
      + 'anything you have not said.';
    log.appendChild(empty);
    chat.appendChild(log);

    var form = el('form', 'jobby-compose');
    form.id = 'jobby-form';

    // The same comment as the markup this replaces, because the reasoning is the
    // part worth keeping: people hold more than one resume, aimed at different
    // work, and the natural moment to offer the second is mid-conversation. A
    // separate "upload again" control elsewhere is a second thing to remember.
    var attachRow = el('div', 'attach-row');
    attachRow.id = 'attach-row';
    attachRow.hidden = true;
    var attachList = el('ul', 'attach-list');
    attachList.id = 'attach-list';
    attachList.setAttribute('aria-label', 'Files to send with this message');
    attachRow.appendChild(attachList);
    form.appendChild(attachRow);

    var bar = el('div', 'compose-bar');
    var attachLabel = el('label', 'attach-button');
    attachLabel.setAttribute('for', 'jobby-attach');
    attachLabel.setAttribute('title', 'Attach a document');
    var srAttach = el('span', 'visually-hidden', 'Attach a document');
    attachLabel.appendChild(srAttach);
    attachLabel.appendChild(el('span', 'attach-glyph', '+'));
    attachLabel.appendChild(el('span', 'attach-text', 'Attach'));
    bar.appendChild(attachLabel);

    var file = document.createElement('input');
    file.type = 'file';
    file.id = 'jobby-attach';
    file.multiple = true;
    file.accept = '.pdf,.docx,.txt';
    file.setAttribute('aria-label', 'Attach a document to parse');
    bar.appendChild(file);

    var srInput = el('label', 'visually-hidden', 'Message Jobby');
    srInput.setAttribute('for', 'jobby-input');
    bar.appendChild(srInput);

    var input = document.createElement('textarea');
    input.id = 'jobby-input';
    input.rows = 2;
    input.placeholder = 'Ask Jobby anything, or tell it something new about you…';
    input.setAttribute('autocomplete', 'off');
    bar.appendChild(input);

    var send = el('button', null, 'Send');
    send.type = 'submit';
    send.id = 'jobby-send';
    bar.appendChild(send);
    form.appendChild(bar);
    chat.appendChild(form);

    var hint = el('p', 'jobby-hint');
    hint.id = 'jobby-hint';
    hint.textContent = 'Jobby writes to your dossier when you tell it something. Attach a second '
      + 'resume and it will read that too rather than replacing what it has. Every change is '
      + 'logged and you can see it on your dashboard.';
    chat.appendChild(hint);

    return chat;
  }

  function build() {
    var root = el('div', 'jobby-widget');
    root.id = 'jobby-widget';
    root.setAttribute('data-state', 'closed');

    var panel = el('section', 'jobby-widget-panel');
    panel.id = 'jobby-widget-panel';
    panel.setAttribute('aria-label', 'Conversation with Jobby');
    panel.hidden = true;

    var head = el('header', 'jobby-widget-head');
    var title = el('h2', 'jobby-widget-title', 'Jobby McJobberson');
    head.appendChild(title);

    var headActions = el('div', 'jobby-widget-actions');
    // The page-level hint that the conversation is no longer on this page. Without
    // it, moving the chat out of the flow looks like removing it, and the honest
    // thing is to say where it went.
    var away = el('p', 'jobby-widget-away', 'Talk to Jobby from any page — this panel follows you.');
    headActions.appendChild(away);

    var close = el('button', 'jobby-widget-close');
    close.type = 'button';
    close.setAttribute('aria-label', 'Close the conversation with Jobby');
    close.innerHTML = '';
    close.appendChild(el('span', 'jobby-widget-close-glyph', '×'));
    headActions.appendChild(close);
    head.appendChild(headActions);
    panel.appendChild(head);

    panel.appendChild(buildChat());
    root.appendChild(panel);

    var launcher = el('button', 'jobby-widget-launcher');
    launcher.id = 'jobby-widget-launcher';
    launcher.type = 'button';
    launcher.setAttribute('aria-expanded', 'false');
    launcher.setAttribute('aria-controls', 'jobby-widget-panel');
    launcher.appendChild(el('span', 'jobby-widget-launcher-glyph', 'JM'));
    launcher.appendChild(el('span', 'jobby-widget-launcher-label', 'Jobby'));
    var badge = el('span', 'jobby-widget-badge');
    badge.id = 'jobby-widget-badge';
    badge.hidden = true;
    badge.setAttribute('aria-hidden', 'true');
    launcher.appendChild(badge);
    root.appendChild(launcher);

    return { root: root, panel: panel, launcher: launcher, badge: badge, close: close };
  }

  // ── open and close ───────────────────────────────────────────────────────

  function isOpen() {
    return els.root && els.root.getAttribute('data-state') === 'open';
  }

  /**
   * Stop speaking when the panel closes.
   *
   * Otherwise a candidate closes a conversation mid-answer and keeps listening to
   * it from another page, which is the exact thing a floating widget makes
   * possible and nobody asked for.
   */
  function quietSpeech() {
    try {
      if (window.JobbyTTS && typeof window.JobbyTTS.stop === 'function') window.JobbyTTS.stop();
      else if (window.speechSynthesis) window.speechSynthesis.cancel();
    } catch (e) { /* speech is not available; nothing to quiet */ }
  }

  function open(opts) {
    if (!mounted) return;
    els.root.setAttribute('data-state', 'open');
    els.panel.hidden = false;
    els.launcher.setAttribute('aria-expanded', 'true');
    clearBadge();
    markSeen();
    if (window.JobbyWidget && typeof window.JobbyWidget.onOpen === 'function') {
      try { window.JobbyWidget.onOpen(); } catch (e) { /* a hook must not block the panel */ }
    }
    restoreDraft();
    // The transcript is re-read on every open rather than cached, so a reply that
    // arrived while the panel was shut is there before the candidate looks. The
    // page is the cache; the server is the record.
    if (!opts || opts.refresh !== false) {
      fetch('/api/jobby/history?limit=30', { headers: { Accept: 'application/json' } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (h) {
          if (h && h.messages && h.messages.length) markSeen(h.messages[h.messages.length - 1].created_at);
        })
        .catch(function () { /* the badge is a nicety */ });
    }
    if (!opts || opts.focus !== false) {
      try { els.panel.querySelector('#jobby-input').focus(); } catch (e) { /* no input yet */ }
    }
    // Introduces itself, once per session — but only once the transcript is on
    // screen, because "let's find you a job" said to somebody with eight messages
    // already above it is the wrong sentence. The history is jobby.js's to fetch,
    // so this waits for the log to stop being empty rather than racing it.
    waitForTranscript();
    startPolling();
  }

  function close(opts) {
    if (!mounted) return;
    saveDraft();
    els.root.setAttribute('data-state', 'closed');
    els.panel.hidden = true;
    els.launcher.setAttribute('aria-expanded', 'false');
    if (!opts || opts.quiet !== false) quietSpeech();
    stopPolling();
    if (!opts || opts.refocus !== false) {
      try { els.launcher.focus(); } catch (e) { /* nothing to focus */ }
    }
  }

  function toggle() { if (isOpen()) close(); else open(); }

  // ── the draft ────────────────────────────────────────────────────────────
  //
  // A candidate who is half-way through "my name is actually Joe Lee, not Jordan
  // Ellis" and clicks through to the dashboard to check something should come back
  // to the sentence, not an empty box. sessionStorage rather than localStorage
  // because it is scoped to the tab and a draft is not something to find again
  // tomorrow in a browser they did not close.

  function saveDraft() {
    try {
      var input = document.getElementById('jobby-input');
      if (!input) return;
      var text = input.value || '';
      if (text.trim()) sessionStorage.setItem(DRAFT_KEY, text);
      else sessionStorage.removeItem(DRAFT_KEY);
    } catch (e) { /* private mode, or storage disabled */ }
  }

  function restoreDraft() {
    try {
      var input = document.getElementById('jobby-input');
      if (!input || input.value) return;
      var text = sessionStorage.getItem(DRAFT_KEY);
      if (!text) return;
      input.value = text;
      sessionStorage.removeItem(DRAFT_KEY);
      // The textarea autosizes on entry, which happens in jobby.js. A restored
      // draft in a one-line box looks broken, so re-run whatever the entry helper
      // returned. Held on window by initJobby for exactly this sort of reason.
      if (typeof window.JobbyWidgetResize === 'function') {
        try { window.JobbyWidgetResize(input); } catch (e) { /* cosmetic only */ }
      }
    } catch (e) { /* private mode, or storage disabled */ }
  }

  // ── the badge ────────────────────────────────────────────────────────────

  function markSeen(iso) {
    if (!iso) return;
    lastSeenAt = iso;
    try { sessionStorage.setItem(SEEN_KEY, iso); } catch (e) { /* not essential */ }
  }

  function lastSeen() {
    if (lastSeenAt) return lastSeenAt;
    try { return sessionStorage.getItem(SEEN_KEY); } catch (e) { return null; }
  }

  function clearBadge() {
    if (!els.badge) return;
    els.badge.hidden = true;
    els.badge.textContent = '';
  }

  function showBadge() {
    if (!els.badge || isOpen()) return;
    els.badge.hidden = false;
    els.badge.textContent = '1';
  }

  /**
   * One cheap request, only while the panel is shut and the tab is visible.
   *
   * Checks the newest message against the last one seen. A `jobby` message that is
   * newer means Jobby spoke while nobody was looking, which is the only thing
   * worth badging — the candidate's own message is not news to them.
   */
  function pollForNews() {
    if (isOpen() || document.hidden) return;
    fetch('/api/jobby/history?limit=1', { headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (h) {
        if (!h || !h.messages || !h.messages.length) return;
        var newest = h.messages[h.messages.length - 1];
        var seen = lastSeen();
        // No baseline yet: adopt whatever is there rather than badging a backlog
        // from a previous session as if it had just arrived.
        if (!seen) { markSeen(newest.created_at); return; }
        if (newest.role === 'jobby' && String(newest.created_at) > String(seen)) showBadge();
      })
      .catch(function () { /* a missed poll is not worth reporting */ });
  }

  function startPolling() {
    stopPolling();
    pollTimer = setInterval(pollForNews, BADGE_POLL_MS);
  }
  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  /**
   * Greet once the transcript has settled, or once it is clear nothing is coming.
   *
   * jobby.js loads the history itself, asynchronously, and does not announce when
   * it finishes. So rather than racing it, this watches the log: as soon as it holds
   * a message, the transcript is known and the greeting can pick its words. A short
   * deadline covers a genuinely new candidate, whose log stays empty forever and
   * would otherwise never be greeted at all.
   */
  function waitForTranscript() {
    if (alreadyGreeted()) return;
    var log = document.getElementById('jobby-log');
    if (!log) return;

    var done = false;
    var fire = function () {
      if (done) return;
      done = true;
      observer.disconnect();
      clearTimeout(timer);
      greet();
    };
    var observer = new MutationObserver(function () {
      if (log.querySelector('.jobby-msg')) fire();
    });
    observer.observe(log, { childList: true });
    // Long enough for a history fetch on a slow connection, short enough that a
    // first-time visitor is not left in silence.
    var timer = setTimeout(fire, 2500);
  }

  // ── the introduction ─────────────────────────────────────────────────────
  //
  // Spoken *and* written. A greeting that exists only as audio is invisible to a
  // deaf candidate and to somebody whose browser refused the sound, which is much
  // the same set of people most likely to be reading this page. Both channels carry
  // the same sentence, so the transcript and the voice never disagree about what
  // Jobby just said.
  //
  // Once per session, not once per page load. Navigating from the front page to the
  // dashboard is one conversation continuing, and a candidate who clicked through to
  // check their applications should not be greeted a second time by a voice they
  // have already heard — which is the fastest way to make an agent feel like an
  // advert.
  //
  // It is a local, session-scoped line and is NOT written to the server. Storing it
  // would be worse than useless: the Suite persists its fresh-start greeting, and
  // here that would put a "hello" at the top of a returning candidate's saved
  // history every time they opened a new tab, and a greeting that reappears in the
  // record is a bug, not a welcome. The Suite guards it with a ref for the same
  // reason; the difference is that here the record is shared and the greeting is not.

  var GREETING = {
    // New here, or here with nothing said yet.
    newUser: {
      en: "Hello, I'm Jobby. Let's find you a job!",
      es: '¡Hola! Soy Jobby. ¡Encontremoste un trabajo!',
    },
    // There is already a conversation. Saying "let's find you a job" to somebody
    // who has been applying for a week is the wrong sentence, and it is the
    // difference the Suite's quickGreetingService draws between returnUser and
    // newUser — the most useful thing in it.
    returnUser: {
      en: "Welcome back. Let's pick up where we left off.",
      es: 'Bienvenido de nuevo. Continuad donde lo dejamos.',
    },
  };

  var GREETED_KEY = 'jobby-greeted';
  var blockedNoteShown = false;

  function isSpanish() {
    try { return window.localStorage.getItem('jobby-lang') === 'es'; } catch (e) { return false; }
  }

  /**
   * Which greeting, and in which language.
   *
   * `hasHistory` comes from the transcript rather than from the server, so it is
   * correct by the time the panel opens: the widget re-reads the history before it
   * would greet, and the check below is made against what is actually on screen.
   */
  function greetingFor(hasHistory) {
    var set = hasHistory ? GREETING.returnUser : GREETING.newUser;
    return { text: isSpanish() ? set.es : set.en, lang: isSpanish() ? 'es' : 'en' };
  }

  function alreadyGreeted() {
    try { return sessionStorage.getItem(GREETED_KEY) === '1'; } catch (e) { return false; }
  }
  function markGreeted() {
    try { sessionStorage.setItem(GREETED_KEY, '1'); } catch (e) { /* not essential */ }
  }

  /**
   * The engine said no.
   *
   * Worth saying out loud, because the alternative is a feature that is on, set to
   * on, and makes no sound — which reads as broken rather than as a browser policy.
   * One line, next to the rest of the panel's status, and it goes away the moment
   * something does speak.
   */
  function noteAudioBlocked() {
    if (!els.root || blockedNoteShown) return;
    var note = document.getElementById('jobby-audio-note');
    if (!note) {
      note = el('p', 'jobby-audio-note');
      note.id = 'jobby-audio-note';
      note.setAttribute('role', 'status');
      var hint = els.panel && els.panel.querySelector('.jobby-hint');
      if (hint && hint.parentNode) hint.parentNode.insertBefore(note, hint);
    }
    note.textContent = 'Jobby will say this once you click anywhere on the page — browsers keep '
      + 'speech silent until then.';
    blockedNoteShown = true;
  }

  function clearAudioBlocked() {
    var note = document.getElementById('jobby-audio-note');
    if (note) note.remove();
    blockedNoteShown = false;
  }

  function greet() {
    if (alreadyGreeted()) return;
    // Whether there is already a conversation, read from the log the history pass
    // has just filled rather than guessed, so a returning candidate is recognised
    // as one.
    var hasHistory = !!document.querySelector('#jobby-log .jobby-msg');
    var g = greetingFor(hasHistory);

    // In the transcript first, so it is there even if the sound never is. At the
    // top, because it is an introduction to this session and not an answer to
    // whatever the last stored message happened to be.
    if (window.jobbyAddMessage) {
      try { window.jobbyAddMessage('jobby', g.text, null, 'top'); } catch (e) { /* the log is the nicety */ }
    }

    var tts = window.JobbyTTS;
    if (!tts || !tts.supported || !tts.supported()) return;
    if (!window.JobbyChat || typeof window.JobbyChat.speakOnFirstGesture !== 'function') return;

    window.JobbyChat.speakOnFirstGesture(g.text, { lang: g.lang })
      .then(function (r) {
        if (r && r.spoke) { markGreeted(); clearAudioBlocked(); }
        else noteAudioBlocked();
      })
      .catch(function () { noteAudioBlocked(); });
  }

  // ── wiring ───────────────────────────────────────────────────────────────

  function init() {
    if (mounted) return;
    if (document.getElementById('jobby-widget')) return; // already there

    var built = build();
    els = built;
    document.body.appendChild(built.root);
    mounted = true;

    built.launcher.addEventListener('click', toggle);
    built.close.addEventListener('click', function () { close(); });

    // Escape closes, but only from inside the panel — a page-level Escape handler
    // would fight every dialog the site opens.
    built.panel.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.stopPropagation(); close(); }
    });

    // A draft survives a navigation only if it is written as it is typed.
    document.addEventListener('input', function (e) {
      if (e.target && e.target.id === 'jobby-input') saveDraft();
    });

    // Coming back to the tab is the moment a badge is most likely to be stale, and
    // also the moment the candidate is most likely to be looking.
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) pollForNews();
    });

    // Translated after it is built, because i18n's own pass over the document ran
    // before this file existed. The module exports applyI18nTo for exactly this:
    // a region created after the page's pass.
    if (window.JobbyI18n && typeof window.JobbyI18n.applyI18nTo === 'function') {
      try { window.JobbyI18n.applyI18nTo(built.root); } catch (e) { /* English is a fine fallback */ }
    }

    // Open on the front page, where the conversation starts. Everywhere else it
    // waits, so the dashboard does not open with a panel covering the numbers
    // someone came to read.
    if (OPENS_ON_ARRIVAL.test(location.pathname)) {
      open({ focus: false });
    } else {
      // The baseline is "whatever is already there" — adopted, not badged, so
      // yesterday's conversation does not arrive as a fresh alert.
      fetch('/api/jobby/history?limit=1', { headers: { Accept: 'application/json' } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (h) {
          if (h && h.messages && h.messages.length) markSeen(h.messages[h.messages.length - 1].created_at);
        })
        .catch(function () { /* no baseline; the badge just stays quiet */ });
      startPolling();
    }
  }

  window.JobbyWidget = {
    open: open,
    close: close,
    toggle: toggle,
    isOpen: isOpen,
    // Read by jobby.js so a reply that lands while the panel is shut still gets
    // badged rather than arriving silently.
    onReply: function (createdAt) {
      if (createdAt && String(createdAt) > String(lastSeen() || '')) showBadge();
    },
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
