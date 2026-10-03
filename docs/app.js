const dropZone = document.getElementById('resume-drop-zone');
const dropArea = document.getElementById('resume-drop-area');
const fileInput = document.getElementById('resume-file');
const statusElement = document.getElementById('resume-status');
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const SUPPORTED_TYPES = new Set([
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'text/plain',
]);

function setStatus(message, kind = 'neutral') {
  statusElement.textContent = message;
  statusElement.dataset.kind = kind;
}

function validateFile(file) {
  if (!file) return 'Choose one PDF, DOCX, or TXT resume.';
  if (file.size > MAX_UPLOAD_BYTES) return 'Resume must be 10 MB or smaller.';
  if (!SUPPORTED_TYPES.has(file.type)) return 'Use a PDF, DOCX, or TXT resume.';
}

async function parseResume(file) {
  const error = validateFile(file);
  if (error) {
    setStatus(error, 'error');
    return null;
  }
  setStatus(tn('Parsing') + ' ' + file.name + '…', 'working');
  try {
    const form = new FormData();
    form.append('lang', currentLang());
    form.append('resume', file, file.name);
    form.append('format', file.name.split('.').pop().toLowerCase());
    const response = await fetch('/api/resume/parse', {
      method: 'POST',
      body: form,
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || 'Resume parsing failed.');
    renderParsedProfile(result);
    stopDossierPolling();
    const dossier = result.dossier;
    if (dossier && dossier.request_id) {
      showDossierPending();
      setStatus(tn('Resume parsed. Building the dossier…'), 'working');
      pollDossier(dossier.request_id);
    } else {
      setStatus(tn('Resume parsed. Profile is ready for review.'), 'success');
    }
    return result;
  } catch (error) {
    setStatus(error.message, 'error');
    return null;
  }
}

function renderList(elementId, values) {
  const list = document.getElementById(elementId);
  if (!list) return;
  list.replaceChildren();
  const items = Array.isArray(values) ? values : [];
  if (!items.length) {
    const item = document.createElement('li');
    item.textContent = 'Not found in resume';
    list.appendChild(item);
    return;
  }
  items.forEach(value => {
    const item = document.createElement('li');
    item.textContent = String(value);
    list.appendChild(item);
  });
}

function renderParsedProfile(profile) {
  const existing = document.getElementById('parsed-profile');
  if (!existing) return;
  existing.hidden = false;
  renderList('parsed-skills', profile.skills || []);
  renderList('parsed-fields', profile.job_fields || []);
  renderList('parsed-links', profile.urls || []);
}

/* ---------------------------------------------------------------- dossier */

const dossierPanel = document.getElementById('dossier-panel');
const dossierHeading = document.getElementById('dossier-heading');
const dossierBody = document.getElementById('dossier-body');
let dossierTimer = null;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

// A card is skipped entirely when the AI had nothing confirmed for it, so the
// panel never fills with "Not found" noise.
function dossierCard(title, children) {
  const kept = children.filter(Boolean);
  if (!kept.length) return null;
  const card = el('article', 'parsed-card dossier-card');
  card.appendChild(el('h3', null, title));
  kept.forEach(child => card.appendChild(child));
  return card;
}

// Source-extracted lists pass an emptyText so the reader can tell "the resume
// listed none" from "we did not look". Inferred lists pass null, which omits
// the card entirely rather than showing a lone placeholder.
function dossierList(values, emptyText) {
  const items = Array.isArray(values) ? values.filter(Boolean) : [];
  if (!items.length) {
    if (!emptyText) return null;
    const placeholder = el('ul', 'dossier-list');
    placeholder.appendChild(el('li', 'dossier-muted', emptyText));
    return placeholder;
  }
  const list = el('ul', 'dossier-list');
  items.forEach(value => list.appendChild(el('li', null, value)));
  return list;
}

/**
 * One line of text, as a dossier record card.
 *
 * The counterpart to `dossierList`. A bullet list is right for a short inline set
 * — skills, target roles, links — where the list is a qualifier on the card
 * around it. It is the wrong shape for the sections a CV is built from: education,
 * achievements, and the two sections reporting what could not be established. Those
 * were rendered as bullets while employment was rendered as cards, so the dossier
 * looked designed for its first section and unstyled for the rest, even though
 * every line was the same kind of fact.
 *
 * `variant` changes the accent only, never the structure:
 *   'is-gap'  — the source was silent. Grey.
 *   'is-flag' — the extraction saw something it will not vouch for. Amber.
 *   none      — stated plainly. Blue, same as employment.
 *
 * Achievements pass `is-compact`, because that card repeats more than any other on
 * the page and does not need employment's vertical padding to be legible.
 */
function dossierEntryCards(values, variant) {
  const items = Array.isArray(values) ? values.filter(Boolean) : [];
  if (!items.length) return null;
  const wrap = el('div', 'dossier-timeline');
  const cls = 'dossier-entry' + (variant ? ' ' + variant : '');
  items.forEach(value => {
    const card = el('article', cls);
    // The line goes in a heading, not straight into the card.
    //
    // A first version appended the text to the <article> directly, which produced
    // the card and the drop shadow but left the line as body text — so those
    // sections looked like employment from across the room and lost the blue
    // headline only at reading distance. The heading is what carries the accent
    // colour in the shared rule, so the line has to be inside one.
    //
    // h3 matches the employment cards, which already use it for the same purpose.
    card.appendChild(el('h3', null, String(value)));
    wrap.appendChild(card);
  });
  return wrap;
}

/**
 * Confirmed achievements, as medal ribbons.
 *
 * These were one dossier card each — a bordered tile with a drop shadow, the same
 * object as an employment card. Fifteen of them turned the bottom of the dossier
 * into a wall of identical tiles, and the thing that is supposed to feel like
 * evidence felt like inventory.
 *
 * A ribbon reads differently on purpose: it marks the line as something the
 * candidate can point at, and it lets the achievements sit close together as a
 * group rather than competing with the employment cards above them for attention.
 * The tile remains the right shape for a job, a qualification or a gap — each of
 * which is one record with fields. An achievement is a single sentence of prose,
 * and a sentence does not need a 12px box around it.
 *
 * The medal is decorative and hidden from assistive technology; the sentence beside
 * it is the content, and stands on its own without the ribbon.
 */
function dossierAchievements(values) {
  const items = Array.isArray(values) ? values.filter(Boolean) : [];
  if (!items.length) return null;
  const list = el('ul', 'ach-list');
  items.forEach(value => {
    const row = el('li', 'ach-row');
    const medal = el('span', 'ach-medal');
    medal.setAttribute('aria-hidden', 'true');
    row.appendChild(medal);
    row.appendChild(el('p', 'ach-text', String(value)));
    list.appendChild(row);
  });
  return list;
}

/* ------------------------------------------------------- dossier views ---- */
/*
 * One dossier, read differently for each kind of work.
 *
 * The switcher exists because a career can look thin to a site recruiter and
 * strong to an editor without anything being different about the person. A
 * former Marine who operates LV Switchers and now writes documentation has a
 * resume that leads with office work; to a FIFO recruiter that resume says
 * almost nothing, and it should not.
 *
 * Two rules this UI is built around:
 *
 *  - A view never invents. If the dossier has no equipment history, the FIFO
 *    view says so in its own words rather than borrowing the nearest-sounding
 *    office adjective. `whatItCannotShow` is rendered, not hidden, because a
 *    view that quietly padded itself would be worse than no view at all.
 *
 *  - An interpretation is always shown next to the original. The service record
 *    stays verbatim and the site vocabulary appears beside it, labelled as our
 *    reading, so the candidate can correct it.
 */

const dvEls = {};
let dvViews = [];
let dvActive = null;

function cacheDossierViewEls() {
  for (const id of ['dossier-views', 'dv-note', 'dv-tabs', 'dv-body']) {
    dvEls[id] = document.getElementById(id);
  }
}

function renderDossierViews(views, defaultView) {
  cacheDossierViewEls();
  if (!dvEls['dossier-views']) return;
  if (!Array.isArray(views) || !views.length) {
    dvEls['dossier-views'].hidden = true;
    return;
  }
  dvViews = views;

  const tabs = dvEls['dv-tabs'];
  const body = dvEls['dv-body'];
  if (!tabs || !body) return;
  tabs.replaceChildren();
  body.replaceChildren();

  views.forEach((v) => {
    const tab = el('button', 'dv-tab' + (v.empty ? ' is-empty' : ''), v.label);
    tab.type = 'button';
    tab.setAttribute('role', 'tab');
    tab.dataset.view = v.view;
    // A view with nothing in it is still offered — that is information — but it
    // is marked, so the count does not imply a fully populated view.
    tab.appendChild(el('span', 'dv-count', v.empty ? '—' : String(v.sectionCount)));
    tab.addEventListener('click', () => selectView(v.view));
    tabs.appendChild(tab);
  });

  const note = dvEls['dv-note'];
  if (note) {
    note.textContent =
      'One dossier, read differently for each kind of work. Nothing here is invented to '
      + 'fill a gap — a view with little to show says so.';
  }

  dvEls['dossier-views'].hidden = false;
  // Prefer the view the active track implies, so the first thing a FIFO
  // candidate sees is the FIFO framing rather than an arbitrary one.
  selectView(defaultView && dvViews.some((v) => v.view === defaultView) ? defaultView : null);
}

/**
 * One record from a dossier section, as a line of text.
 *
 * This was inline and was written for employment and nothing else: it read
 * `branch`, `role`, `unit`, `description` and `company`, joined them, and — when
 * every one of them was absent — fell through to `JSON.stringify(v)`.
 *
 * An education record has none of those keys. It has `degree`, `field`,
 * `institution` and `year`. So in any view that shows education it rendered as raw
 * JSON, in a list of otherwise well-formed lines, which reads as the parser having
 * failed when the parse was perfect. "Business and administration" is where it
 * showed worst, because `office` puts `education` first in its order and a broken
 * first line makes the whole section look wrong.
 *
 * Per-field rather than per-object, because the shape is a property of what the
 * record *is* and only the section knows that. Guessing from the keys present would
 * mean a military record that happened to carry an `institution` rendered as a
 * qualification.
 *
 * Nothing here is invented. Every part comes from a field the parser wrote, and a
 * record with none of the expected keys lists its own contents rather than being
 * summarised — an unrecognised shape should be visible, not tidied into a sentence
 * the source did not say.
 */
function formatRecord(field, v) {
  if (field === 'education') return educationLine(v);

  // Employment and military service, unchanged: this is the shape those sections
  // have always been rendered from and the wording is load-bearing.
  const who = [v.branch, v.role, v.unit].filter(Boolean).join(' · ');
  const line = [who, v.description || v.company].filter(Boolean).join(' — ');
  if (line) return line;

  // Anything else. A certification with an issuer, a qualification with a
  // credential — read the keys it actually has instead of dumping JSON at the
  // reader. Tried in the order a reader wants them.
  const parts = [];
  const named = ['credential', 'qualification', 'title', 'name']
    .filter((k) => typeof v[k] === 'string' && v[k].trim())
    .map((k) => v[k].trim());
  if (named.length) parts.push(named.join(' '));
  const org = v.organization || v.issuer || v.provider || v.institution;
  if (org) parts.push(String(org));
  const when = [v.date, v.year, v.until, v.expires].filter(Boolean).join(' – ');
  if (when) parts.push('(' + when + ')');
  if (parts.length) return parts.join(' — ');

  // Last resort: its own fields, named, so an unrecognised record is legible and
  // obviously a record rather than a sentence.
  const entries = Object.entries(v)
    .filter(([, val]) => val !== null && val !== undefined && val !== '' && typeof val !== 'object')
    .map(([k, val]) => k + ': ' + val);
  return entries.length ? entries.join(' · ') : '(empty record)';
}

/**
 * A qualification, as one line.
 *
 * Shared with the education block further down so the two renderings of one fact
 * cannot drift apart. They had already been written separately, which is how one of
 * them ended up correct and the other printing JSON.
 */
function educationParts(item) {
  if (!item || typeof item !== 'object') return null;
  const degree = [item.degree, item.field].filter(Boolean).join(' ');
  const institution = item.institution || '';
  // The institution is only appended when there is a qualification to put in front
  // of it. With only an institution, the old form produced "Only the school - Only
  // the school", which is the sort of thing a reader notices and stops trusting the
  // rest of the page over.
  const lead = degree || institution;
  const tail = (institution && degree) ? ' - ' + institution : '';
  const year = item.year ? ' (' + item.year + ')' : '';

  // The qualification is the headline and the institution and year sit under it,
  // which is how a reader of a CV expects the pair to be arranged — and it is what
  // lets education use the same card as employment. Every part is a field the
  // record actually carries: an absent degree leaves the headline blank rather than
  // borrowing the institution to fill it, because "University of X" presented as a
  // qualification is a claim the resume never made.
  return {
    headline: lead,
    detail: (tail + year).trim(),
    line: (lead + tail + year).trim(),
  };
}

function educationLine(item) {
  if (!item || typeof item !== 'object') return String(item == null ? '' : item);
  const parts = educationParts(item);
  return parts ? parts.line : '';
}

function selectView(viewId) {
  const body = dvEls['dv-body'];
  const tabs = dvEls['dv-tabs'];
  if (!body || !tabs) return;
  const v = dvViews.find((x) => x.view === viewId) || dvViews.find((x) => !x.empty) || dvViews[0];
  if (!v) return;
  dvActive = v.view;

  Array.from(tabs.children).forEach((t) => {
    const on = t.dataset.view === v.view;
    t.classList.toggle('is-active', on);
    t.setAttribute('aria-selected', on ? 'true' : 'false');
  });

  body.replaceChildren();

  const head = el('div', 'dv-viewhead');
  head.appendChild(el('p', 'dv-viewlabel', v.label));
  head.appendChild(el('p', 'dv-blurb', v.blurb));
  head.appendChild(el('p', 'dv-audience', 'Written for: ' + v.audience));
  body.appendChild(head);

  if (v.empty) {
    body.appendChild(el('p', 'dossier-muted',
      'This view has nothing to show from the dossier. That is a gap in what is recorded, '
      + 'not a judgement on you — tell Jobby in chat and it will write it in.'));
  }

  v.sections.forEach((s) => {
    const card = el('article', 'dv-section' + (s.lead ? ' is-lead' : ''));
    card.appendChild(el('h4', null, s.label));
    const list = el('ul', 'dossier-list');
    // Derived sections arrive as {items|text, derivedFrom} rather than a bare
    // value, so the shape is unwrapped here instead of being special-cased in
    // three places below.
    const raw = (s.value && typeof s.value === 'object' && !Array.isArray(s.value)
      && (s.value.items || s.value.text)) ? (s.value.items || [s.value.text])
      : (Array.isArray(s.value) ? s.value : [s.value]);
    raw.forEach((v2) => {
      if (v2 && typeof v2 === 'object') {
        list.appendChild(el('li', null, formatRecord(s.field, v2)));
      } else {
        list.appendChild(el('li', null, v2));
      }
    });
    card.appendChild(list);

    // Where this content came from. A view that read "open to rotations" out of
    // the summary has to say so, or the candidate cannot tell a recorded field
    // from our reading of a sentence — and cannot correct the one that is wrong.
    if (s.derivedFrom) {
      card.appendChild(el('p', 'dv-derived', 'Read ' + s.derivedFrom));
    }

    // The interpretation, always beside the original and always labelled.
    if (s.alsoShows && s.alsoShows.length) {
      const also = el('div', 'dv-also');
      also.appendChild(el('p', 'dv-also-label', 'Also readable as'));
      const ul = el('ul', 'dv-also-list');
      s.alsoShows.forEach((x) => ul.appendChild(el('li', null, x)));
      also.appendChild(ul);
      if (s.alsoShows.reason) also.appendChild(el('p', 'dv-also-reason', s.alsoShows.reason));
      card.appendChild(also);
    }
    body.appendChild(card);
  });

  // Rendered, not hidden. A view that quietly omitted its own gaps would read
  // as complete, and that is the failure this whole module is built to avoid.
  if (v.whatItCannotShow && v.whatItCannotShow.length) {
    const gaps = el('div', 'dv-gaps');
    gaps.appendChild(el('p', 'dv-gaps-label', 'This view cannot show'));
    const ul = el('ul', 'dossier-list');
    v.whatItCannotShow.forEach((g) => ul.appendChild(el('li', null, g)));
    gaps.appendChild(ul);
    body.appendChild(gaps);
  }

  if (v.note) body.appendChild(el('p', 'dv-footnote', v.note));
}

// "Lead Platform Engineer, Acme Systems" + "March 2021 - present"
function employmentLine(job) {
  const who = [job.title, job.company].filter(Boolean).join(', ');
  if (!who) return null;
  const dates = [job.start, job.end].filter(Boolean).join(' – ');
  if (!dates) return who;
  return who + ' · ' + dates;
}

function renderDossier(profile) {
  if (!dossierPanel || !dossierBody || !profile) return;
  dossierBody.replaceChildren();
  const grid = el('div', 'parsed-profile-grid dossier-grid');

  const identity = [];
  const name = profile.name || tn('Name not stated');
  identity.push(el('p', 'dossier-name', name));
  if (profile.current_title || profile.current_company) {
    identity.push(el('p', 'dossier-role',
      [profile.current_title, profile.current_company].filter(Boolean).join(' · ')));
  }
  if (profile.experience_years !== null && profile.experience_years !== undefined) {
    const bits = [profile.experience_years + ' yrs experience'];
    if (profile.seniority) bits.push(profile.seniority);
    identity.push(el('p', 'dossier-muted', bits.join(' · ')));
  }
  const contacts = [profile.location, profile.email, profile.phone].filter(Boolean);
  if (contacts.length) identity.push(el('p', 'dossier-muted', contacts.join(' · ')));
  const links = profile.links || {};
  const linkValues = [links.linkedin, links.github, links.portfolio, links.website]
    .concat(links.other || []).filter(Boolean);
  if (linkValues.length) identity.push(el('p', 'dossier-muted', linkValues.join(' · ')));
  identity.push(el('p', 'dossier-confidence',
    tn('Extraction confidence') + ': ' + confidenceLabel(profile.confidence)));
  const identityCard = dossierCard(tn('Identity'), identity);
  // Identity is the first thing in the dossier, alone, before anything else.
  //
  // It used to be the first card in a grid of seven, so the reader met their own
  // name and then had to scroll past a summary, a skills list, inferred job
  // fields and a set of target roles before reaching the employment history they
  // came for. The supporting cards are all real and all worth having — they are
  // also, by construction, the parts derived from the resume rather than the
  // parts the person is.
  //
  // So: identity, then employment, then the derived material. That is also the
  // order of trust. A name and a job held are things the resume stated; "job
  // fields" and "domain expertise" are this product's reading of them, and there
  // is no reason to ask a reader to weigh an inference before they have seen the
  // fact it was inferred from.
  if (identityCard) dossierBody.appendChild(identityCard);

  const summaryCard = dossierCard(tn('Summary'), [el('p', 'dossier-summary', profile.summary)]);
  if (summaryCard) grid.appendChild(summaryCard);

  const skillsCard = dossierCard(tn('Skills'), [dossierList(profile.skills, tn('None listed'))]);
  if (skillsCard) grid.appendChild(skillsCard);

  const fieldsCard = dossierCard(tn('Job fields'), [dossierList(profile.job_fields, tn('None inferred'))]);
  if (fieldsCard) grid.appendChild(fieldsCard);

  const expertiseCard = dossierCard(tn('Domain expertise'), [dossierList(profile.domain_expertise, null)]);
  if (expertiseCard) grid.appendChild(expertiseCard);

  const certsCard = dossierCard(tn('Certifications'), [dossierList(profile.certifications, tn('None listed'))]);
  if (certsCard) grid.appendChild(certsCard);

  const roles = Array.isArray(profile.target_roles) && profile.target_roles.length
    ? profile.target_roles
    : profile.roles_in_resume;
  const rolesCard = dossierCard(
    Array.isArray(profile.target_roles) && profile.target_roles.length
      ? tn('Suggested target roles')
      : tn('Roles named in the resume'),
    [dossierList(roles, tn('None listed'))]);
  if (rolesCard) grid.appendChild(rolesCard);

  // Employment gets full width: it carries the highlight bullets. It comes
  // directly after identity, and the derived cards above follow it — see the note
  // at the identity card for why the order is trust order rather than arbitrary.
  const jobs = Array.isArray(profile.employment) ? profile.employment.filter(Boolean) : [];
  if (jobs.length) {
    const wrap = el('div', 'dossier-timeline');
    jobs.forEach(job => {
      const entry = el('article', 'dossier-job');
      const line = employmentLine(job);
      if (line) entry.appendChild(el('h3', null, line));
      if (job.team_size) {
        entry.appendChild(el('p', 'dossier-muted', tn('Team size') + ': ' + job.team_size));
      }
      const highlights = Array.isArray(job.highlights) ? job.highlights.filter(Boolean) : [];
      if (highlights.length) appendList(entry, dossierList(highlights, null));
      wrap.appendChild(entry);
    });
    dossierBody.appendChild(el('h3', 'dossier-subhead', tn('Experience')));
    dossierBody.appendChild(wrap);
  }

  // The derived cards, now that the facts they were inferred from are above them.
  // Appended only if something landed in it — an empty grid would otherwise render
  // as a stray band of nothing.
  if (grid.children.length) dossierBody.appendChild(grid);

  // Education, and the sections below it, were plain lists while employment was a
  // run of cards, so the dossier's visual language stopped at the Experience
  // subhead. They are cards now, built by the same helper, from the same record.
  const education = Array.isArray(profile.education) ? profile.education.filter(Boolean) : [];
  // The same helper the dossier views use, for the same reason: two renderings of
  // one fact, written separately, is how one of them ends up correct and the other
  // printing JSON.
  const eduItems = education.map(educationLine).filter(Boolean);
  if (eduItems.length) {
    dossierBody.appendChild(el('h3', 'dossier-subhead', tn('Education')));
    const eduWrap = el('div', 'dossier-timeline');
    education.forEach(item => {
      const parts = educationParts(item);
      if (!parts || !parts.line) return;
      const card = el('article', 'dossier-entry');
      // Headline only when the record states a qualification. A record with an
      // institution and no degree still gets a card — the institution is simply
      // not promoted into the headline slot.
      if (parts.headline && parts.headline !== parts.detail) {
        card.appendChild(el('h3', null, parts.headline));
        if (parts.detail) card.appendChild(el('p', 'dossier-muted', parts.detail));
      } else {
        card.appendChild(el('h3', null, parts.line));
      }
      eduWrap.appendChild(card);
    });
    dossierBody.appendChild(eduWrap);
  }

  const achievements = Array.isArray(profile.achievements) ? profile.achievements.filter(Boolean) : [];
  if (achievements.length) {
    dossierBody.appendChild(el('h3', 'dossier-subhead', tn('Confirmed achievements')));
    dossierBody.appendChild(dossierAchievements(achievements));
  }

  // Present so the reader can see the limits of the extraction.
  const gaps = gapList(profile.not_stated);
  if (gaps.length) {
    dossierBody.appendChild(el('h3', 'dossier-subhead', tn('Not stated in resume')));
    dossierBody.appendChild(dossierEntryCards(gaps, 'is-gap'));
  }

  const flags = gapList(profile.verification_flags);
  if (flags.length) {
    dossierBody.appendChild(el('h3', 'dossier-subhead', tn('Flagged for verification')));
    dossierBody.appendChild(dossierEntryCards(flags, 'is-flag'));
  }

  dossierHeading.textContent = tn('Dossier for') + ' ' + name;
  dossierPanel.hidden = false;
  // The relay has already onboarded this dossier server-side, so the agent
  // panel can pick up the tracks, plan and change log without a page reload.
  if (typeof jobbyRefreshAfterDossier === 'function') jobbyRefreshAfterDossier(profile);
}

function renderDossierUnavailable(message) {
  if (!dossierPanel || !dossierBody) return;
  dossierBody.replaceChildren();
  dossierBody.appendChild(el('p', 'dossier-muted', message));
  dossierHeading.textContent = tn('Dossier unavailable');
  dossierPanel.hidden = false;
}

/* ------------------------------------------------- dossier build progress */
// Driven by the server's own stage, never by a client timer. A bar that advances
// on its own schedule eventually outruns the work and sits at 90% for a minute,
// which is the opposite of reassuring: the candidate would be watching a lie.
const progressBlock = document.getElementById('dossier-progress');
const progressStage = document.getElementById('dp-stage');
const progressCount = document.getElementById('dp-count');
const progressTrack = document.getElementById('dp-track');
const progressFill = document.getElementById('dp-fill');
const progressSteps = document.getElementById('dp-steps');
const progressNote = document.getElementById('dp-note');

// Mirrors the server's _DOSSIER_STAGES order, so the list can be drawn on the
// first paint before any stage has been reported. The server's wording
// overwrites these on every update, so the two cannot drift into contradicting
// each other on a live build.
const progressLabels = [
  'Read your details',
  'Pull the job history apart',
  'Work out what it supports',
  'Cross-check the dates',
  'Decide what it can claim',
  'Build your tracks and plan',
];
let progressStartedAt = Date.now();
let progressTotal = progressLabels.length;

function progressStepsTo(index, total) {
  if (!progressSteps) return;
  const want = total || progressLabels.length;
  while (progressSteps.children.length > want) {
    progressSteps.removeChild(progressSteps.lastElementChild);
  }
  while (progressSteps.children.length < want) {
    progressSteps.appendChild(el('li', 'dp-step'));
  }
  for (let i = 0; i < want; i++) {
    const step = progressSteps.children[i];
    const state = i < index - 1 ? 'done' : (i === index - 1 ? 'active' : 'todo');
    if (step.dataset.state === state) continue;
    step.dataset.state = state;
    const mark = state === 'done' ? '\u2713 ' : (state === 'active' ? '\u25b8 ' : '\u00b7 ');
    step.textContent = mark + (progressLabels[i] || '');
  }
}

/* The build-stage labels, translated by stage key.
 *
 * These live server-side in _DOSSIER_STAGES, which has one language, and a live
 * Spanish build reported "Reading your details out of the document" while the
 * summary it produced was in Spanish - so the progress bar was the only English
 * on a page that had been switched.
 *
 * Keyed by the stage name rather than by the label, because the key is stable
 * and machine-readable while the label is prose. Prose keys are what let an
 * ellipsis-vs-full-stop mismatch through unnoticed earlier.
 *
 * The server's label is still used for English and as a fallback, so a stage
 * added server-side and not yet translated shows its English label rather than
 * disappearing. */
const JOBBY_STAGE_LABELS = {
  identity:  { es: 'Lee tus datos del documento' },
  history:   { es: 'Desmonta tu historial laboral' },
  interpret: { es: 'Determina qué respalda ese historial' },
  reconcile: { es: 'Contrasta las fechas con el documento' },
  verify:    { es: 'Decide qué puede afirmar y qué no' },
  onboard:   { es: 'Construye tus rutas y tu plan' },
};

function stageLabel(progress) {
  if (!progress) return '';
  var entry = JOBBY_STAGE_LABELS[progress.stage];
  if (entry && window.JobbyI18n && window.JobbyI18n.isSpanish()) return entry.es;
  return progress.label || '';
}

function renderProgress(progress) {
  if (!progressBlock || !progress) return;
  progressBlock.hidden = false;
  const total = Number(progress.total) || progressTotal;
  const index = Math.min(Math.max(Number(progress.index) || 1, 1), total);
  progressTotal = total;

  const label = stageLabel(progress) || tn('Working');
  if (progressStage && progressStage.textContent !== label) {
    progressStage.textContent = label;
  }
  if (progressCount) progressCount.textContent = index + ' of ' + total;
  if (progressTrack) {
    progressTrack.setAttribute('aria-valuemax', String(total));
    progressTrack.setAttribute('aria-valuenow', String(index));
  }
  if (progressFill) {
    // Never 100% before the last stage lands. The final jump belongs to the real
    // render, so a slow final stage stays visibly unfinished rather than
    // pretending to be done.
    const pct = index >= total ? 100 : Math.round(((index - 0.35) / total) * 100);
    progressFill.style.width = Math.max(4, Math.min(pct, 97)) + '%';
  }
  progressStepsTo(index, total);

  if (progressNote) {
    const seconds = Math.round((Date.now() - progressStartedAt) / 1000);
    progressNote.textContent = seconds < 10
      ? 'Usually under a minute. The dossier fills in on its own \u2014 you can keep reading.'
      : seconds + ' seconds so far, still working. The dossier fills in on its own.';
  }
}

function showDossierPending() {
  if (!dossierPanel || !dossierBody) return;
  dossierBody.replaceChildren();
  progressStartedAt = Date.now();
  progressTotal = progressLabels.length;
  progressStepsTo(1, progressTotal);
  if (progressStage) progressStage.textContent = 'Starting';
  if (progressCount) progressCount.textContent = '0 of ' + progressTotal;
  if (progressFill) progressFill.style.width = '4%';
  if (progressTrack) {
    progressTrack.setAttribute('aria-valuemax', String(progressTotal));
    progressTrack.setAttribute('aria-valuenow', '0');
  }
  if (progressNote) {
    progressNote.textContent = 'Usually under a minute. The dossier fills in on its own \u2014 you can keep reading.';
  }
  if (progressBlock) progressBlock.hidden = false;
  dossierHeading.textContent = 'Building the candidate dossier';
  dossierPanel.hidden = false;
}

function hideDossierProgress() {
  if (progressBlock) progressBlock.hidden = true;
}


// dossierList returns null when there is nothing to show, so appending goes
// through this rather than relying on each call site re-checking.
function appendList(parent, list) {
  if (list) parent.appendChild(list);
}

function stopDossierPolling() {
  if (dossierTimer) {
    clearTimeout(dossierTimer);
    dossierTimer = null;
  }
}

/**
 * Fetch the dossier's views from the relay.
 *
 * Goes to /api/jobby/session rather than to this origin's own API, because the
 * views are computed on the relay where the dossier lives, and because this
 * server's session cookie is the same jobby_sid the relay resolves — so the
 * candidate sees their own views and nobody else's.
 *
 * Failure is silent by design: the dossier itself still renders, and a missing
 * view switcher is a smaller loss than an error over a panel that is otherwise
 * fine. It is a convenience surface, not the record.
 */
async function loadDossierViews() {
  try {
    const res = await fetch('/api/jobby/session', {
      headers: { Accept: 'application/json' },
      credentials: 'same-origin',
    });
    if (!res.ok) return;
    const s = await res.json().catch(() => ({}));
    if (!s.views) return;
    renderDossierViews(s.views, s.defaultView);
  } catch {
    /* the dossier is still there; the switcher is optional */
  }
}

// Also on page load, not only after an upload.
//
// The five readings of the dossier were reachable only as a side effect of
// uploading a file in *this* page load, because `loadDossierViews` was called from
// one place: the poll that watches an upload finish. So a candidate who had a
// dossier, refreshed, or arrived from the dashboard, saw the dossier panel with no
// view switcher on it at all — the session was returning all five views, complete
// with content, and nothing was asking for them.
//
// The same bug the resume profile panel had, in the panel above it: a record that
// exists being displayed only as a side effect of the act of creating it, so a
// refresh reads as data loss. Cost here was a whole feature that looked missing.
//
// The fetch is the same one the upload path makes and is already silent on failure,
// so this cannot make the page worse if the relay is down.
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', loadDossierViews);
} else {
  loadDossierViews();
}

