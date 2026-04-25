---
title: "feat: chiefpa.com apex marketing site (Meta App Review + lead capture)"
type: feat
status: active
date: 2026-04-25
---

# chiefpa.com apex marketing site (Meta App Review + lead capture)

## Overview

Stand up a public marketing site at the **apex** `chiefpa.com` (and `www.chiefpa.com`) that serves two jobs at once:

1. **Unblock Meta App Review** — provide the public Privacy Policy, Terms of Service, and Data Deletion Instructions URLs that Meta requires before granting `pages_messaging`, `instagram_manage_messages`, etc. Today these don't exist; review can't be submitted.
2. **Convert service-business owners** — pitch what Chiefpa does, capture qualified leads via a short form (name, email, years in business, est. annual revenue, industry), and route each lead into the most-relevant existing tenant subdomain so they can try a real demo.

Hosted on **Cloudflare Pages** (greenfield — apex DNS doesn't exist yet) with a small **Pages Function** for form handling. Future tracking pixels (Meta Pixel, GA4) bolt on via the shared head partial.

---

## Problem Frame

Today only four tenant subdomains have DNS (`hvac`, `chiro`, `insurance`, `santhi` — all `chiefpa.com`). The apex resolves to nothing. There is no public surface that:

- Explains what Chiefpa is to a stranger
- Hosts the legal pages Meta App Review demands
- Captures inbound demand from cold traffic

The four tenants are real demo environments. The fastest credible "try it" experience for a prospect is dropping them into the demo whose vertical matches theirs. So the marketing site is also a **router**: it takes a self-declared industry and lands the visitor on the tenant subdomain that best showcases the product for them.

The Meta App Review angle is the load-bearing constraint. Without these three URLs being live and credible, the official Messenger / Instagram connectors stay in development mode (existing plan `docs/plans/2026-04-23-001-feat-official-meta-connectors-plan.md`). The marketing site is the gate.

---

## Requirements Trace

- **R1.** Apex `chiefpa.com` and `www.chiefpa.com` both serve the marketing site over HTTPS, with `www` redirecting to apex.
- **R2.** Three Meta-mandated public pages exist with content credibly meeting Meta App Review criteria: `/privacy`, `/terms`, `/data-deletion`.
- **R3.** A landing page explains the product to a service-business owner who has never heard of it (problem framed, solution shown, CTA to demo form).
- **R4.** A qualifier form collects name, email, years in business, estimated annual revenue (band), and industry; on submit, the visitor is redirected to the most-relevant existing tenant subdomain.
- **R5.** Form submissions are captured durably enough that a lead never silently disappears (notification to admin Telegram chat is the v1 channel).
- **R6.** The site supports adding tracking pixels (Meta Pixel, Google Analytics 4) later via a single edit point — no architecture re-work required when the time comes.
- **R7.** Form submissions are protected from bot spam without forcing a multi-step CAPTCHA flow on legitimate users.
- **R8.** Visual identity is consistent enough with the tenant SPA (`static/index.html`) that owners who clicked through to a demo subdomain feel like they're in the same product family.
- **R9.** Adding a new industry → tenant mapping (when a fifth tenant launches) is a single config edit, not an architectural change.

---

## Scope Boundaries

**Non-goals in v1:**

- A blog, case-study CMS, or markdown content pipeline — defer until SEO becomes a priority and a content library actually exists.
- A pricing calculator or tier comparison — pricing isn't stable enough to publish; CTA stays "talk to us / try the demo."
- Authenticated areas (customer login, paid tier signup) — out of scope until billing exists.
- Internationalisation — single English version. Singapore-targeted today.
- Live chat widget — belongs on tenant subdomains where there's an actual AI to talk to, not the marketing site.
- Persistent KV/DB storage of leads in v1 — Telegram notification is the durable record; revisit if volume warrants.
- A11y audit beyond reasonable defaults (semantic HTML, alt text, contrast) — defer formal WCAG conformance pass.

### Deferred to Follow-Up Work

- **Meta App Review screencast + submission** — operational follow-up after the legal pages go live (referenced in `docs/plans/2026-04-23-001-feat-official-meta-connectors-plan.md`). Plan unit U7 covers documentation; the actual Meta submission happens once we're ready to record.
- **Industry-specific landing pages** (`/for/hvac`, `/for/chiropractors`, …) — strong SEO play, but premature until the generic landing converts.

---

## Context & Research

### Relevant Code and Patterns

- `static/index.html`, `static/style.css`, `static/app.js` — tenant SPA. Tailwind **v3** via CDN (`https://cdn.tailwindcss.com`), vanilla JS, CSS custom properties for theming, blue primary `#2563eb` light / `#3b82f6` dark, slate grays for text, system font stack. Marketing site adopts the same palette and CDN approach for cross-product consistency and zero-build-step parity.
- `docker/setup-subdomain.sh` — existing Cloudflare DNS-via-API + Traefik route automation for tenant subdomains. The marketing site does NOT use this path — apex DNS goes via Cloudflare Pages's "custom domain" UI (or API) and bypasses Traefik entirely.
- `docs/meta-app-setup.md` — the existing runbook for Meta App registration. Lists the exact URLs Meta will request and the `pages_messaging` / `instagram_manage_messages` scopes that depend on them. The marketing site's `/privacy`, `/terms`, `/data-deletion` slot directly into this runbook's Part 5.
- Apex DNS state confirmed via Cloudflare API (zone `ea8af9ea109e9c45253fcd6ad62950e2`): no A/CNAME at `chiefpa.com` or `www.chiefpa.com`. Greenfield — no migration concerns.

### Institutional Learnings

- `docs/solutions/architecture-patterns/compounding-automation-via-learned-approval-patterns-2026-04-23.md` — the auto-approval pattern story (intent-classification, owner-authoritative promotion, refactor-as-prerequisite). Relevant as **product narrative** for the "How it works" page: this is the differentiating capability worth highlighting on the landing.

### External References

- Meta App Review requirements for messaging permissions — privacy policy must publicly disclose data collection, retention, third-party sharing, and user rights. Data Deletion URL accepts either an automated endpoint or public instructions; instructions are the simpler path. Authoritative source: <https://developers.facebook.com/docs/development/release/app-review> (consult at implementation time for current wording).
- Cloudflare Pages docs for apex domains, Pages Functions, and Turnstile integration — apex on Pages uses CNAME flattening (CF-native; no static IP needed).

---

## Key Technical Decisions

- **Cloudflare Pages over the existing FastAPI VPS** — keeps marketing-site uptime independent of tenant-container uptime, free at this scale, native fit for the existing Cloudflare-centric stack, trivial preview-deploy-per-PR workflow. No Traefik changes needed.
- **Plain HTML + Tailwind v3 CDN, no build step** — matches the tenant SPA exactly. 7-ish pages doesn't justify Astro's build pipeline; copy-paste plus `partials.js` (mirroring the SPA's vanilla-JS injection pattern) is faster to ship and easier for a future agent to maintain. Astro stays open as a migration path if the page count grows.
- **Single in-repo `site/` subdirectory, configured as the Pages build root** — keeps deployment atomic with the rest of the codebase, lets a single PR ship code + content + legal updates together, no second repo to coordinate.
- **Pages Function (`functions/api/lead.js`) for form submission** — the only piece of dynamic logic. Validates input, verifies a Cloudflare Turnstile token, posts a notification to the admin Telegram chat (existing infra used by the tenant containers — token already in Cloudflare env), and returns the redirect URL. No second host, no separate deploy.
- **Industry → subdomain mapping is a config object inside the function**, not a database. Adding a new tenant is a one-line edit + redeploy. v1 mappings: `hvac → hvac.chiefpa.com`, `chiropractor → chiro.chiefpa.com`, `insurance → insurance.chiefpa.com`, `wellness/salon/spa → santhi.chiefpa.com`, `other → /thank-you` (capture-only, with explicit "we'll provision one for you" message).
- **Cloudflare Turnstile over reCAPTCHA** — same vendor as the rest of the stack, frictionless (mostly invisible challenge), no Google dependency.
- **Tracking pixels deferred but architecturally provisioned** — single shared `<head>` partial (`_head.html` injected by `partials.js`) is the only place a future agent needs to touch to add Meta Pixel, GA4, or a tag manager. Initial deploy ships with the partial in place but no pixel IDs.
- **Telegram notification, no KV/DB persistence at v1** — same chat the tenant containers already notify; admin sees every lead in real time. Revisit if volume hides anything.
- **www → apex 301 redirect** via Cloudflare bulk redirect rules (or a tiny Worker), not via duplicating the Pages project on `www`. One canonical URL for SEO.

---

## Open Questions

### Resolved During Planning

- **Hosting model** → Cloudflare Pages (user-confirmed, with future-tracking-pixel constraint that Pages handles trivially via head partial).
- **Lead capture mechanism** → Cloudflare Pages Function with industry-based redirect to the relevant tenant subdomain (user-confirmed).
- **Tech stack** → plain HTML + Tailwind v3 CDN + small `partials.js`, matching the tenant SPA's no-build-step convention.
- **Apex vs separate marketing subdomain** → apex (user-stated requirement; "@ domain instead of a subdomain").
- **Whether to disrupt existing DNS** → no — apex is currently empty. No tenant rerouting required.

### Deferred to Implementation

- **Exact copy for the landing, how-it-works, industries, and legal pages** — drafting the words is part of unit execution, not planning. The legal pages should cross-reference Meta's then-current published requirements at the moment of writing rather than freezing language now.
- **OG default image visual** — design call during U6.
- **Whether the "other" industry branch shows a generic demo (e.g., HVAC) with a banner, or a thank-you-only page** — defer; default to thank-you-only and re-evaluate after first 50 leads.
- **Telegram chat ID / bot token reuse vs new dedicated bot** — implementation can reuse the existing tenant-notification bot if there's a clean admin chat, or provision a marketing-specific bot. Operational, not architectural.
- **Whether to also write `data-deletion` as an actual deletion endpoint (not just instructions)** — Meta accepts either; instructions are simpler. Defer the endpoint until a real deletion request comes in.

---

## Output Structure

```
site/
├── index.html              # Landing
├── how-it-works.html       # Product detail / "the auto-approval story"
├── industries.html         # Industry showcase + per-vertical hooks
├── demo.html               # Qualifier form
├── thank-you.html          # Fallback for "other" industry / post-submit hold page
├── privacy.html            # Privacy policy (Meta App Review required)
├── terms.html              # Terms of service (Meta App Review required)
├── data-deletion.html      # Data deletion instructions (Meta App Review required)
├── _head.html              # Shared head injection point (meta tags, tracking pixel slot)
├── _header.html            # Shared nav
├── _footer.html            # Shared footer w/ legal links + copyright
├── partials.js             # DOMContentLoaded → fetch + inject head/header/footer
├── styles.css              # Marketing-site-specific tweaks on top of Tailwind CDN
├── favicon.ico
├── og-default.png          # Default OG image (branded card)
├── sitemap.xml
├── robots.txt
└── functions/
    └── api/
        └── lead.js         # Cloudflare Pages Function: validate → notify → redirect
docs/
├── site-deploy.md          # NEW — CF Pages deploy + DNS + tracking + legal-page maintenance runbook
└── meta-app-setup.md       # MODIFIED — add the three URLs to Part 5
```

The implementer may flatten `_head.html`/`_header.html`/`_footer.html` into a single `_partials.html` if that reads better — the per-unit file lists are authoritative, not this tree.

---

## High-Level Technical Design

> *This illustrates the intended request/redirect flow and is directional guidance for review, not implementation specification.*

```mermaid
graph LR
  Visitor((Visitor)) -->|chiefpa.com| CF[Cloudflare Pages<br/>static HTML + JS]
  CF -->|/| Land[Landing]
  CF -->|/privacy /terms<br/>/data-deletion| Legal[Legal pages]
  CF -->|/demo| Form[Qualifier form<br/>+ Turnstile widget]
  Form -->|POST /api/lead| Fn[Pages Function]
  Fn -->|verify Turnstile<br/>validate fields| TG[Telegram admin chat]
  Fn -->|industry → mapping| Resp{redirect URL}
  Resp -->|hvac| H[hvac.chiefpa.com]
  Resp -->|chiropractor| C[chiro.chiefpa.com]
  Resp -->|insurance| I[insurance.chiefpa.com]
  Resp -->|wellness/spa/salon| S[santhi.chiefpa.com]
  Resp -->|other| TY[/thank-you]
```

Static-only request paths (everything except `/api/lead`) are served entirely by Cloudflare's edge — no compute. The single dynamic endpoint is `POST /api/lead`, which a Pages Function runs at the edge.

---

## Implementation Units

- [ ] U1. **Cloudflare Pages project + apex DNS**

**Goal:** `https://chiefpa.com` and `https://www.chiefpa.com` both serve a placeholder index from a Cloudflare Pages project, with HTTPS valid and `www → apex` redirect in place.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Create: `site/index.html` (placeholder — "Coming soon" stub at this unit; full landing lands in U3)
- Create: `docs/site-deploy.md` (runbook covering Pages project creation, build settings, custom-domain wiring, www-redirect rule)

**Approach:**
- Create a CF Pages project pointing at this repo's `main` branch with build root = `site/`.
- Add custom domains `chiefpa.com` and `www.chiefpa.com` in the Pages dashboard. CF auto-issues certificates via CNAME-flattening at apex.
- Use a Cloudflare bulk redirect rule (or a Page Rule) to send `www.chiefpa.com/*` → `https://chiefpa.com/$1` 301.
- Document the manual one-time steps (Pages project, custom domains, redirect rule) and the recurring deploy flow (push to `main` → auto-deploy).
- Reuse `CF_API_TOKEN` and `CF_ZONE_ID` from `CLAUDE.md` for any scripted DNS work.

**Patterns to follow:**
- DNS-via-API style from `docker/setup-subdomain.sh` (zone ID + token usage).

**Test scenarios:**
- Happy path: `curl -I https://chiefpa.com` returns 200 with valid TLS; the placeholder body is served.
- Happy path: `curl -I https://www.chiefpa.com` returns 301 Location: `https://chiefpa.com/`.
- Edge case: HTTP request `curl -I http://chiefpa.com` returns 301 to HTTPS (CF default).
- Test expectation: manual smoke test from outside the host network; no automated tests for this config-only unit.

**Verification:**
- Both apex and www resolve and answer 200/301 respectively from a non-CF network.
- The Pages dashboard shows the project as "Production" with both custom domains green.

---

- [ ] U2. **Site shell — partials, base styles, head injection points**

**Goal:** Establish the layout primitives every page reuses: head partial (with the future tracking-pixel slot), header nav, footer with legal links, brand-aligned base styles. After this unit, an empty content page only needs to write the `<main>` block.

**Requirements:** R6, R8

**Dependencies:** U1

**Files:**
- Create: `site/_head.html` (charset, viewport, Tailwind CDN script, base meta tags, tracking-pixel slot — initially commented-out placeholders for Meta Pixel + GA4)
- Create: `site/_header.html` (nav: home, how it works, industries, demo CTA)
- Create: `site/_footer.html` (links to /privacy, /terms, /data-deletion; copyright; small "made by humans + AI" line)
- Create: `site/partials.js` (on DOMContentLoaded, fetch and inject the three partials at marker `<div data-partial="…">` slots)
- Create: `site/styles.css` (CSS custom properties matching the SPA's blue primary `#2563eb` / dark `#3b82f6` and slate grays; marketing-friendly spacing tokens — more whitespace than the dense SPA)
- Modify: `site/index.html` (replace placeholder with the partial-driven shell so the rest of the unit lifecycle has something to look at)

**Approach:**
- The partial loader is intentionally vanilla JS (matches `static/app.js`). No bundler.
- Each page file starts with the partial markers and a single `<script src="/partials.js" defer>` reference.
- Tracking-pixel slot is a single HTML comment block with `<!-- tracking:meta-pixel --> ... <!-- tracking:ga4 -->` markers so a future change lands in exactly one file.
- Brand voice: confident, plain-English, service-business framing (not generic SaaS). Sentence-length copy, no jargon.

**Patterns to follow:**
- `static/index.html` for the Tailwind CDN load + custom CSS variable approach.
- `static/app.js` for vanilla-JS event-listener wiring, no framework.

**Test scenarios:**
- Happy path: loading `/` injects `_header.html` + `_footer.html` and the page renders correctly.
- Edge case: a partial 404s → page still renders main content; injection failure logs to console but doesn't break the page.
- Edge case: mobile viewport (≤640px) — header collapses to a hamburger or a wrap-friendly layout; nothing overflows horizontally.
- Test expectation: visual review across desktop + mobile viewports; no automated tests for static layout.

**Verification:**
- Every subsequent unit's pages render identical header/footer without copy-paste.
- View-source shows the head partial includes the dormant tracking-pixel markers.

---

- [ ] U3. **Marketing content pages — landing, how-it-works, industries**

**Goal:** Three pages of real product copy that explain Chiefpa to a service-business owner and channel them to the demo form.

**Requirements:** R3, R8

**Dependencies:** U2

**Files:**
- Modify: `site/index.html` (full landing: hero, three-step "how it works" teaser, four feature highlights, industry tiles, primary CTA → /demo)
- Create: `site/how-it-works.html` (deeper walkthrough: example inbound message → AI draft → owner approves → AI learns → next time auto-sends. Pull narrative from `docs/solutions/architecture-patterns/compounding-automation-via-learned-approval-patterns-2026-04-23.md`. Do not name actual customers.)
- Create: `site/industries.html` (cards for HVAC, chiropractor, insurance, wellness/spa, with one-liner showing what the AI handles for each. Each card CTA → /demo with `?industry=…` prefilled.)
- Modify: `site/styles.css` (any page-specific tweaks)

**Approach:**
- Hero pitch: one sentence on the customer outcome (faster replies, never miss a lead) plus one sentence on the differentiator (it learns your style, then automates).
- "How it works" copy leans on the auto-approval pattern as the believability anchor — it's a real shipped capability with a documented learning doc.
- Industry tiles in `industries.html` deep-link to `/demo?industry=hvac` (etc.) so the form pre-selects the right vertical.
- Avoid stock-photo SaaS clichés — prefer simple SVG diagrams or plain-text mock conversations.

**Patterns to follow:**
- Tone of `static/index.html` (functional, direct) but with marketing breathing room.

**Test scenarios:**
- Happy path: every internal link resolves (no 404s on /demo, /privacy, etc.).
- Happy path: industry-tile click on `/industries.html` lands on `/demo?industry=<value>` and the form's industry select is pre-set.
- Edge case: page renders correctly without JavaScript (partials don't load, but main content is still readable). Acceptable degradation: header/footer absent but body intact.
- Test expectation: visual + content review; linkcheck via a simple `curl` loop in the deploy runbook; no unit tests.

**Verification:**
- A reviewer who hasn't seen Chiefpa understands what it does after reading the landing.
- Each marketing page's CTA flows to /demo.

---

- [ ] U4. **Legal pages — privacy, terms, data deletion (Meta App Review compliant)**

**Goal:** Three live URLs that satisfy Meta App Review's public-policy requirements, written in plain English and credibly reflecting how Chiefpa actually handles data today.

**Requirements:** R2

**Dependencies:** U2

**Files:**
- Create: `site/privacy.html`
- Create: `site/terms.html`
- Create: `site/data-deletion.html`

**Approach:**
- Cross-reference Meta's then-current published App Review requirements at writing time (do not freeze the policy against today's wording).
- **Privacy must cover** at minimum: what we collect (customer messages routed via Messenger/Instagram/WhatsApp/Telegram; identifiers like phone, email, PSID, IGSID; contact metadata maintained by tenants), how we store it (per-tenant SQLite + GitHub-backed wiki repos under the `chiefpa-tenant-data` org; access tokens Fernet-encrypted at rest — see `docs/wiki-backup.md`), retention (until tenant cancels + 30-day grace), who can access (the tenant operator + Chiefpa support under contract), third-party sharing (Anthropic for the AI calls, GitHub for backups, Meta itself for delivery), user rights (request deletion via the tenant or via `privacy@chiefpa.com`).
- **Terms must cover**: service description, acceptable use (no spam, no illegal use), Chiefpa's right to suspend, limitation of liability, governing law (Singapore), how termination works.
- **Data Deletion** is a public instructions page (Meta accepts this). State: who to contact, what gets deleted (messages, wiki records, tokens), expected turnaround (e.g. 7 business days), what's retained for legal reasons (audit log of deletion itself).
- Each page carries a visible "Last updated: YYYY-MM-DD" line and a link to the GitHub commit that produced it (or just to the docs repo).
- Provision a real `privacy@chiefpa.com` mailbox (or alias) before publishing — broken contact info on these pages is the most common Meta App Review rejection cause.

**Patterns to follow:**
- Plain HTML + the partial-loaded shell from U2.
- Reference `docs/wiki-backup.md` for the actual backup architecture so the privacy claims match reality.

**Test scenarios:**
- Happy path: `/privacy`, `/terms`, `/data-deletion` each return 200 from public network.
- Happy path: each page contains the Meta-required sections (manual checklist).
- Happy path: footer links from any page resolve to all three legal pages.
- Edge case: the contact email on each page actually receives mail (test by sending one).
- Edge case: pages render correctly when partials.js fails (legal content is in the page body, not in a partial).
- Test expectation: content review against a Meta App Review checklist + manual mail-deliverability test for the privacy contact address.

**Verification:**
- Pasting all three URLs into Meta App Dashboard → Settings → Basic produces no validation errors.
- A non-technical reader can locate the deletion instructions within 10 seconds of landing on the homepage.

---

- [ ] U5. **Qualifier form + Pages Function (lead capture + industry routing)**

**Goal:** Visitor fills the five-field form, gets a Turnstile-verified submission accepted, the admin gets a Telegram notification, and the visitor lands on the most-relevant tenant subdomain (or /thank-you if no match).

**Requirements:** R4, R5, R7, R9

**Dependencies:** U2

**Files:**
- Create: `site/demo.html` (form: name, email, years_in_business, annual_revenue band, industry select; Turnstile widget; submit button)
- Create: `site/thank-you.html` (used when industry = "other" or as a fallback if redirect URL fails)
- Create: `site/functions/api/lead.js` (Cloudflare Pages Function: validates input, verifies Turnstile token via the CF siteverify endpoint, posts to Telegram bot API, returns redirect URL)
- Create: small client-side JS in `demo.html` (or a sibling file) that POSTs the form, reads the returned redirect URL, and navigates the browser to it
- Modify: `docs/site-deploy.md` (env var section: Turnstile site key + secret, Telegram bot token + chat ID, industry-mapping config location)

**Approach:**
- Form fields:
  - `name` — text, required, ≤80 chars.
  - `email` — required, validated against a basic regex on both client and server.
  - `years_in_business` — number, 0–100. Optional.
  - `annual_revenue` — band select: `<100k`, `100k-500k`, `500k-1M`, `1M+`, `prefer-not-say`. Required.
  - `industry` — select with the v1 allowlist: HVAC, chiropractor, insurance, wellness/spa/salon, real estate, restaurant, gym, beauty, other. Pre-fillable via `?industry=…` query param.
- Server-side mapping (in `lead.js`):
  ```
  hvac → hvac.chiefpa.com
  chiropractor → chiro.chiefpa.com
  insurance → insurance.chiefpa.com
  wellness | spa | salon | beauty → santhi.chiefpa.com
  other industries → /thank-you
  ```
  As a single editable object at the top of the function — adding the next tenant is one line.
- Anti-spam: Cloudflare Turnstile widget on the form (site key public, secret in CF env). Function rejects submissions without a valid token.
- Notification: Telegram bot message with the five fields + UA + IP (CF gives us `request.headers.get('cf-connecting-ip')`). Reuse the existing tenant-notification Telegram bot if there's a clean admin chat; otherwise provision a marketing-specific one (operational call).
- Response: JSON `{ ok: true, redirect: "https://hvac.chiefpa.com/" }`. Client-side JS does the navigation. Avoids 302-on-POST quirks and lets the client honour the user's expectation of a same-tab redirect.
- Failure modes:
  - Turnstile invalid → 400 with `{ ok: false, error: "verification" }`. Client shows "Please retry the verification."
  - Validation fails → 400 with field-level errors. Client highlights bad fields.
  - Telegram post fails → log to CF Pages console, but **still return ok + redirect URL** to the visitor — losing the visitor over a backend hiccup is worse than missing one notification (and we can recover the lead from CF logs).
  - Rate limit (>10 submissions per IP per 5 min) → 429.

**Patterns to follow:**
- Existing Telegram notification flow used by tenant containers (whichever bot/chat is used today — confirm at implementation).
- Form-validation parity between client (immediate feedback) and server (authoritative).

**Test scenarios:**
- Happy path: valid form with industry = "hvac" → response includes `redirect: "https://hvac.chiefpa.com/"` and Telegram chat receives a formatted message with all fields.
- Happy path: industry = "wellness" → redirect to `santhi.chiefpa.com`. Same for "spa", "salon", "beauty" (synonym matching).
- Happy path: industry = "other" or "real estate" → redirect to `/thank-you`.
- Happy path: `/demo?industry=chiropractor` pre-selects the industry option on page load.
- Edge case: missing required field (e.g., no email) → 400, field-level error rendered next to the input, no Telegram notification fires.
- Edge case: malformed email → 400.
- Edge case: invalid/missing Turnstile token → 400 with verification error.
- Edge case: Telegram bot API returns 5xx → visitor still gets the redirect URL; CF Pages console shows the backend error.
- Edge case: same IP submits 11+ times in 5 minutes → 429.
- Edge case: oversized payload (>4 KB) → 413.
- Edge case: industry value not in the allowlist (e.g., crafted POST) → server treats as "other" rather than crashing; defensive default.
- Integration: full submit happens entirely client→edge→admin, no tenant-VPS hop, latency well under 1s end-to-end.
- Test expectation: function tested via Wrangler local dev (`npx wrangler pages dev site/`) hitting a staging Telegram chat and a Turnstile test key; documented in the deploy runbook.

**Verification:**
- A test submission per industry produces the expected redirect target.
- The admin Telegram chat receives every test submission.
- A bot-style submission (no Turnstile token) is rejected.

---

- [ ] U6. **SEO basics + tracking-pixel scaffolding + favicon + OG**

**Goal:** Each page has unique title/description/OG meta. `sitemap.xml` and `robots.txt` exist and are correct. Favicon ships. Tracking pixel insertion is a one-file change when IDs are ready.

**Requirements:** R6

**Dependencies:** U2, U3, U4, U5

**Files:**
- Create: `site/sitemap.xml`
- Create: `site/robots.txt`
- Create: `site/favicon.ico`
- Create: `site/og-default.png` (simple branded card — logo + tagline)
- Modify: every content page from U3, U4, U5 to add page-specific `<title>`, `<meta name=description>`, `og:title`, `og:description`, `og:image`, `twitter:card`
- Modify: `site/_head.html` (the existing tracking-pixel slot — confirm marker placement; no real IDs yet)
- Modify: `docs/site-deploy.md` (add a "Wiring tracking pixels" section: where to paste Meta Pixel ID, where to paste GA4 measurement ID; gating note about preview vs production)

**Approach:**
- Use canonical URLs without trailing slashes; sitemap reflects the canonical form.
- `robots.txt` allows `*` and points at `/sitemap.xml`. Disallow nothing in v1.
- OG image is 1200×630 px PNG, branded but not pixel-perfect — iterate later.
- Tracking section in `_head.html` carries explicit comments showing where Meta Pixel base code goes and where GA4's `gtag` snippet goes — when the prod IDs arrive, the change is paste-only.

**Patterns to follow:**
- Standard OG/Twitter card meta-tag conventions.

**Test scenarios:**
- Happy path: each page's `<title>` is unique and human-readable.
- Happy path: `https://chiefpa.com/sitemap.xml` returns 200 and lists all canonical pages.
- Happy path: `https://chiefpa.com/robots.txt` returns 200 with sitemap reference.
- Happy path: pasting the homepage URL into a WhatsApp/Slack chat renders a non-default OG preview.
- Edge case: tracking pixel slot, when filled with a test Meta Pixel ID, fires correctly per Meta Pixel Helper extension.
- Test expectation: Lighthouse SEO audit ≥ 90; OG validator (developers.facebook.com/tools/debug) shows correct preview; tracking smoke test deferred until real IDs are wired.

**Verification:**
- A search-engine crawler can discover every public page from the sitemap.
- Adding a real Meta Pixel ID later requires editing only `_head.html`.

---

- [ ] U7. **Meta App Review wiring + deploy runbook**

**Goal:** The Meta App Review submission can proceed: the three required URLs are documented in the existing setup runbook, the deploy/maintenance flow is captured, and a future agent (or future-you) can update legal pages and tracking pixels without re-deriving the architecture.

**Requirements:** R2, R6, R9

**Dependencies:** U4, U6

**Files:**
- Modify: `docs/meta-app-setup.md` (Part 5 — populate the three URLs, add a sentence pointing to `site/privacy.html` etc. as the source of truth)
- Modify: `docs/site-deploy.md` (already started in U1; finalise covering: build/deploy, custom-domain wiring, www-redirect rule, Turnstile + Telegram env vars, tracking-pixel insertion, legal-page update workflow, Meta App Review re-submission steps and screencast checklist)
- Modify: `AGENTS.md` (add `site/` to the project shape directory listing with a one-line description; add `docs/site-deploy.md` to the docs list)
- Modify: `docs/deferred-work.md` (mark "marketing site / Meta legal pages" as shipped if listed; otherwise add a brief note linking to this plan)

**Approach:**
- Meta App Review screencast checklist lives in `docs/site-deploy.md` and references the existing screencast guidance in `docs/meta-app-setup.md` Part 5. Don't duplicate.
- Legal-page update workflow: edit the HTML, bump the "Last updated" date, push to main, confirm Pages auto-deploy succeeded, sanity-check the live URL. Document this end-to-end as a numbered list.
- The actual Meta App Review submission (filling out the dashboard form, recording the screencast) is operational work that happens after this plan's code lands — it's listed under Scope Boundaries → Deferred to Follow-Up Work, not as a code unit here.

**Patterns to follow:**
- `docs/meta-app-setup.md` voice and structure for any additions.
- `docs/wiki-backup.md` for runbook style.

**Test scenarios:**
- Happy path: `docs/meta-app-setup.md` Part 5 contains the three URLs verbatim and they each return 200.
- Happy path: `docs/site-deploy.md` walks an unfamiliar engineer from "fresh checkout" to "deployed site" without external knowledge.
- Edge case: a legal-page typo fix follows the documented workflow and lands in production within one cycle.
- Test expectation: documentation read-through; have a teammate or fresh-Claude run through the runbook to flag gaps.

**Verification:**
- An engineer who has never touched this can (a) modify a marketing page, (b) update a legal page and bump the date, (c) wire a new tracking pixel ID, and (d) submit Meta App Review — all from the runbooks alone.

---

## System-Wide Impact

- **Interaction graph:** None within the existing FastAPI codebase. The marketing site is fully decoupled — separate hosting, separate deploy, separate domain (apex). The only inter-system touchpoint is the *outbound* redirect from the Pages Function to existing tenant subdomains, which already exist and are unmodified.
- **Error propagation:** Form-submission failures are local to the Pages Function. A Telegram outage degrades to "lead missed in real time but visible in CF logs" — no cascading effect on tenant containers.
- **State lifecycle risks:** Lead capture is fire-and-forget at v1. If KV/DB persistence is added later, write idempotency must be considered. Out of scope today.
- **API surface parity:** The new `POST /api/lead` endpoint lives only on the apex. Tenant subdomains are unaffected.
- **Integration coverage:** Industry → subdomain mapping must stay in sync with actually-provisioned tenants. A new tenant launch requires a one-line edit to `lead.js`. Document this dependency in `docs/site-deploy.md`.
- **Unchanged invariants:** Tenant subdomains, their Traefik routes, their FastAPI containers, their auth flows, and the gateway-secret middleware are all untouched. The marketing site shares no compute or storage with them.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Meta App Review rejection due to ambiguous policy wording or unclear screencast | Cross-reference Meta's then-current public requirements at writing time (U4); pre-flight the screencast against the existing checklist in `docs/meta-app-setup.md`; have a non-engineer read the privacy policy before submission. |
| Privacy/Terms drift from actual data practice as the product evolves | Each legal page carries a "Last updated" date and is reviewed whenever a privacy-impacting change ships (new processor, new data field, retention change). Add this to the cleanup-plan loop. |
| Form spam from bots | Cloudflare Turnstile on the form + IP-based rate limit in the Pages Function. |
| Tenant demo environment on the redirect target is unimpressive (stale data, broken state) | Run a quick "demo readiness" pass on each tenant subdomain before driving real traffic — clean wiki, clean inbox, plausible recent activity. Pre-launch checklist in `docs/site-deploy.md`. |
| Industry mapping goes stale (new tenant launches but mapping not updated) | Mapping lives in one config object in `lead.js`. Add a line item to the tenant-provisioning runbook (`docker/setup-subdomain.sh` adjacent docs) to update the mapping when a new tenant goes live. |
| Apex DNS conflicts with future plans (e.g., a fifth tenant wants `chiefpa.com` for some reason) | Apex is reserved for the marketing site; tenants stay on subdomains. Document this convention in `AGENTS.md`. |
| Tracking pixel rollout leaks PII into the analytics platform | When wiring pixels, configure them with default-off PII transmission (Meta Pixel: do not send the email field; GA4: respect default consent). Note this in the tracking section of `docs/site-deploy.md`. |
| Privacy contact email (`privacy@chiefpa.com`) bounces because the mailbox doesn't exist | Provision the mailbox (or an alias) before U4 ships; verify deliverability with a test mail. |
| Cloudflare Pages free-tier limits hit (500 builds/month, request volume) | Free tier is generous for a marketing site. Monitor the Pages dashboard usage panel monthly. Upgrade is cheap if needed. |

---

## Documentation / Operational Notes

- **`docs/site-deploy.md`** is the single operational runbook produced by this plan. It must cover: Pages project + custom domains, www-redirect, Turnstile + Telegram env vars, industry mapping update, tracking-pixel wiring, legal-page maintenance, Meta App Review submission/re-submission.
- **`docs/meta-app-setup.md`** Part 5 needs the three URLs added (currently blank).
- **`AGENTS.md`** project-shape section gains the `site/` directory line.
- **`docs/deferred-work.md`** — if it lists a "marketing site / Meta legal pages" entry, mark shipped when this plan lands.
- **Mailbox provisioning** (`privacy@chiefpa.com`) is a precondition for U4. Operational, not code.
- **Demo-readiness pass on tenants** — operational, runs alongside U7 before driving real marketing traffic.

---

## Sources & References

- Existing plan: [docs/plans/2026-04-23-001-feat-official-meta-connectors-plan.md](2026-04-23-001-feat-official-meta-connectors-plan.md) — the Meta connectors plan that's blocked on these legal URLs going live.
- Existing runbook: [docs/meta-app-setup.md](../meta-app-setup.md) — Meta App Review requirements and process.
- Existing runbook: [docs/wiki-backup.md](../wiki-backup.md) — actual backup architecture, the source of truth for privacy-policy claims about retention and storage.
- Existing learning: [docs/solutions/architecture-patterns/compounding-automation-via-learned-approval-patterns-2026-04-23.md](../solutions/architecture-patterns/compounding-automation-via-learned-approval-patterns-2026-04-23.md) — narrative source for the "How it works" page.
- Tenant SPA reference: `static/index.html`, `static/style.css`, `static/app.js` — visual + JS conventions to mirror.
- Cloudflare Pages docs (apex domains, Pages Functions, Turnstile) — consult at implementation time.
- Cloudflare zone for `chiefpa.com`: `ea8af9ea109e9c45253fcd6ad62950e2` (creds in `CLAUDE.md`).
