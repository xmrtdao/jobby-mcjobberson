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
  if (identityCard) grid.appendChild(identityCard);

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

  dossierBody.appendChild(grid);

  // Employment gets full width: it carries the highlight bullets.
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

  const education = Array.isArray(profile.education) ? profile.education.filter(Boolean) : [];
  const eduItems = education.map(item => {
    const degree = [item.degree, item.field].filter(Boolean).join(' ');
    const tail = item.institution ? ' — ' + item.institution : '';
    const year = item.year ? ' (' + item.year + ')' : '';
    return ((degree || item.institution || '') + tail + year).trim();
  }).filter(Boolean);
  if (eduItems.length) {
    dossierBody.appendChild(el('h3', 'dossier-subhead', tn('Education')));
    appendList(dossierBody, dossierList(eduItems, null));
  }

  const achievements = Array.isArray(profile.achievements) ? profile.achievements.filter(Boolean) : [];
  if (achievements.length) {
    dossierBody.appendChild(el('h3', 'dossier-subhead', tn('Confirmed achievements')));
    appendList(dossierBody, dossierList(achievements, null));
  }

  // Present so the reader can see the limits of the extraction.
  const gaps = gapList(profile.not_stated);
  if (gaps.length) {
    dossierBody.appendChild(el('h3', 'dossier-subhead', tn('Not stated in resume')));
    appendList(dossierBody, dossierList(gaps, null));
  }

  const flags = gapList(profile.verification_flags);
  if (flags.length) {
    dossierBody.appendChild(el('h3', 'dossier-subhead', tn('Flagged for verification')));
    appendList(dossierBody, dossierList(flags, null));
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