function pollDossier(requestId) {
  stopDossierPolling();
  const tick = async () => {
    try {
      const response = await fetch(
        '/api/resume/dossier?request_id=' + encodeURIComponent(requestId));
      const body = await response.json().catch(() => ({}));
      if (body.status === 'done') {
        setStatus(tn('Dossier ready.'), 'success');
        // The bar is taken down only once the dossier is genuinely in hand.
        hideDossierProgress();
        showDossierActions();
        renderDossier(body.profile);
        // Views arrive with the dossier rather than from a second fetch.
        //
        // The page's session call lives in jobby.js, which loads after this file,
        // so reaching for it here would be a race. The poll response is already
        // the moment the dossier exists, so it is the right place to ask.
        loadDossierViews();
        return;
      }
      if (body.status === 'processing') {
        // Fed on every tick, including one that carries no progress block, so
        // a slow stage still refreshes its elapsed note rather than freezing at
        // whatever the last real stage left behind.
        renderProgress(body.progress);
        dossierTimer = setTimeout(tick, 1500);
        return;
      }
      setStatus(tn('Resume parsed. ') + (body.error || tn('Dossier unavailable.')), 'error');
      // A failed build takes the bar down too, or it would sit there forever.
      hideDossierProgress();
      renderDossierUnavailable(body.error || tn('The dossier could not be built.'));
    } catch (error) {
      // A dropped poll is not a failure; keep trying until the job expires.
      dossierTimer = setTimeout(tick, 2500);
    }
  };
  dossierTimer = setTimeout(tick, 1200);
}


