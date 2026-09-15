const dropZone = document.getElementById('resume-drop-zone');
const dropArea = document.getElementById('resume-drop-area');
const fileInput = document.getElementById('resume-file');
const statusElement = document.getElementById('resume-status');
const onboardingOverlay = document.getElementById('onboarding-overlay');
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
    setStatus('Resume parsed. Profile is ready for review.', 'success');
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

function openOnboarding() {
  if (onboardingOverlay) onboardingOverlay.style.display = 'flex';
}

function nextStep(stepNum) {
  document.querySelectorAll('.onboarding-step').forEach(step => {
    step.classList.remove('active');
  });
  const next = document.querySelector(`.onboarding-step[data-step="${stepNum}"]`);
  if (!next) return;
  next.classList.add('active');
  if (stepNum === 4) updateSummary();
}

function updateSummary() {
  const summary = document.getElementById('summary-box');
  if (!summary) return;
  summary.replaceChildren();
  const values = [
    ['Name', document.getElementById('onboard-name')?.value],
    ['Roles', document.getElementById('onboard-roles')?.value],
    ['Resume', document.getElementById('onboard-resume')?.value],
    ['Sources', document.getElementById('onboard-sources')?.value],
  ];
  values.forEach(([label, value]) => {
    const labelNode = document.createElement('strong');
    labelNode.textContent = label + ': ';
    const valueNode = document.createTextNode(value || 'Not provided');
    summary.append(labelNode, valueNode, document.createElement('br'));
  });
}

function finishOnboarding() {
  const name = document.getElementById('onboard-name')?.value;
  window.alert(name ? `Onboarding complete. Jobby is now active for ${name}` : 'Onboarding complete.');
  if (onboardingOverlay) onboardingOverlay.style.display = 'none';
}

document.querySelectorAll('[data-open-onboarding]').forEach(button => {
  button.addEventListener('click', openOnboarding);
});
document.querySelectorAll('[data-onboarding-step]').forEach(button => {
  button.addEventListener('click', () => nextStep(Number(button.dataset.onboardingStep)));
});
document.querySelectorAll('[data-onboarding-finish]').forEach(button => {
  button.addEventListener('click', finishOnboarding);
});
if (onboardingOverlay) {
  onboardingOverlay.addEventListener('click', event => {
    if (event.target === onboardingOverlay) onboardingOverlay.style.display = 'none';
  });
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
