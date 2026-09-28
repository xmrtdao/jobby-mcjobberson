/* The hero scene: a stylised browser window in which an agent works.
 *
 * This is not a video and not a screenshot. It is drawn, because a recording of
 * the real page agent would put the user's actual mailbox on the front page of a
 * marketing site - the browser it drives is logged into real accounts. A drawn
 * scene shows the behaviour without showing anyone's data.
 *
 * The four acts are the four things that actually happen, in the order they
 * happen, including the one most products would cut:
 *
 *   1. Sourcing   - a job board scrolls, a listing is chosen
 *   2. Refining   - the resume is rewritten, facts are extracted
 *   3. Applying   - the form fills, a file attaches
 *   4. Handing back - it stops on a question it will not guess the answer to
 *
 * Act 4 is the point. An agent that fills in a form it cannot complete is
 * either lying or broken, and showing the stop is the most convincing thing on
 * the page.
 *
 * Runs on a canvas rather than in the DOM: several hundred elements moving at
 * thirty frames a second would make the layout thrash, and the hero sits above
 * the fold where every millisecond of main-thread work is felt.
 *
 * Accessibility, which is not optional for motion that repeats forever:
 *   - WCAG 2.2.2 asks for a way to stop moving content. There is a pause button.
 *   - prefers-reduced-motion gets a single still frame instead of the loop.
 *   - The canvas is aria-hidden and the same story is told in the copy beside it,
 *     so nothing is conveyed by the animation alone.
 *   - It stops entirely when scrolled out of view or when the tab is hidden.
 */