['dragenter', 'dragover'].forEach(eventName => {
  dropZone.addEventListener(eventName, event => {
    event.preventDefault();
    dropArea.classList.add('drag-over');
  });
});
['dragleave', 'drop'].forEach(eventName => {
  dropZone.addEventListener(eventName, () => dropArea.classList.remove('drag-over'));
});
dropZone.addEventListener('drop', event => {
  event.preventDefault();
  const file = event.dataTransfer.files[0];
  if (file) parseResume(file);
});
dropArea.addEventListener('click', () => fileInput.click());
dropArea.addEventListener('keydown', event => {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    fileInput.click();
  }
});
fileInput.addEventListener('change', () => {
  parseResume(fileInput.files[0]);
  fileInput.value = '';
});

/* ------------------------------------------------------------- language ---- */
// The toggle restores the stored language on load, flips on click, and re-applies
// after anything that replaces a region's contents. That last part is the one
// that is easy to miss: a language switch cannot survive content rendered later
// in English, and the dossier, the tracks and the Google panel are all rendered
// after load.
(function wireLanguageToggle() {
  var I18N = window.JobbyI18n;
  var button = document.getElementById('lang-toggle');
  if (!I18N || !button) return;

  var TOGGLE_LABEL = { en: 'ES', es: 'EN' };
  var TOGGLE_TITLE = {
    en: 'Cambiar el idioma a espa&ntilde;ol',
    es: 'Switch the language to English',
  };

  function paintToggle(lang) {
    button.textContent = TOGGLE_LABEL[lang] || 'ES';
    button.setAttribute('lang', lang === 'es' ? 'en' : 'es');
    var title = (TOGGLE_TITLE[lang] || TOGGLE_TITLE.en).replace(/&ntilde;/g, 'ñ');
    button.setAttribute('aria-label', title);
    button.title = title;
  }

  function setLang(lang) {
    var applied = I18N.setLang(lang);
    paintToggle(applied);
    return applied;
  }

  button.addEventListener('click', function () {
    setLang(I18N.current() === 'es' ? 'en' : 'es');
  });

  // Anything rendered after a language switch asks to be re-rendered in it.
  document.addEventListener('jobby:lang', function () { paintToggle(I18N.current()); });

  setLang(I18N.getLang());
})();

