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
  setStatus('Parsing ' + file.name + '…', 'working');
  try {
    const form = new FormData();
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
      setStatus('Resume parsed. Building the dossier…', 'working');
      pollDossier(dossier.request_id);
    } else {
      setStatus('Resume parsed. Profile is ready for review.', 'success');
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
  const name = profile.name || 'Name not stated';
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
  identity.push(el('p', 'dossier-confidence', 'Extraction confidence: ' + (profile.confidence || 'low')));
  const identityCard = dossierCard('Identity', identity);
  if (identityCard) grid.appendChild(identityCard);

  const summaryCard = dossierCard('Summary', [el('p', 'dossier-summary', profile.summary)]);
  if (summaryCard) grid.appendChild(summaryCard);

  const skillsCard = dossierCard('Skills', [dossierList(profile.skills, 'None listed')]);
  if (skillsCard) grid.appendChild(skillsCard);

  const fieldsCard = dossierCard('Job fields', [dossierList(profile.job_fields, 'None inferred')]);
  if (fieldsCard) grid.appendChild(fieldsCard);

  const expertiseCard = dossierCard('Domain expertise', [dossierList(profile.domain_expertise, null)]);
  if (expertiseCard) grid.appendChild(expertiseCard);

  const certsCard = dossierCard('Certifications', [dossierList(profile.certifications, 'None listed')]);
  if (certsCard) grid.appendChild(certsCard);

  const roles = Array.isArray(profile.target_roles) && profile.target_roles.length
    ? profile.target_roles
    : profile.roles_in_resume;
  const rolesCard = dossierCard(
    Array.isArray(profile.target_roles) && profile.target_roles.length
      ? 'Suggested target roles'
      : 'Roles named in the resume',
    [dossierList(roles, 'None listed')]);
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
        entry.appendChild(el('p', 'dossier-muted', 'Team size: ' + job.team_size));
      }
      const highlights = Array.isArray(job.highlights) ? job.highlights.filter(Boolean) : [];
      if (highlights.length) appendList(entry, dossierList(highlights, null));
      wrap.appendChild(entry);
    });
    dossierBody.appendChild(el('h3', 'dossier-subhead', 'Experience'));
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
    dossierBody.appendChild(el('h3', 'dossier-subhead', 'Education'));
    appendList(dossierBody, dossierList(eduItems, null));
  }

  const achievements = Array.isArray(profile.achievements) ? profile.achievements.filter(Boolean) : [];
  if (achievements.length) {
    dossierBody.appendChild(el('h3', 'dossier-subhead', 'Confirmed achievements'));
    appendList(dossierBody, dossierList(achievements, null));
  }

  // Present so the reader can see the limits of the extraction.
  const gaps = Array.isArray(profile.not_stated) ? profile.not_stated.filter(Boolean) : [];
  if (gaps.length) {
    dossierBody.appendChild(el('h3', 'dossier-subhead', 'Not stated in resume'));
    appendList(dossierBody, dossierList(gaps, null));
  }

  const flags = Array.isArray(profile.verification_flags) ? profile.verification_flags.filter(Boolean) : [];
  if (flags.length) {
    dossierBody.appendChild(el('h3', 'dossier-subhead', 'Flagged for verification'));
    appendList(dossierBody, dossierList(flags, null));
  }

  dossierHeading.textContent = 'Dossier for ' + name;
  dossierPanel.hidden = false;
  // The relay has already onboarded this dossier server-side, so the agent
  // panel can pick up the tracks, plan and change log without a page reload.
  if (typeof jobbyRefreshAfterDossier === 'function') jobbyRefreshAfterDossier(profile);
}

function renderDossierUnavailable(message) {
  if (!dossierPanel || !dossierBody) return;
  dossierBody.replaceChildren();
  dossierBody.appendChild(el('p', 'dossier-muted', message));
  dossierHeading.textContent = 'Dossier unavailable';
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

function renderProgress(progress) {
  if (!progressBlock || !progress) return;
  progressBlock.hidden = false;
  const total = Number(progress.total) || progressTotal;
  const index = Math.min(Math.max(Number(progress.index) || 1, 1), total);
  progressTotal = total;

  if (progressStage && progressStage.textContent !== progress.label) {
    progressStage.textContent = progress.label || 'Working';
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
        setStatus('Dossier ready.', 'success');
        // The bar is taken down only once the dossier is genuinely in hand.
        hideDossierProgress();
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
      setStatus('Resume parsed. ' + (body.error || 'Dossier unavailable.'), 'error');
      // A failed build takes the bar down too, or it would sit there forever.
      hideDossierProgress();
      renderDossierUnavailable(body.error || 'The dossier could not be built.');
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