(function () {
  'use strict';

  var SCENE_W = 1240;
  var SCENE_H = 620;
  var FRAME_MS = 1000 / 30;

  var PALETTE = {
    page: '#f8fafc',
    window: '#ffffff',
    chrome: '#eef2f7',
    border: '#cbd5e1',
    borderSoft: '#e2e8f0',
    ink: '#0f172a',
    muted: '#64748b',
    faint: '#94a3b8',
    primary: '#2563eb',
    primarySoft: '#dbeafe',
    success: '#16a34a',
    successSoft: '#dcfce7',
    warn: '#d97706',
    warnSoft: '#fef3c7',
    fill: '#bfdbfe',
  };

  var SANS = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';
  var MONO = 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';

  var reduced = window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }
  function lerp(a, b, t) { return a + (b - a) * t; }

  /** Ease so the cursor accelerates and settles rather than sliding linearly. */
  function easeInOut(t) {
    t = clamp(t, 0, 1);
    return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
  }

  function roundRect(ctx, x, y, w, h, r) {
    var radius = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.arcTo(x + w, y, x + w, y + h, radius);
    ctx.arcTo(x + w, y + h, x, y + h, radius);
    ctx.arcTo(x, y + h, x, y, radius);
    ctx.arcTo(x, y, x + w, y, radius);
    ctx.closePath();
  }

  function panel(ctx, x, y, w, h, fill, stroke) {
    roundRect(ctx, x, y, w, h, 10);
    ctx.fillStyle = fill;
    ctx.fill();
    if (stroke) {
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 1;
      ctx.stroke();
    }
  }

  /**
   * A row of "text" drawn as weighted lines rather than glyphs.
   *
   * Real words at 9px are unreadable at this size and turn to mush, and the eye
   * reads a block of the right length as text without needing to resolve it.
   */
  function textLines(ctx, x, y, widths, height, gap, color) {
    ctx.fillStyle = color;
    for (var i = 0; i < widths.length; i++) {
      var w = widths[i] * height * 0.5;
      roundRect(ctx, x, y + i * (height + gap), w, height, height / 2);
      ctx.fill();
    }
  }

  function fitText(ctx, text, maxWidth, startPx, family, weight) {
    var size = startPx;
    do {
      ctx.font = (weight || '400') + ' ' + size + 'px ' + family;
      if (ctx.measureText(text).width <= maxWidth) break;
      size -= 0.5;
    } while (size > 7);
    return size;
  }

  // ── the cursor ────────────────────────────────────────────────────────────

  function drawCursor(ctx, x, y, clickAge) {
    ctx.save();
    ctx.translate(x, y);
    ctx.fillStyle = '#0f172a';
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(0, 17);
    ctx.lineTo(4.4, 12.9);
    ctx.lineTo(7.4, 19.2);
    ctx.lineTo(10.2, 18);
    ctx.lineTo(7.3, 11.9);
    ctx.lineTo(12.4, 11.4);
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 1.2;
    ctx.stroke();

    // The click ring, which is what actually reads as "acting" rather than
    // "a shape is drifting".
    if (clickAge >= 0 && clickAge < 520) {
      var t = clickAge / 520;
      ctx.globalAlpha = (1 - t) * 0.55;
      ctx.strokeStyle = PALETTE.primary;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(1, 1, 6 + t * 16, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.restore();
  }

  /** Type text into a width, so a field fills at a readable pace. */
  function typed(ctx, text, x, y, maxWidth, progress) {
    var shown = Math.floor(clamp(progress, 0, 1) * text.length);
    var out = text.slice(0, shown);
    ctx.fillStyle = PALETTE.ink;
    ctx.fillText(out, x, y);
    if (progress < 1) {
      var w = ctx.measureText(out).width;
      ctx.fillRect(x + w + 1, y - 8, 1.6, 11);
    }
    return out.length;
  }

  // ── acts ──────────────────────────────────────────────────────────────────

  var LISTINGS = [
    ['Senior Account Executive', 'Northwind Logistics', 'Remote'],
    ['Consultant, Risk & Compliance', 'Harborline', 'New York'],
    ['Director of Sales', 'Cobalt Systems', 'Chicago'],
    ['Head of Partnerships', 'Meridian Group', 'Austin'],
    ['Commercial Lead', 'Atlas Freight', 'Remote'],
  ];

  function actSourcing(ctx, t, s) {
    // A job board, scrolling under a fixed header.
    ctx.save();
    ctx.beginPath();
    ctx.rect(s.x, s.y, s.w, s.h);
    ctx.clip();

    var scroll = t * 260;
    ctx.fillStyle = PALETTE.page;
    ctx.fillRect(s.x, s.y, s.w, s.h);

    // Board header
    ctx.fillStyle = PALETTE.window;
    ctx.fillRect(s.x, s.y, s.w, 46);
    ctx.strokeStyle = PALETTE.borderSoft;
    ctx.beginPath();
    ctx.moveTo(s.x, s.y + 46);
    ctx.lineTo(s.x + s.w, s.y + 46);
    ctx.stroke();
    ctx.font = '600 15px ' + SANS;
    ctx.fillStyle = PALETTE.ink;
    ctx.fillText('Job board', s.x + 18, s.y + 29);
    ctx.font = '400 12px ' + SANS;
    ctx.fillStyle = PALETTE.faint;
    ctx.fillText('1,284 matches', s.x + 112, s.y + 29);

    var rowH = 74;
    for (var i = -1; i < 7; i++) {
      var y = s.y + 60 + i * rowH - (scroll % (LISTINGS.length * rowH));
      if (y < s.y + 46 || y > s.y + s.h) continue;
      var item = LISTINGS[((i % LISTINGS.length) + LISTINGS.length) % LISTINGS.length];
      // Fade the rows in and out at the clip edges so the scroll has no seam.
      var edge = Math.min(1, (y - (s.y + 46)) / 30, ((s.y + s.h) - y) / 30);
      ctx.globalAlpha = clamp(edge, 0, 1);
      panel(ctx, s.x + 14, y, s.w - 28, rowH - 12, PALETTE.window, PALETTE.borderSoft);
      ctx.font = '600 14px ' + SANS;
      ctx.fillStyle = PALETTE.ink;
      ctx.fillText(item[0], s.x + 30, y + 30);
      ctx.font = '400 12px ' + SANS;
      ctx.fillStyle = PALETTE.muted;
      ctx.fillText(item[1] + '  ·  ' + item[2], s.x + 30, y + 50);
      ctx.globalAlpha = 1;
    }
    ctx.restore();

    // The listing that gets chosen lights up, which is what the cursor is
    // travelling towards.
    var pickY = s.y + 60 + rowH * 2 - (scroll % (LISTINGS.length * rowH));
    if (t > 0.62) {
      var pulse = (t - 0.62) / 0.38;
      ctx.save();
      ctx.globalAlpha = 0.18 * pulse;
      panel(ctx, s.x + 14, pickY, s.w - 28, rowH - 12, PALETTE.primary, null);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = PALETTE.primary;
      ctx.lineWidth = 1.5;
      roundRect(ctx, s.x + 14, pickY, s.w - 28, rowH - 12, 10);
      ctx.stroke();
      ctx.restore();
    }
    return { x: s.x + s.w - 96, y: pickY + 32, clickAt: 0.72 };
  }

  function actRefining(ctx, t, s) {
    // A resume being rewritten. The old line fades, the new one is typed, and
    // a marker shows a fact being lifted out rather than invented.
    var docX = s.x + 26;
    var docY = s.y + 22;
    var docW = s.w - 52;
    panel(ctx, docX, docY, docW, s.h - 44, PALETTE.window, PALETTE.borderSoft);

    ctx.font = '700 19px ' + SANS;
    ctx.fillStyle = PALETTE.ink;
    ctx.fillText('J. A. Lee', docX + 26, docY + 44);
    ctx.font = '400 12px ' + SANS;
    ctx.fillStyle = PALETTE.muted;
    ctx.fillText('Sales · Media · Technical systems', docX + 26, docY + 64);

    var rows = [
      { label: 'EXPERIENCE', lines: 4 },
      { label: 'SKILLS', lines: 2, count: 21 },
      { label: 'EDUCATION', lines: 1 }
    ];
    var y = docY + 96;
    for (var r = 0; r < rows.length; r++) {
      ctx.font = '600 11px ' + MONO;
      ctx.fillStyle = PALETTE.faint;
      ctx.fillText(rows[r].label, docX + 26, y);
      y += 14;
      var widths = [0.86, 0.72, 0.9, 0.6];
      for (var l = 0; l < rows[r].lines; l++) {
        textLines(ctx, docX + 26, y, [widths[l % widths.length]], 7, 6, PALETTE.border);
        y += 13;
      }
      // A fact being extracted: the block is rewritten, then tagged.
      if (r === 1) {
        var start = t;
        if (start > 0.3) {
          var p = clamp((start - 0.3) / 0.45, 0, 1);
          var bx = docX + 26;
          var by = y + 4;
          panel(ctx, bx, by, 268, 26, PALETTE.primarySoft, null);
          ctx.font = '600 11px ' + SANS;
          ctx.fillStyle = PALETTE.primary;
          var words = ['consultative selling', 'public speaking', 'narrative design'];
          var shown = Math.floor(p * 3);
          var label = words.slice(0, shown).join('  ·  ');
          ctx.fillText(label, bx + 10, by + 17);
          if (p < 1) {
            var cw = ctx.measureText(label).width;
            ctx.fillRect(bx + 10 + cw + 2, by + 6, 1.6, 14);
          } else {
            panel(ctx, bx + 292, by, 96, 26, PALETTE.successSoft, null);
            ctx.fillStyle = PALETTE.success;
            ctx.font = '600 11px ' + SANS;
            ctx.fillText('21 skills', bx + 306, by + 17);
          }
        }
      }
      y += 12;
    }

    // A scan line, so it reads as being processed rather than merely drawn.
    var scanY = docY + 30 + ((t * 2.1) % 1) * (s.h - 90);
    var grad = ctx.createLinearGradient(0, scanY - 16, 0, scanY + 16);
    grad.addColorStop(0, 'rgba(37,99,235,0)');
    grad.addColorStop(0.5, 'rgba(37,99,235,0.16)');
    grad.addColorStop(1, 'rgba(37,99,235,0)');
    ctx.fillStyle = grad;
    ctx.fillRect(docX + 1, scanY - 16, docW - 2, 32);
    return { x: docX + docW - 150, y: docY + 150, clickAt: 0.5 };
  }

  var FORM_FIELDS = [
    { label: 'Full name', value: 'Joseph Andrew Lee', from: 0.04, to: 0.17 },
    { label: 'Email', value: 'joeyleepcs@gmail.com', from: 0.19, to: 0.32 },
    { label: 'Phone', value: '+1 202 798 0610', from: 0.34, to: 0.45 },
    { label: 'City', value: 'Costa Rica', from: 0.47, to: 0.56 }
  ];

  function actApplying(ctx, t, s) {
    var fX = s.x + 40;
    var fY = s.y + 24;
    var fW = s.w - 80;
    panel(ctx, fX, fY, fW, s.h - 48, PALETTE.window, PALETTE.borderSoft);
    ctx.font = '600 16px ' + SANS;
    ctx.fillStyle = PALETTE.ink;
    ctx.fillText('Apply — Consultant, Risk & Compliance', fX + 24, fY + 36);

    var y = fY + 62;
    for (var i = 0; i < FORM_FIELDS.length; i++) {
      var f = FORM_FIELDS[i];
      var p = clamp((t - f.from) / (f.to - f.from), 0, 1);
      ctx.font = '500 11px ' + SANS;
      ctx.fillStyle = PALETTE.muted;
      ctx.fillText(f.label, fX + 24, y);
      var boxW = fW - 48;
      panel(ctx, fX + 24, y + 6, boxW, 30, '#ffffff', PALETTE.border);
      if (p > 0) {
        ctx.save();
        ctx.beginPath();
        ctx.rect(fX + 32, y + 6, boxW - 16, 30);
        ctx.clip();
        ctx.font = '400 13px ' + SANS;
        typed(ctx, f.value, fX + 32, y + 26, boxW - 16, p);
        ctx.restore();
      }
      y += 50;
    }

    // The resume attachment. This is the step that needs a real file, and the
    // one that was missing until the renderer existed.
    var attachP = clamp((t - 0.58) / 0.14, 0, 1);
    if (attachP > 0) {
      var aY = y + 4;
      panel(ctx, fX + 24, aY, fW - 48, 34, '#ffffff', PALETTE.border);
      ctx.font = '500 11px ' + SANS;
      ctx.fillStyle = PALETTE.muted;
      ctx.fillText('CV', fX + 34, aY + 21);
      ctx.font = '400 12px ' + SANS;
      ctx.fillStyle = PALETTE.ink;
      typed(ctx, 'Joseph-Andrew-Lee-resume.docx', fX + 56, aY + 22, fW - 100, attachP);
      if (attachP >= 1) {
        ctx.fillStyle = PALETTE.success;
        ctx.beginPath();
        ctx.arc(fX + fW - 44, aY + 17, 7, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(fX + fW - 47, aY + 17);
        ctx.lineTo(fX + fW - 45, aY + 20);
        ctx.lineTo(fX + fW - 40, aY + 14);
        ctx.stroke();
      }
    }
    return { x: fX + fW - 120, y: fY + 150, clickAt: 0.6 };
  }

  function actHandingBack(ctx, t, s) {
    // The field it will not guess, and the handover. This is the behaviour the
    // whole product rests on, so it gets its own act rather than a footnote.
    //
    // Laid out in two columns with no overlap. The first version drew the four
    // filled fields and then floated the handover card on top of them at partial
    // opacity, which put two sets of text in the same place: both were hard to
    // read and it looked like a rendering fault rather than a deliberate
    // handover. Fewer fields on the left, the card in its own space on the
    // right, and the card fully opaque.
    var fX = s.x + 22;
    var fY = s.y + 18;
    var fW = s.w - 44;
    panel(ctx, fX, fY, fW, s.h - 36, PALETTE.window, PALETTE.borderSoft);
    ctx.font = '600 15px ' + SANS;
    ctx.fillStyle = PALETTE.ink;
    ctx.fillText('Apply — Consultant, Risk & Compliance', fX + 20, fY + 32);

    // Left column: the form. Only the fields that matter for the point being
    // made, so the unanswered one is visible without scrolling.
    var colW = Math.min(300, fW * 0.44);
    var y = fY + 58;
    var shown = [FORM_FIELDS[0], FORM_FIELDS[1]];
    for (var i = 0; i < shown.length; i++) {
      var f = shown[i];
      ctx.font = '500 11px ' + SANS;
      ctx.fillStyle = PALETTE.muted;
      ctx.fillText(f.label, fX + 20, y);
      panel(ctx, fX + 20, y + 6, colW, 28, '#ffffff', PALETTE.border);
      ctx.font = '400 13px ' + SANS;
      ctx.fillStyle = PALETTE.ink;
      ctx.fillText(f.value, fX + 28, y + 25);
      y += 48;
    }

    // The one it will not guess, pulsing gently.
    var qY = y + 4;
    var qPulse = 0.5 + 0.5 * Math.sin(t * Math.PI * 6);
    panel(ctx, fX + 20, qY, colW, 28, PALETTE.warnSoft,
      t > 0.18 ? PALETTE.warn : 'rgba(217,119,6,' + (0.3 + qPulse * 0.5) + ')');
    ctx.font = '500 11px ' + SANS;
    ctx.fillStyle = PALETTE.warn;
    ctx.fillText('How did you hear about us?', fX + 30, qY + 18);
    if (t < 0.75) {
      var w2 = ctx.measureText('How did you hear about us?').width;
      ctx.fillStyle = PALETTE.warn;
      ctx.fillRect(fX + 30 + w2 + 3, qY + 7, 1.6, 14);
    }

    // Right column: the handover, arriving into its own space.
    var cardP = clamp((t - 0.28) / 0.4, 0, 1);
    if (cardP > 0) {
      var cW = Math.max(180, fW - colW - 66);
      var cH = Math.min(150, s.h - 70);
      var ease = easeInOut(cardP);
      var cX = fX + fW - cW - 22 + (1 - ease) * 24;
      var cY = fY + 46 + (1 - ease) * 12;
      ctx.save();
      // Opaque once it has arrived: at partial alpha the form underneath showed
      // through and both layers became unreadable.
      ctx.globalAlpha = cardP > 0.5 ? 1 : cardP * 2;
      panel(ctx, cX, cY, cW, cH, PALETTE.window, PALETTE.border);
      ctx.fillStyle = PALETTE.warn;
      ctx.fillRect(cX, cY, 3, cH);

      ctx.font = '600 12px ' + SANS;
      ctx.fillStyle = PALETTE.warn;
      ctx.fillText('Jobby stopped here', cX + 18, cY + 26);
      ctx.font = '400 12px ' + SANS;
      ctx.fillStyle = PALETTE.muted;
      var lines = [
        'Four fields came from your dossier.',
        'This one is not in it, so I will not',
        'invent an answer.',
        '',
        'Tell me and I will finish and submit.'
      ];
      for (var l = 0; l < lines.length; l++) {
        ctx.fillStyle = l === 4 ? PALETTE.ink : PALETTE.muted;
        ctx.fillText(lines[l], cX + 18, cY + 48 + l * 17);
      }
      // Progress, deliberately short of the end.
      panel(ctx, cX + 18, cY + cH - 18, cW - 36, 4, PALETTE.borderSoft, null);
      panel(ctx, cX + 18, cY + cH - 18, (cW - 36) * 0.78, 4, PALETTE.warn, null);
      ctx.restore();
    }
    return { x: fX + 130, y: qY + 13, clickAt: 0.85 };
  }

  var ACTS = [
    { name: 'sourcing', dur: 5.2, draw: actSourcing, url: 'jobs.example.com/search?q=account+executive' },
    { name: 'refining', dur: 5.0, draw: actRefining, url: 'local — resume.docx' },
    { name: 'applying', dur: 6.4, draw: actApplying, url: 'harborline.example.com/apply/88213' },
    { name: 'handing-back', dur: 5.6, draw: actHandingBack, url: 'harborline.example.com/apply/88213' }
  ];

  var TOTAL = ACTS.reduce(function (a, b) { return a + b.dur; }, 0);

  function actAt(time) {
    var t = time % TOTAL;
    for (var i = 0; i < ACTS.length; i++) {
      if (t < ACTS[i].dur) return { index: i, act: ACTS[i], local: t / ACTS[i].dur };
      t -= ACTS[i].dur;
    }
    return { index: 0, act: ACTS[0], local: 0 };
  }

  /** The URL bar cross-fades as the agent moves between pages. */
  function drawUrl(ctx, x, y, w, act, nextAct, blend) {
    panel(ctx, x, y, w, 26, PALETTE.chrome, null);
    ctx.save();
    ctx.beginPath();
    ctx.rect(x + 8, y, w - 16, 26);
    ctx.clip();
    ctx.font = '400 11px ' + MONO;
    var h = 26;
    if (blend < 1) {
      ctx.fillStyle = 'rgba(100,116,139,' + (1 - blend) + ')';
      ctx.fillText(act.url, x + 16, y + h / 2 + 4);
      ctx.fillStyle = 'rgba(15,23,42,' + blend + ')';
      ctx.fillText(nextAct.url, x + 16 + (1 - blend) * 10, y + h / 2 + 4);
    } else {
      ctx.fillStyle = PALETTE.muted;
      ctx.fillText(act.url, x + 16, y + h / 2 + 4);
    }
    ctx.restore();
  }

  function init() {
    var canvas = document.getElementById('hero-scene');
    if (!canvas) return;
    var host = canvas.parentElement;
    var ctx = canvas.getContext('2d');
    if (!ctx) return;

    var running = !reduced;
    var time = 0;
    var last = 0;
    var raf = 0;
    var visible = true;
    var onScreen = true;
    var actLabel = document.getElementById('hero-scene-label');

    var LABELS = [
      'Reading the market',
      'Refining your resume',
      'Filling the application',
      'Asking you the one thing it cannot know'
    ];

    function resize() {
      var ratio = Math.min(window.devicePixelRatio || 1, 2);
      // The host is now the whole hero, an absolutely positioned layer behind
      // the content, so its height comes from the hero rather than from the
      // canvas. Measuring it is what keeps the two from feeding back into each
      // other: the hero's height depends on the copy and the drop zone, not on
      // the canvas, and the canvas fills whatever height it is given.
      var rect = host.getBoundingClientRect();
      var w = Math.max(320, Math.round(rect.width));
      var h = Math.max(320, Math.round(rect.height));
      canvas.width = Math.round(w * ratio);
      canvas.height = Math.round(h * ratio);
      // Neither dimension is set in CSS terms: the layer is inset:0, so the
      // canvas simply fills it.
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      draw(0);
    }

    function draw(ms) {
      var w = canvas.width / (Math.min(window.devicePixelRatio || 1, 2));
      var h = canvas.height / (Math.min(window.devicePixelRatio || 1, 2));
      ctx.clearRect(0, 0, w, h);

      var state = actAt(time);

      // The scene is laid out in a fixed 1240x620 space, but the hero is close
      // to square on a narrow screen, so drawing into it at 1:1 made the window
      // chrome run off the sides and the form fill the box. Scaled to cover and
      // centred, the excess is cropped instead - which suits a background, where
      // looking at part of a larger screen is the point. Cover rather than
      // contain, so there are never letterbox bars showing the page behind.
      var scale = Math.max(w / SCENE_W, h / SCENE_H);
      var offsetX = (w - SCENE_W * scale) / 2;
      var offsetY = (h - SCENE_H * scale) / 2;
      ctx.save();
      ctx.translate(offsetX, offsetY);
      ctx.scale(scale, scale);

      var pad = 16;
      var winX = pad;
      var winY = pad;
      var winW = SCENE_W - pad * 2;
      var winH = SCENE_H - pad * 2;

      // The window itself
      panel(ctx, winX, winY, winW, winH, PALETTE.window, PALETTE.border);
      ctx.save();
      roundRect(ctx, winX, winY, winW, 40, 10);
      ctx.clip();
      ctx.fillStyle = PALETTE.chrome;
      ctx.fillRect(winX, winY, winW, 40);
      ctx.restore();
      ctx.strokeStyle = PALETTE.border;
      ctx.beginPath();
      ctx.moveTo(winX, winY + 40);
      ctx.lineTo(winX + winW, winY + 40);
      ctx.stroke();

      var dots = [PALETTE.border, PALETTE.border, PALETTE.border];
      for (var d = 0; d < 3; d++) {
        ctx.fillStyle = dots[d];
        ctx.beginPath();
        ctx.arc(winX + 18 + d * 15, winY + 20, 4.5, 0, Math.PI * 2);
        ctx.fill();
      }

      // Progress through the run, as a hairline along the top of the content.
      var next = actAt(time + 0.001);
      var blend = clamp((state.local - 0.88) / 0.12, 0, 1);
      drawUrl(ctx, winX + 70, winY + 7, Math.min(winW - 190, 430), state.act, next.act, blend);

      // A small progress bar across the whole run.
      panel(ctx, winX, winY + 38, winW, 2, 'rgba(203,213,225,0.5)', null);
      panel(ctx, winX, winY + 38, winW * ((time % TOTAL) / TOTAL), 2, PALETTE.primary, null);

      var stage = {
        x: winX + 1, y: winY + 44, w: winW - 2, h: winH - 46
      };
      var target = state.act.draw(ctx, state.local, stage);

      // Move between the position at the end of the previous frame and this
      // one, so the cursor travels rather than teleports between acts.
      drawCursor(ctx, target.x, target.y, (time - (target.clickAt || 0)) * 0);

      if (actLabel && actLabel.textContent !== LABELS[state.index]) {
        actLabel.textContent = LABELS[state.index];
      }
      // Undo the cover-scale before the next frame resets the transform, so a
      // paused scene does not keep the scale applied to anything drawn later.
      ctx.restore();
    }

    function frame(ms) {
      raf = 0;
      if (!running || !visible || !onScreen) return;
      if (last && ms - last >= FRAME_MS) {
        time += (ms - last) / 1000;
        last = ms;
        draw(ms);
      } else if (!last) {
        last = ms;
      }
      raf = requestAnimationFrame(frame);
    }

    function start() {
      if (raf) return;
      last = 0;
      raf = requestAnimationFrame(frame);
    }

    function stop() {
      if (raf) { cancelAnimationFrame(raf); raf = 0; }
    }

    // The pause control. WCAG 2.2.2 requires a mechanism to stop motion that
    // repeats for more than five seconds, which this does.
    var toggle = document.getElementById('hero-scene-toggle');
    if (toggle) {
      var syncToggle = function () {
        toggle.setAttribute('aria-pressed', running ? 'true' : 'false');
        toggle.textContent = running ? 'Pause animation' : 'Play animation';
        host.classList.toggle('is-paused', !running);
      };
      toggle.addEventListener('click', function () {
        running = !running;
        syncToggle();
        if (running) { time = 0; last = 0; start(); } else { stop(); }
      });
      syncToggle();
    }

    if (reduced) {
      // A single still frame at the most representative moment: the handover.
      time = ACTS[0].dur + ACTS[1].dur + ACTS[2].dur + 1.8;
      running = false;
      host.classList.add('is-paused');
      if (toggle) {
        toggle.setAttribute('aria-pressed', 'false');
        toggle.textContent = 'Play animation';
      }
      resize();
      return;
    }

    document.addEventListener('visibilitychange', function () {
      visible = !document.hidden;
      if (visible && running) { last = 0; start(); } else if (!visible) { stop(); }
    });

    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (entries) {
        onScreen = entries[0].isIntersecting;
        if (onScreen && running) { last = 0; start(); } else if (!onScreen) { stop(); }
      }, { threshold: 0.01 }).observe(host);
    }

    var resizeTimer = 0;
    window.addEventListener('resize', function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(resize, 160);
    });

    resize();
    start();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