// The language the server should write the dossier, resume and chat in. An
// English resume in Spanish mode still yields a Spanish dossier, which is the
// point of asking for a language at all.
function currentLang() {
  return (window.JobbyI18n && window.JobbyI18n.current()) || 'en';
}

// Translate and rename a string built at runtime.
function tn(text) {
  return (window.JobbyI18n && window.JobbyI18n.tn) ? window.JobbyI18n.tn(text) : text;
}

/* The download links exist before there is a dossier, and are only revealed once
 * there is one. The language is stamped onto the href rather than baked into it,
 * so switching to Spanish and then downloading gives a Spanish CV instead of an
 * English one - which is the whole reason the endpoint reads ?lang=. */
function showDossierActions() {
  var actions = document.getElementById('dossier-actions');
  if (actions) actions.hidden = false;
  stampDownloadLanguage();
}

function stampDownloadLanguage() {
  var lang = currentLang();
  var doc = document.getElementById('resume-download');
  var print = document.getElementById('resume-print');
  if (doc) {
    doc.href = '/api/resume/document?lang=' + encodeURIComponent(lang);
    doc.textContent = tn('Download your resume');
  }
  if (print) {
    print.href = '/api/resume/document?format=html&lang=' + encodeURIComponent(lang);
    print.textContent = tn('Print or save as PDF');
  }
}

