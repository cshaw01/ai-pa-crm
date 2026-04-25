# chiefpa.com Marketing Site — Deploy & Maintenance Runbook

The marketing site at `chiefpa.com` (apex) is a static site hosted on **Cloudflare Pages**, with a single Pages Function for the demo-form lead capture. Source lives in this repo under `site/`.

This runbook is the operational source of truth — every recurring task (deploying changes, wiring a tracking pixel, updating a legal page, adding a new tenant to the industry mapping, submitting Meta App Review) is documented here.

> **Plan source:** `docs/plans/2026-04-25-001-feat-chiefpa-com-marketing-site-plan.md`

---

## Overview

```
site/
├── index.html, how-it-works.html, industries.html, demo.html, thank-you.html
├── privacy.html, terms.html, data-deletion.html        # Meta App Review legal pages
├── _head.html, _header.html, _footer.html              # shared partials
├── partials.js                                         # injects partials at DOMContentLoaded
├── styles.css                                          # marketing-site CSS on top of Tailwind CDN
├── favicon.ico, og-default.png, sitemap.xml, robots.txt
└── functions/
    └── api/
        └── lead.js                                     # Cloudflare Pages Function: form handler
```

The site is fully static except for `POST /api/lead`. There is no application server, no database, no Traefik routing, no tenant-VPS dependency for the marketing site. Only the apex `chiefpa.com` and `www.chiefpa.com` are served from Cloudflare Pages — the four tenant subdomains (`hvac`, `chiro`, `insurance`, `santhi`) continue to live on the existing Traefik + FastAPI stack as before.

---

## Initial Setup (one-time)

These steps are done once when the site first launches. After they are done, day-to-day work is just `git push origin main`.

### 1. Create the Cloudflare Pages project

1. Cloudflare dashboard → **Workers & Pages** → **Create** → **Pages** → **Connect to Git**.
2. Authorise GitHub access (one-time OAuth) and pick the `cshaw01/ai-pa-crm` repository.
3. Project name: `chiefpa-site` (this becomes the `*.pages.dev` preview URL).
4. Production branch: `main`.

### 2. Configure build settings

In the Pages project's **Build** settings:

| Setting | Value |
|---|---|
| Framework preset | None |
| Build command | *(leave empty — site is plain HTML, no build step)* |
| **Root directory** | **`site`** |
| Build output directory | `/` *(or leave empty — defaults to root directory)* |
| Environment variables | See section 5 below |

> **Critical:** the **Root directory must be `site`**, not blank. Cloudflare Pages auto-detects a `functions/` directory at the build *root*, not relative to the build output. If the root is blank, CF looks for `/functions/` at the repo root, finds nothing, ships only static assets, and silently drops `site/functions/api/lead.js` — leaving you with `404 /api/lead` and no way to add env vars (the dashboard will say "Variables cannot be added to a Worker that only has static assets"). If you see those symptoms, this setting is the cause.

Click **Save and Deploy**. The first deploy will publish whatever is on `main` to `https://chiefpa-site.pages.dev`. Confirm that loads before continuing — and also confirm `curl -I https://<project>.pages.dev/api/lead` returns `405` (not `404`), which proves the Function was bundled.

### 3. Add custom domains (apex + www)

In the Pages project → **Custom domains** → **Set up a custom domain**:

1. Add `chiefpa.com`. Cloudflare auto-creates a CNAME flattening record. HTTPS provisions in a minute or two.
2. Add `www.chiefpa.com`. Same flow.

Both domains should show **Active** with valid TLS.

> **DNS sanity check (from the host shell):**
>
> ```bash
> dig +short chiefpa.com @1.1.1.1
> dig +short www.chiefpa.com @1.1.1.1
> curl -I https://chiefpa.com         # expect 200
> curl -I https://www.chiefpa.com     # expect 301 once step 4 is done; 200 before that
> ```

### 4. www → apex 301 redirect rule

The marketing site has one canonical URL (apex). Send `www` to apex with a 301.

Cloudflare dashboard → **Rules** → **Redirect Rules** → **Create rule**:

| Field | Value |
|---|---|
| Rule name | `www-to-apex-marketing` |
| When incoming requests match | Hostname equals `www.chiefpa.com` |
| Then | URL redirect → Static |
| Target URL | `https://chiefpa.com${request.uri.path}` (concat) |
| Status code | `301` |
| Preserve query string | yes |

Deploy the rule. Re-test `curl -I https://www.chiefpa.com` — should now return `301 Location: https://chiefpa.com/`.

### 5. Provision env vars (Turnstile + Telegram)

The Pages Function at `functions/api/lead.js` needs three secrets. Add them in the Pages project → **Settings** → **Environment variables** → **Production** (and **Preview** if you want preview deploys to be fully functional):

| Variable | What it is | Where it comes from |
|---|---|---|
| `TURNSTILE_SECRET_KEY` | Server-side secret for verifying Turnstile tokens | Cloudflare → **Turnstile** → create a widget for `chiefpa.com` → copy the **Secret Key** |
| `TELEGRAM_BOT_TOKEN` | Bot token used to post lead notifications to the admin chat | BotFather (`@BotFather` on Telegram) — create a new bot or reuse an admin bot |
| `TELEGRAM_CHAT_ID` | Numeric chat ID where notifications land | After messaging the bot once, hit `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy the `chat.id` |

The corresponding Turnstile **Site Key** is public and lives in the form HTML — see section 7 (Adding/updating tracking pixels and the Turnstile widget).

### 6. Provision the privacy contact mailbox

Meta App Review will reject the privacy/data-deletion pages if the contact email bounces. Before publishing the legal pages publicly:

1. Create the mailbox or alias `privacy@chiefpa.com` (or whatever address the legal pages reference — check `site/privacy.html` and `site/data-deletion.html`).
2. Send a test email from an external address and confirm it lands.
3. Document who monitors it and the expected response SLA in your internal docs.

---

### 7. Designer TODOs (binary assets)

The agent ships everything except the two binary files that need a designer:

| File | Purpose | Spec |
|---|---|---|
| `site/og-default.png` | Default Open Graph preview when chiefpa.com pages are shared in WhatsApp / Slack / iMessage / etc. | 1200×630 PNG, brand blue background, "Chiefpa" wordmark + the tagline "AI personal assistant for service businesses" |
| `site/favicon.ico` | Legacy favicon for older browsers (modern browsers use `favicon.svg` which the agent already shipped) | 32×32 (or multi-size) ICO file generated from the same blue square + "C" mark used in `favicon.svg` |

Until these land, OG previews show no image (text-only) and Internet Explorer / very old browsers get no favicon. Both are cosmetic, not blocking. Drop the files into `site/` and push — no other changes needed; pages already reference both filenames in the right places.

---

## Deploying changes

Day-to-day deploys are automatic.

```bash
git checkout main
git pull
# ... edit files in site/ ...
git add site/
git commit -m "site: copy update"
git push origin main
```

Cloudflare Pages picks up the push and deploys within ~30 seconds. Watch the deploy in the Pages dashboard → **Deployments**.

**Preview deploys** — every branch and PR gets its own `<branch>.chiefpa-site.pages.dev` URL automatically. Use these for review before merging.

---

## Adding a new tenant to the industry mapping

When a new tenant launches (e.g., `gym.chiefpa.com`), the demo form needs to route relevant industries to it.

1. Open `site/functions/api/lead.js`.
2. Find the `INDUSTRY_TO_SUBDOMAIN` mapping near the top of the file.
3. Add the industry key(s) → subdomain mapping.
4. Commit, push, and the change is live within ~30 seconds.

Add the same line to your tenant-provisioning checklist (alongside `docker/setup-subdomain.sh`) so it's not forgotten the next time.

---

## Wiring tracking pixels (Meta Pixel, GA4)

The site is built with placeholder pixel slots in `site/_head.html`. To activate analytics:

### Meta Pixel

1. Meta Events Manager → create a new pixel for `chiefpa.com` if you don't have one. Copy the Pixel ID.
2. Open `site/_head.html`.
3. Find the `<!-- tracking:meta-pixel -->` block.
4. Paste Meta's standard base code, replacing `YOUR_PIXEL_ID` with the real ID.
5. Commit, push, deploy.
6. Verify with the Meta Pixel Helper browser extension on the live site.

### Google Analytics 4

1. GA4 admin → create a property for `chiefpa.com`. Copy the Measurement ID (`G-XXXXXXX`).
2. Open `site/_head.html`.
3. Find the `<!-- tracking:ga4 -->` block.
4. Paste the gtag snippet with the real Measurement ID.
5. Commit, push, deploy.
6. Verify in GA4 Realtime view.

> **PII reminder:** the form's `email` field must NOT be transmitted to either pixel. Default behaviour respects this; do not enable Meta's Advanced Matching or GA4's user-provided-data features without explicit consent UX in place.

---

## Legal page maintenance

`site/privacy.html`, `site/terms.html`, and `site/data-deletion.html` must stay accurate as the product evolves. Anytime any of the following changes, update them:

- A new third-party processor (e.g., a new AI provider, a new email service)
- A new data field collected
- A retention-policy change
- A change to who can access tenant data
- A new channel (e.g., adding TikTok, SMS) that touches user data

**Workflow for an update:**

1. Edit the relevant `.html` file.
2. Bump the visible "Last updated: YYYY-MM-DD" line at the top.
3. Commit with a message that names the substantive change (e.g., `site: privacy — disclose new SMS channel`).
4. Push → auto-deploy.
5. Sanity-check the live URL.
6. If the change is material, send a courtesy notice to active tenants.

---

## Meta App Review submission

The marketing site exists in part to unblock Meta App Review for the official Messenger and Instagram connectors. Once `site/privacy.html`, `site/terms.html`, and `site/data-deletion.html` are live and credible, follow `docs/meta-app-setup.md` Part 5.

**Pre-flight checklist before submitting:**

- [ ] All three legal URLs return 200 from a non-Cloudflare network
- [ ] Each page contains the Meta-required sections (data collected, retention, sharing, user rights, deletion process)
- [ ] `privacy@chiefpa.com` (or whichever address the pages list) actually receives mail
- [ ] At least one tenant subdomain has clean, plausible demo state for the screencast
- [ ] Screencast clearly shows: customer messages first → tenant approves AI draft within 24h window
- [ ] App ID, App Secret, Verify Token are populated per `docs/meta-app-setup.md` Part 6

If a review is rejected, the most common reason is screencast ambiguity about who initiated the conversation. Re-record showing an inbound customer message → owner approving inside the 24h window.

---

## Troubleshooting

**Deploy stuck "Initializing" in Cloudflare** — usually a CF-side hiccup. Wait 5 minutes; if still stuck, retry the deploy from the dashboard.

**Custom domain shows "Pending"** — DNS hasn't propagated. Check `dig +short chiefpa.com @1.1.1.1`. If the CNAME isn't visible, manually re-add the domain in the Pages project.

**Form returns 500** — Pages Function error. Cloudflare dashboard → **Pages** → project → **Functions** → **Real-time Logs** to see the stack trace. Common causes: missing env var, Telegram bot token revoked, Turnstile secret-key mismatch.

**`/api/lead` returns 404 / dashboard says "Variables cannot be added to a Worker that only has static assets"** — the Pages Function never made it into the deploy. The build config's **Root directory** is wrong. Fix: Settings → Build configuration → set Root directory to `site` (not blank), set Build output directory to `/` or empty, retry deployment. Verify with `curl -I https://chiefpa.com/api/lead` returning `405`. See section 2 above for the full correct config.

**Turnstile widget shows "Error" in the form** — site key in HTML doesn't match the configured widget, or the widget isn't configured for the site domain. Check Cloudflare → Turnstile → widget settings.

**Form submits but no Telegram notification** — verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` env vars; check that the bot has been added to the chat. Pages Function logs will show the actual Telegram API response.

**Industry routing sends to the wrong tenant** — `site/functions/api/lead.js` mapping is the source of truth. Pull, inspect, fix, push.
