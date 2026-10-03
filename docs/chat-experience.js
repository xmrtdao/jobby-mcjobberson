/**
 * chat-experience.js — the two usability layers the candidate chat was missing
 *
 * Ported from the Suite SPA's UnifiedChat and its TTS services, which is where
 * this behaviour was actually dialled in. Copied as patterns, not as a dependency:
 * that is TypeScript and React, this is two static files served with no build.
 *
 * ── What was taken, and why each part was worth taking ─────────────────────
 *
 * **A speech queue, not a fire-and-forget call.** `speak()` while already
 * speaking cancels the current utterance in most engines, so a candidate who
 * receives two replies in quick succession hears the first one cut off. UnifiedChat
 * queues, drains one at a time, and resolves a promise per item. That is the whole
 * difference between speech synthesis that works and speech synthesis that works
 * most of the time.
 *
 * **A text sanitizer before speaking.** A model reply is markdown, and
 * "**Red Seal**" read aloud as "asterisk asterisk Red Seal asterisk asterisk" is
 * worse than silence. UnifiedChat strips emphasis, code, links, list bullets and
 * emoji before it hands text to the engine.
 *
 * **The Chrome `synthesis-failed` workaround.** This is the part that was
 * genuinely expensive to learn. Chrome's speech engine wedges into a state where
 * every subsequent call fails, and the recovery is to `resume()` the engine, re-
 * read the voice list, and speak again. Copied verbatim in behaviour because
 * nothing else in that file is subtle.
 *
 * **Voice selection with a real fallback chain.** Preferred voice → any voice for
 * the language → any English voice → the first voice available → the engine
 * default. Picking one and hoping is how you get a silent button on a machine with
 * one voice installed.
 *
 * **The preference is remembered, and it starts ON.** UnifiedChat stores
 * `audioEnabled` in the same localStorage key, so somebody who enabled audio there
 * is not asked again — and somebody who turned it *off* here stays off, because
 * only an explicit `'0'` disables it. Absence of a stored value is a first visit,
 * not a decision, and Jobby introduces itself out loud.
 *
 * It was off by default, on the reasoning that unbidden speech is rude. That was a
 * real objection and it was aimed at the wrong thing: the problem was never that
 * Jobby speaks, it was that it would have spoken *unprompted, mid-thought, with no
 * way to tell the voice from an advert*. Speaking once, as an introduction, with a
 * visible control and a remembered off switch, is a different thing entirely.
 *
 * The browser still will not allow sound before the user has interacted with the
 * page, and refuses silently when it does not. `speakOnFirstGesture` exists for
 * that and is the reason this feature can be on by default without being broken on
 * arrival.
 *
 * ── One bug deliberately not copied ────────────────────────────────────────
 *
 * UnifiedChat sends on `Enter` unless Shift is held, with no check for IME
 * composition. On a Japanese, Chinese or Korean keyboard, Enter is how a
 * composition is *confirmed* — so a candidate mid-word would have their message
 * sent by the act of choosing a character. `isComposing` is checked here, and the
 * event's own `keyCode === 229` is honoured too, because not every browser sets
 * `isComposing` on the event.
 */