document.addEventListener('jobby:lang', stampDownloadLanguage);

/* ------------------------------------------------- dossier string helpers ---- */
// The dossier stores machine keys in English - "low", "phone", "employment" -
// because the relay, the renderer and the page agent all read them. Translating
// them at the point of display is what lets a Spanish panel show Spanish without
// a migration or an audit of every consumer. The panel used to print the raw
// key, so an English word leaked into the Spanish dossier.

// Confidence: a key in, a word out.
const JOBBY_CONFIDENCE = {
  high: { en: 'High', es: 'Alta' },
  medium: { en: 'Medium', es: 'Media' },
  low: { en: 'Low', es: 'Baja' },
};

function confidenceLabel(value) {
  var key = String(value == null ? '' : value).trim().toLowerCase();
  var entry = JOBBY_CONFIDENCE[key];
  if (!entry) return key;
  return (window.JobbyI18n && window.JobbyI18n.isSpanish()) ? entry.es : entry.en;
}

// Gaps and verification flags, stored as English field names.
const JOBBY_GAP_LABELS = {
  phone: { en: 'phone', es: 'teléfono' },
  email: { en: 'email', es: 'correo electrónico' },
  location: { en: 'location', es: 'ubicación' },
  name: { en: 'name', es: 'nombre' },
  links: { en: 'links', es: 'enlaces' },
  summary: { en: 'summary', es: 'resumen' },
  skills: { en: 'skills', es: 'habilidades' },
  employment: { en: 'employment history', es: 'historial laboral' },
  education: { en: 'education', es: 'formación' },
  certifications: { en: 'certifications', es: 'certificaciones' },
  achievements: { en: 'achievements', es: 'logros' },
  experience_years: { en: 'years of experience', es: 'años de experiencia' },
  portfolio: { en: 'portfolio', es: 'portafolio' },
  current_company: { en: 'current employer', es: 'empleador actual' },
  current_title: { en: 'current role', es: 'puesto actual' },
};

function gapLabel(value) {
  var key = String(value == null ? '' : value).trim().toLowerCase();
  var entry = JOBBY_GAP_LABELS[key];
  if (entry) return (window.JobbyI18n && window.JobbyI18n.isSpanish()) ? entry.es : entry.en;
  // Not a known key: a sentence of prose the model wrote, so it passes through.
  return value;
}

function gapList(values) {
  if (!Array.isArray(values)) return [];
  return values.map(gapLabel);
}

// The years figure, with the unit in the reader's language. The number itself is
// the same in both; only the noun changes, and it has to agree with the noun in
// the sentence it appears in, which is why this is a string and not a number
// format.
function yearsLabel(years) {
  if (years == null || years === '') return '';
  if (window.JobbyI18n && window.JobbyI18n.isSpanish()) {
    return years + (Number(years) === 1 ? ' año de experiencia' : ' años de experiencia');
  }
  return years + (Number(years) === 1 ? ' yr experience' : ' yrs experience');
}
