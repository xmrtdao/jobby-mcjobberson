# AGENTS.md — working in this repository

## What this is

**Jobby McJobberson** — a personal job agent, served at
<https://jobbymcjobberson.com>. Part of [31 Harbor](https://github.com/xmrtdao/sea-hampton-house).

The product and the server are the same repository: `resume_server.py` serves
`index.html`, the SPA assets and the API. There is no separate frontend project.

---

## Serving is allowlisted — read this before adding any file

`resume_server.py` holds `_STATIC_ASSETS`, a **set of filenames**. A file that
exists on disk but is not in that set **is not served**. It returns 404, and
nothing errors.

This is the single most likely way to break something here:

- Adding `og/jobby-og.png` without listing it → the social card renders with no
  image, and every scraper reports a blank card with no error anywhere.
- Adding a favicon without listing it → a blank tab icon.
- Adding `robots.txt` without listing it → search crawlers get a 404 and treat
  the site as having no crawl policy, which is the opposite of the intent.

**Any new file served to a browser must be added to `_STATIC_ASSETS`.**

The set uses `|` union with `_DASHBOARD_ASSETS`, so it is additive — add the
filename, do not rewrite the block.

---

## How a page gets its assets

`index.html` and `dashboard.html` are entry points, and the server stamps
version queries onto the assets they reference. The reason is not tidiness:

- A cached `dashboard.html` paired with a stale `dashboard.js` is a silent
  failure.
- `jobby-chat-widget.js` **builds the chat DOM at runtime**. A cached widget
  against a fresh `jobby.js` — or the reverse — produces a chat that renders
  and then sends nothing, because the element ids stopped lining up.

**Never add an asset to an entry point without letting the server stamp it.**
A hand-written `?v=` in the HTML will drift from the real content.

---

## House style

- **Never overstate what ships.** Say a thing is live when it is live.
- Lead with what it does, then the specifics that make the claim checkable.
- Third person, present tense. "Jobby sends from your own address."

### Never invent — this is the product's own principle

It is the thing that distinguishes Jobby, and it binds this repository too:

- A gap is recorded as a gap. A rate floor is never guessed at.
- Never invent a user's skill, employer, rate or work authorisation.
- Never invent a metric, a testimonial, a client name or a user count. None
  exist, and inventing any of them is the fastest way to lose trust in the one
  product whose whole pitch is that it does not do this.

---

## Social and SEO

If the brand, headline or positioning changes, update these together — they drift
apart otherwise:

- `<title>`, `meta[name=description]`, `meta[name=keywords]`
- `og:title`, `og:description`, `og:image`, `og:image:width/height/alt`, `og:url`
- `twitter:card`, `twitter:title`, `twitter:description`, `twitter:image`
- `og/jobby-og.png` (1200×630 PNG)

**Absolute URLs in OG and Twitter tags.** Relative paths resolve against the
scraper's own base and produce a broken card.

**`og:image` must resolve publicly.** Verify with an unauthenticated request
that it returns `200` and `image/png`. Check it against the tunnel, not
`localhost` — the scraper is not on this machine.

The image is served through the same allowlist as everything else, so it only
appears after `_STATIC_ASSETS` lists it.

---

## Housekeeping

- `resume_server.log` is **1.3 MB** and growing. Do not commit it. It is
  gitignored; if it reappears in `git status`, something added it back.
- `crash_log.txt`, `debug_server.log`, `vite-dev.log`, `proxy_server.log` are
  empty or near-empty runtime artefacts. Leave them untracked.
- `test_resume.docx` / `.pdf` / `.txt` are fixtures. They are committed and
  some tests read them. Do not delete them as "test cruft" — `_test_pdf_parity`
  and `_test_resume_render` depend on them.
- The `_test_*.py` and `_check_*.py` files are **not** throwaway scratch. They
  are the test suite; several are the only coverage a behaviour has.
- `client_profile.json` is generated runtime state, not configuration.

---

## Before committing

- **New file served to a browser? It is in `_STATIC_ASSETS`.**
- No credential or token anywhere. `relay/.env` is a different repo and is
  gitignored.
- `resume_server.log` is not staged.
- The never-invent behaviour is intact — check that no placeholder invented a
  field, rate or figure.