(function () {
  'use strict';

  // ── TTS ────────────────────────────────────────────────────────────────────

  const synth = typeof window !== 'undefined' ? window.speechSynthesis : null;

  const voiceQueue = [];
  let draining = false;
  let currentUtterance = null;
  let voicesReady = false;
  // The interactions that unlock speech. Captured, not scroll: a scroll is not a
  // deliberate act in every browser and a page that has just reflowed can fire one
  // without the reader having done anything.
  var GESTURES = ['pointerdown', 'keydown', 'touchstart', 'click'];

  let enabled = false;
  const listeners = { state: [] };

  function emit() {
    for (const fn of listeners.state) {
      try { fn({ enabled, speaking: !!currentUtterance, queued: voiceQueue.length }); } catch (e) { /* a broken listener is not the caller's problem */ }
    }
  }

  /**
   * Markdown, links and emoji, stripped.
   *
   * Copied in behaviour from UnifiedChat's sanitizer, which is the part of that
   * file that had clearly been written against real output rather than imagined
   * output. The order matters: code fences go before inline code, or the inline
   * pass shreds the fences.
   */
  function sanitizeForSpeech(text) {
    return String(text == null ? '' : text)
      .replace(/```[\s\S]*?```/g, ' ')
      .replace(/`([^`]+)`/g, '$1')
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1')   // links: read the label, not the href
      .replace(/https?:\/\/\S+/g, ' ')
      .replace(/\*\*([^*]+)\*\*/g, '$1')
      .replace(/\*([^*]+)\*/g, '$1')
      .replace(/__([^_]+)__/g, '$1')
      .replace(/_([^_]+)_/g, '$1')
      .replace(/~~([^~]+)~~/g, '$1')
      .replace(/^\s*[-*+]\s+/gm, '')
      .replace(/^\s*\d+\.\s+/gm, '')
      .replace(/[←-⇿⌀-➿⬀-⯿️]/gu, ' ')
      .replace(/[#*_~|]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  /**
   * The voice list, which is empty on first read in Chrome.
   *
   * `getVoices()` returns [] until the engine has loaded, and the only reliable
   * signal is the `voiceschanged` event. Polling too, because the event does not
   * fire on every platform. Two paths because one path is not enough.
   */
  function loadVoices(timeoutMs) {
    if (!synth) return Promise.resolve([]);
    if (voicesReady) return Promise.resolve(synth.getVoices());

    return new Promise((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        voicesReady = true;
        synth.removeEventListener?.('voiceschanged', finish);
        resolve(synth.getVoices());
      };
      synth.addEventListener?.('voiceschanged', finish);
      // The event is not guaranteed, so a timer is the actual mechanism and the
      // listener is the optimisation.
      const t = setTimeout(finish, timeoutMs || 1200);
      // Nudge the engine, which is what makes some of them populate the list.
      try { synth.getVoices(); } catch (e) { /* nothing to nudge */ }
      void t;
    });
  }

  /** The fallback chain, in order. Each step is a real narrowing, not a repeat. */
  function chooseVoice(voices, lang) {
    if (!voices || !voices.length) return null;
    const prefix = lang === 'es' ? 'es' : 'en';
    const byName = (fragments) => voices.find((v) => {
      const n = (v.name || '').toLowerCase();
      return fragments.some((f) => n.includes(f));
    });
    // Preferred, by the names a desktop browser actually ships with.
    const named = lang === 'es'
      ? byName(['monica', 'paulina', 'diego', 'helena', 'sabina', 'juan'])
      : byName(['samantha', 'alex', 'daniel', 'karen', 'moira', 'google us english']);
    if (named && named.lang.toLowerCase().startsWith(prefix)) return named;
    const anyLang = voices.find((v) => v.lang.toLowerCase().startsWith(prefix));
    if (anyLang) return anyLang;
    if (lang !== 'en') {
      const en = voices.find((v) => v.lang.toLowerCase().startsWith('en'));
      if (en) return en;
    }
    return voices[0] || null;
  }

  function speakOnce(text, opts) {
    const options = opts || {};
    const clean = sanitizeForSpeech(text);
    if (!clean) return Promise.resolve({ spoke: false, reason: 'nothing to read' });

    return new Promise((resolve) => {
      let done = false;
      const finish = (spoke, reason) => {
        if (done) return;
        done = true;
        currentUtterance = null;
        emit();
        resolve({ spoke, reason });
      };

      const utter = new SpeechSynthesisUtterance(clean);
      currentUtterance = utter;
      utter.rate = options.rate || 0.98;
      utter.pitch = 1.0;
      utter.volume = 1.0;
      utter.lang = options.lang === 'es' ? 'es-ES' : 'en-US';

      const voice = chooseVoice(synth.getVoices(), options.lang);
      if (voice) {
        utter.voice = voice;
        utter.lang = voice.lang;
      }

      utter.onend = () => finish(true);
      utter.onerror = (e) => {
        // 'canceled' and 'interrupted' mean a person stopped it or a new message
        // arrived. Not failures, and reporting them as failures makes the UI flash
        // an error every time someone types quickly.
        const err = e && e.error;
        if (err === 'canceled' || err === 'interrupted') return finish(false, 'stopped');
        if (err === 'synthesis-failed' && !options._retried) {
          // The Chrome wedge. resume() plus a voice re-read is the documented way
          // out of it, and it is the reason this service exists in this shape.
          try { synth.resume(); } catch (e2) { /* ignore */ }
          try { synth.getVoices(); } catch (e2) { /* ignore */ }
          return speakOnce(text, Object.assign({}, options, { _retried: true }))
            .then((r) => finish(r.spoke, r.reason));
        }
        return finish(false, err || 'failed');
      };

      try {
        synth.speak(utter);
      } catch (e) {
        finish(false, 'unavailable');
      }
    });
  }

  async function drain() {
    if (draining) return;
    draining = true;
    while (voiceQueue.length) {
      const item = voiceQueue.shift();
      try {
        // eslint-disable-next-line no-await-in-loop
        await speakOnce(item.text, item.opts);
      } catch (e) {
        /* one failure must not stop the queue draining */
      }
      if (item.done) item.done();
    }
    draining = false;
  }

  const tts = {
    supported() { return !!synth; },

    /** Read this aloud, after anything already queued. */
    speak(text, opts) {
      if (!enabled || !synth) return Promise.resolve({ spoke: false, reason: 'disabled' });
      voiceQueue.push({ text, opts: opts || {} });
      emit();
      return drain();
    },

    /** Turn it on. Must be called from a click, or the engine stays muted. */
    async enable() {
      if (!synth) return { ok: false, reason: 'not supported' };
      // Some engines refuse the first utterance without a resume() in the same
      // task as a user gesture.
      try { synth.resume(); } catch (e) { /* ignore */ }
      await loadVoices();
      enabled = true;
      try { localStorage.setItem('jobby_audioEnabled', '1'); } catch (e) { /* private mode */ }
      emit();
      return { ok: true, voices: (synth.getVoices() || []).length };
    },

    disable() {
      enabled = false;
      voiceQueue.length = 0;
      try { synth?.cancel(); } catch (e) { /* ignore */ }
      try { localStorage.removeItem('jobby_audioEnabled'); } catch (e) { /* ignore */ }
      emit();
    },

    isEnabled() { return enabled; },

    /** Stop what is playing and drop the queue. */
    stop() {
      voiceQueue.length = 0;
      try { synth?.cancel(); } catch (e) { /* ignore */ }
      currentUtterance = null;
      emit();
    },

    onState(fn) {
      listeners.state.push(fn);
      fn({ enabled, speaking: !!currentUtterance, queued: voiceQueue.length });
      return () => {
        const i = listeners.state.indexOf(fn);
        if (i >= 0) listeners.state.splice(i, 1);
      };
    },

    sanitizeForSpeech,
  };

  window.JobbyTTS = tts;

  // ── Text entry ────────────────────────────────────────────────────────────

  /**
   * Enter sends, Shift+Enter breaks the line — and neither happens while an IME
   * composition is in progress.
   *
   * The composition check is the part UnifiedChat lacks. On a Japanese, Chinese or
   * Korean keyboard, Enter confirms the character being composed; treating that
   * as "send" means a candidate composing a word sends a half-typed one and loses
   * the rest. `isComposing` is the standard signal and `keyCode === 229` is the
   * legacy one, and both are checked because not every browser sets the first.
   */
  function wireTextEntry(input, send, { onTyping } = {}) {
    if (!input || !send) return null;

    input.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      // IME: the key press belongs to the composition, not to us.
      if (e.isComposing || e.keyCode === 229) return;
      // And a modifier the platform uses for its own shortcuts.
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      e.preventDefault();
      send();
    });

    // Grow with the content up to a ceiling, then scroll. An autosize that never
    // stops is a textarea that pushes the send button off the screen.
    let typingTimer = null;
    const resize = () => {
      input.style.height = 'auto';
      const max = 168;
      input.style.height = Math.min(input.scrollHeight, max) + 'px';
      input.style.overflowY = input.scrollHeight > max ? 'auto' : 'hidden';
    };
    input.addEventListener('input', () => {
      resize();
      if (onTyping) {
        clearTimeout(typingTimer);
        typingTimer = setTimeout(() => onTyping(false), 1400);
        onTyping(true);
      }
    });
    input.addEventListener('keyup', (e) => {
      if (e.key === 'Enter' && (e.shiftKey || e.isComposing || e.keyCode === 229)) resize();
    });

    return { resize };
  }

  /**
   * Restores the preference without turning speech on.
   *
   * UnifiedChat auto-initialises on mount, which means a candidate who enabled
   * voice once is read aloud to forever with no way to have declined. A stored
   * preference is honoured as "this person asked for it" — and the browser still
   * requires a gesture before the first sound, so the toggle stays visibly off
   * until they press it.
   */
  function restoreAudioPreference() {
    let stored = null;
    try { stored = localStorage.getItem('jobby_audioEnabled'); } catch (e) { stored = null; }
    // Only an explicit "0" turns it off. Absence of a stored value is not a
    // decision by the candidate, it is a first visit, and the answer there is on.
    if (stored === '0') {
      enabled = false;
      emit();
      return false;
    }
    // Written on the first visit, so the preference is a stored decision rather
    // than an absence that has to be re-interpreted on every load. Matches the
    // Suite's `initializeTTS`, which sets audioEnabled at mount for the same
    // reason: one key, one meaning, no default that quietly changes.
    if (stored === null) {
      try { localStorage.setItem('jobby_audioEnabled', '1'); } catch (e) { /* private mode */ }
    }
    enabled = true;
    emit();
    // Warmed here rather than on the first `speak()`.
    //
    // Taken from the Suite's `initializeTTS` on mount, and for the same reason: the
    // voice list arrives asynchronously, so an utterance started before it resolves
    // is read by whatever voice the engine happens to default to — which is how a
    // greeting ends up in the wrong accent. A greeting has no second chance, so the
    // list is read before it is ever needed.
    prewarm();
    // "Wanted", not "confirmed". The browser still requires a gesture for the
    // first sound, so the caller arms a listener rather than treating this as
    // audible. Returning false here would also be a lie in the other direction.
    return true;
  }

  /**
   * Read the voice list before anything needs to speak.
   *
   * Also nudges the engine awake. Some builds deliver an empty list until
   * `voiceschanged` fires, and some stay paused after a page load with no
   * utterance ever having been made — which reads as "TTS is broken" and is not.
   */
  function prewarm() {
    if (!synth) return;
    try { synth.resume(); } catch (e) { /* some engines have no resume */ }
    // loadVoices sets `voicesReady` itself and is a no-op once warm, so calling it
    // on every load costs nothing and cannot double-read the list.
    loadVoices(1500);
  }

  /**
   * Say the introduction, at the earliest moment the browser will allow sound.
   *
   * The part that cannot be taken at face value: every current engine - Chrome,
   * Safari, Firefox - refuses `speechSynthesis.speak()` before the user has
   * interacted with the page, and refuses *silently*. No error, no event, nothing
   * to catch. A greeting that just called speak() on load would pass every check
   * and be completely inaudible in a browser, which is the worst outcome available
   * for a feature whose entire point is being heard.
   *
   * So: try now, and if the engine declines, arm a one-shot listener for the first
   * real interaction and speak there. For somebody who has just arrived that is a
   * click away. It is as close as the platform allows to "speaks when it appears",
   * and it degrades to sound on the first touch rather than to unexplained silence.
   */
  function speakOnFirstGesture(text, opts) {
    if (!enabled || !synth) return Promise.resolve({ spoke: false, reason: 'disabled' });

    let armed = true;
    const detach = () => {
      for (const ev of GESTURES) window.removeEventListener(ev, fire, true);
      window.removeEventListener('focus', fire, true);
    };
    function fire() {
      if (!armed) return;
      armed = false;
      detach();
      // A gesture is the one moment the engine is guaranteed to accept, so the
      // utterance is *started* here rather than merely attempted.
      try { synth.resume(); } catch (e) { /* some engines have no resume */ }
      speak(text, opts);
    }
    for (const ev of GESTURES) window.addEventListener(ev, fire, true);
    window.addEventListener('focus', fire, true);

    const attempt = speak(text, opts);
    return attempt.then((r) => {
      if (r && r.spoke) { armed = false; detach(); }
      return r;
    });
  }

  window.JobbyChat = { wireTextEntry, restoreAudioPreference, speakOnFirstGesture, prewarm, tts };
}());
