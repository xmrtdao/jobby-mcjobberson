/**
 * The jobs list, read from the relay's board.
 *
 * This is the public half of the product. Everything else on the page is about
 * one person's record; this is the market they are being measured against, and it
 * is the only part of the site where the product has touched something it did not
 * write.
 *
 * Three rules, all of them from having got this wrong in a sibling project:
 *
 *  1. **Nothing is shown without its source.** Every row carries the feed it came
 *     from. A job with no attribution is a rumour, and a rumour in a list that
 *     looks authoritative is worse than an absent row.
 *
 *  2. **The trust note is rendered, not stored.** The relay sends a `note` with
 *     every response saying nobody has verified these and the employer is
 *     sometimes read out of a title. It goes on the page. Leaving it in a JSON
 *     field for a component to maybe render later is how a disclaimer becomes
 *     decoration.
 *
 *  3. **A gap reads as a gap.** No location, no employer, no date — each says so
 *     in those words. It is never filled with a plausible value, because a
 *     candidate filtering by city cannot tell an invented location from a real
 *     one, and will act on the wrong one.
 */
(function () {
  'use strict';

  var els = {};
  var state = { jobs: [], count: { n: 0, worth: 0, feeds: 0, companies: 0 }, bySource: [], registry: null, problems: [], feed: '', q: '', note: '' };
  var PAGE = 24;
  var shown = PAGE;

  function el(tag, className, text) {
    var n = document.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }

  function cache() {
    ['jobs-search', 'jobs-feed', 'jobs-count', 'jobs-trust', 'jobs-body', 'jobs-registry']
      .forEach(function (id) { els[id] = document.getElementById(id); });
  }

  // ── one row ──────────────────────────────────────────────────────────────

  /**
   * How the employer on this row was arrived at, in words a reader can act on.
   *
   * "GitLab" and "GitLab" are not the same claim. The first is a field the
   * employer's own board carried; the second was read out of a headline by a
   * string split, which is a reading of what somebody published rather than a fact
   * anybody asserted. A candidate deciding whether to trust a company name is
   * entitled to that difference before they click, not after.
   */
  function provenanceNote(p) {
    switch (p) {
      case 'stated_as_field':
        return 'employer stated by the employer’s own board';
      case 'stated_by_board':
        return 'employer named by the board this came from';
      case 'not_stated':
        return 'no employer stated';
      default:
        if (p && p.indexOf('stated_in_title') === 0) {
          return 'employer read out of the posting title';
        }
        return null;
    }
  }

  function row(job) {
    var li = el('li', 'job-row');

    var main = el('div', 'job-main');

    // The role is the link, because the role is what you came for. The employer
    // sits under it rather than beside it: a posting titled for a function reads
    // better with the company as a subtitle than as a second headline.
    var role = el('a', 'job-role', job.role || 'Untitled role');
    role.href = job.url || '#';
    if (job.url) {
      role.target = '_blank';
      // noopener because these go to employer sites and a window.opener handle
      // from there is a thing nobody on this page asked for.
      role.rel = 'noopener noreferrer';
    }
    main.appendChild(role);

    var facts = el('p', 'job-facts');
    // Every one of these says "not stated" rather than being omitted or guessed.
    // A blank between two facts is indistinguishable from a field that failed to
    // load, and a reader cannot act on that.
    facts.appendChild(el('span', 'job-fact' + (job.company ? '' : ' is-absent'),
      job.company || 'Employer not stated'));
    facts.appendChild(el('span', 'job-fact' + (job.location ? '' : ' is-absent'),
      job.location || 'Location not stated'));
    if (job.arrangement) {
      facts.appendChild(el('span', 'job-fact', job.arrangement));
    }
    main.appendChild(facts);
    li.appendChild(main);

    var prov = provenanceNote(job.source && job.source.companyProvenance);
    var meta = el('div', 'job-meta');
    if (job.source && job.source.feed) {
      meta.appendChild(el('span', 'job-feed', job.source.feed));
    }
    if (prov) {
      var p = el('span', 'job-prov' + (job.source.companyProvenance === 'not_stated' ? ' is-absent' : ''), prov);
      p.title = 'How this employer name was arrived at';
      meta.appendChild(p);
    }
    li.appendChild(meta);
    return li;
  }

  // ── the list ─────────────────────────────────────────────────────────────

  function render() {
    var host = els['jobs-body'];
    if (!host) return;
    host.replaceChildren();

    if (!state.jobs.length) {
      host.appendChild(el('p', 'empty-note',
        state.q || state.feed
          ? 'Nothing on the board matches that. Try a broader word, or every source.'
          : 'No jobs on the board yet. The feeds are polled on a schedule; check back shortly.'));
      els['jobs-count'].textContent = '0 shown';
      return;
    }

    var list = el('ul', 'job-list');
    state.jobs.slice(0, shown).forEach(function (j) { list.appendChild(row(j)); });
    host.appendChild(list);

    // The figures, as figures.
    //
    // Three numbers in a sentence of small grey text is the wrong shape: the
    // reader skims, and a skim of "24 shown of 1315 on the board across 493
    // employers" yields nothing. Rendered as labelled figures instead, so the size
    // of the board is the first thing seen rather than the last thing parsed.
    //
    // `count` is an object from the relay — {n, worth, feeds, companies} — not a
    // number. It was read as a scalar for a while, which printed the literal text
    // "24 shown of [object Object] on the board" directly under a list of jobs.
    var board = state.count || {};
    var total = typeof board.n === 'number' ? board.n : state.jobs.length;
    var onScreen = Math.min(shown, state.jobs.length);
    var filtered = !!(state.q || state.feed);

    var stats = [];
    // The board's size leads, and it is the number that is not affected by the
    // filter — so a search that returns three rows does not appear to shrink the
    // market to three.
    stats.push({ value: total.toLocaleString(), label: filtered ? 'jobs matching' : 'jobs on the board' });
    if (typeof board.companies === 'number' && board.companies) {
      stats.push({ value: board.companies.toLocaleString(), label: 'employers' });
    }
    if (typeof board.feeds === 'number' && board.feeds) {
      stats.push({ value: String(board.feeds), label: board.feeds === 1 ? 'source' : 'sources' });
    }
    if (onScreen < total) {
      // Said as its own figure rather than a parenthetical, because the relay caps
      // a response and a list that silently shows 200 of 1,315 reads as "these are
      // the jobs" rather than "these are the newest 200".
      stats.push({ value: onScreen.toLocaleString(), label: 'shown now', quiet: true });
    }

    var host = els['jobs-count'];
    host.replaceChildren();
    stats.forEach(function (s) {
      var cell = el('p', 'jobs-stat' + (s.quiet ? ' is-quiet' : ''));
      cell.appendChild(el('span', 'jobs-stat-value', s.value));
      cell.appendChild(el('span', 'jobs-stat-label', s.label));
      host.appendChild(cell);
    });

    if (state.jobs.length > shown) {
      var more = el('button', 'button button-small jobs-more',
        'Show ' + Math.min(PAGE, state.jobs.length - shown) + ' more');
      more.type = 'button';
      more.addEventListener('click', function () { shown += PAGE; render(); });
      host.appendChild(more);
    }
  }

  /**
   * Where the jobs came from, and which sources are worth trusting for what.
   *
   * The per-source numbers are the useful part, and they are the reason this is a
   * table rather than a footnote. A source that states the employer on every row
   * and one that states it on none produce lists that look identical until you
   * count, and the reader is the one who has to decide whether to click.
   *
   * `employerFromTitle` is broken out from `employerStated` rather than folded in,
   * because the two are not the same claim and merging them is how a company name
   * produced by a string split ends up reading like one an employer published.
   */
  function renderRegistry() {
    var host = els['jobs-registry'];
    if (!host) return;
    host.replaceChildren();

    if (state.problems && state.problems.length) {
      var warn = el('div', 'jobs-reg-problems');
      warn.appendChild(el('p', 'jobs-reg-group', 'Known problems with the board'));
      var ul = el('ul');
      state.problems.forEach(function (p) { ul.appendChild(el('li', null, p)); });
      warn.appendChild(ul);
      host.appendChild(warn);
    }

    if (!state.bySource.length) return;

    host.appendChild(el('p', 'jobs-reg-group', 'What each source contributed'));
    var t = el('table', 'jobs-reg-table');
    var head = el('tr');
    ['Source', 'Jobs', 'Employer stated', 'From the title', 'No employer', 'Location stated']
      .forEach(function (h) { head.appendChild(el('th', null, h)); });
    t.appendChild(head);

    state.bySource.forEach(function (r) {
      var tr = el('tr');
      tr.appendChild(el('td', null, r.feed_name || r.feed_id));
      tr.appendChild(el('td', 'is-num', String(r.jobs)));
      tr.appendChild(el('td', 'is-num', String(r.employer_stated)));
      // Dimmed rather than hidden: a source whose employers all come from titles is
      // not useless, it is just a different kind of claim, and hiding the number
      // would leave the reader to assume the good ones.
      tr.appendChild(el('td', 'is-num is-derived', String(r.employer_from_title)));
      tr.appendChild(el('td', 'is-num' + (r.employer_not_stated ? ' is-absent' : ''),
        String(r.employer_not_stated)));
      tr.appendChild(el('td', 'is-num' + (r.location_stated ? '' : ' is-absent'),
        String(r.location_stated)));
      t.appendChild(tr);
    });
    host.appendChild(t);

    if (state.registry && state.registry.disabled) {
      host.appendChild(el('p', 'jobs-reg-foot',
        state.registry.disabled + ' further ' + (state.registry.disabled === 1 ? 'source is' : 'sources are')
        + ' in the registry and switched off — measured, found dead, and kept with the reason rather '
        + 'than deleted. A deleted source is indistinguishable from one never tried.'));
    }
  }

  function fillFeedOptions() {
    var sel = els['jobs-feed'];
    if (!sel || sel.options.length > 1) return;
    state.bySource
      .filter(function (r) { return r.feed_name; })
      .sort(function (a, b) { return String(a.feed_name).localeCompare(String(b.feed_name)); })
      .forEach(function (r) {
        var o = document.createElement('option');
        o.value = r.feed_id;
        o.textContent = r.feed_name + ' (' + r.jobs + ')';
        sel.appendChild(o);
      });
  }

  // ── loading ──────────────────────────────────────────────────────────────

  var inflight = null;

  function load() {
    if (!els['jobs-body']) return;
    var params = new URLSearchParams();
    params.set('limit', '200');
    if (state.feed) params.set('feed', state.feed);
    if (state.q) params.set('q', state.q);
    // Deliberately not worthBuildingOnly. The board's default hides links that
    // are not specific requisitions, which is right for a packet and wrong for a
    // public list: a candidate reading a market wants to know a role exists, and
    // the source is attached to every row either way.
    params.set('all', '1');

    if (inflight) inflight.abort();
    var controller = new AbortController();
    inflight = controller;

    fetch('/api/jobby/board?' + params.toString(), {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error('could not load the board')); })
      .then(function (data) {
        state.jobs = data.jobs || [];
        // An object, not a number. See the note where it is read.
        state.count = data.count || { n: state.jobs.length };
        state.note = data.note || '';
        state.bySource = data.bySource || [];
        state.registry = data.registry || null;
        state.problems = data.healthProblems || [];
        els['jobs-trust'].textContent = state.note;
        fillFeedOptions();
        renderRegistry();
        shown = PAGE;
        render();
      })
      .catch(function (e) {
        if (e.name === 'AbortError') return;   // superseded by a newer request
        els['jobs-body'].replaceChildren();
        els['jobs-body'].appendChild(el('p', 'empty-note',
          'Could not load the board: ' + e.message));
        els['jobs-count'].textContent = '';
      });
  }

  // ── wiring ───────────────────────────────────────────────────────────────

  function init() {
    cache();
    if (!els['jobs-body']) return;

    var timer = null;
    els['jobs-search'].addEventListener('input', function (e) {
      state.q = (e.target.value || '').trim();
      // Debounced, because this fires per keystroke and each one is a request.
      // 300ms is long enough to coalesce a word and short enough not to feel laggy.
      clearTimeout(timer);
      timer = setTimeout(load, 300);
    });
    els['jobs-feed'].addEventListener('change', function (e) {
      state.feed = e.target.value || '';
      load();
    });

    load();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.JobbyJobs = { reload: load, state: state };
}());
