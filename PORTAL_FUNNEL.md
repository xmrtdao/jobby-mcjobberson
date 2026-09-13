# Jobby McJobberson Portal Funnel

## One-line positioning

One platform to prepare, personalize, and launch your job search.

## Funnel promise

Jobby helps Joseph Andrew Lee move from a static resume to a prepared, targeted, trackable job-search system:

1. Prepare the canonical resume and contact package.
2. Source relevant opportunities.
3. Personalize outreach and application materials.
4. Track applications, responses, and next actions.

## Branded client flow

### Step 1: Start with the profile

New client sees:

- Upload or import current resume.
- Confirm name, email, phone, LinkedIn, and target roles.
- Select job-search tracks: contract consulting, temporary/contract, full-time, or ATS-assisted applications.
- Choose language and region variants, such as English/US, English/UK, or Spanish/Costa Rica.

Purpose:
- Create the canonical profile without scattering Joseph's details across tools.
- Keep the outbound identity consistent: Joseph Andrew Lee, not an agent persona.

### Step 2: Prepare the core package

New client sees:

- Resume/CV builder style preview.
- Cover letter builder preview.
- Contact block preview.
- ATS-readiness checklist.

Purpose:
- Make the first win visible: a polished application package.
- Mirror Jobseeker's "fill in the blanks, pick a template, download" simplicity, but keep Jobby's scope clear: preparation and orchestration, not generic resume SEO.

### Step 3: Source opportunities

New client sees:

- Track 1: high-engagement contract consulting outreach.
- Track 2: temporary and contract opportunities.
- Track 3: full-time employment opportunities.
- Track 4: ATS application automation, behind the page-agent boundary.

Purpose:
- Explain why the system has tracks.
- Prevent the user from thinking Jobby is only a scraper or only a resume builder.

### Step 4: Personalize and launch

New client sees:

- Recipient records are normalized, deduplicated, suppressed, and audited.
- Outreach uses the canonical hiring-manager email template from shared context.
- Sending cadence is handled by the fleet's campaign-scheduler/Resend services.
- ATS form work is handled by the canonical page-agent boundary.

Purpose:
- Show controlled automation.
- Make the user confident that Jobby prepares and coordinates, but does not fabricate contacts or bypass consent.

### Step 5: Track and review

New client sees:

- Applications tab.
- Outreach tab.
- Responses tab.
- Suppression/audit tab.
- Next-action list.

Purpose:
- Mirror Jobseeker's application tracking board, but with Jobby-specific auditability.

## Required portal sections

- Home / onboarding
- Resume / CV package
- Cover letter package
- Opportunities
- Applications
- Outreach
- Suppression and audit
- Pricing / access
- FAQ

## Pricing model

Use a simpler variant of Jobseeker's positioning:

"One price, all Jobby tracks, unlimited preparation cycles."

Recommended public pricing until market feedback:

- Starter: $0.99 for 14 days, then $19.99/month.
- Founder access: direct onboarding for first clients.
- Enterprise/recruiter package: later; not needed for MVP.

## Visual and copy direction

Brand: Joseph Andrew Lee / Jobby McJobberson.

Tone:
- Direct.
- Human.
- Slightly playful, but credible.
- No generic AI buzzwords.

Hero examples:

- "Your job search, prepped and ready to launch."
- "One platform for Joseph's next opportunity."
- "Prepare. Personalize. Track. Apply with control."

Feature card examples:

- "Resume / CV package"
- "Tailored cover letters"
- "Curated opportunity tracks"
- "Application command center"

## MVP implementation in this repo

This repo should gain a static portal prototype before any backend/database work.

Add:
- `portal/` directory with static HTML/CSS.
- `portal/index.html` as the branded landing/onboarding funnel.
- `portal/styles.css` for the Jobby visual system.
- `portal/README.md` documenting the funnel, copy, and limitations.

Do not add:
- Production auth.
- Payment collection.
- Scheduler/sender logic.
- ATS automation.
- Scraper implementation.
- New external services.

## Verification gates

Before calling this done:

- Static portal renders in a browser.
- Links are internal-only.
- Copy matches Jobby's actual scope.
- No fabricated contact data appears.
- Repo stays clean after generation.
- CI remains green after commit.
