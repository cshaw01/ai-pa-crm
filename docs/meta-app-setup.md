# Meta App Setup — one-time runbook

This is a one-time setup you (Chiefpa admin) do in Meta Business Manager to
unlock the Messenger and Instagram connectors for all tenants. After this is
done, individual tenants just click "Connect Messenger" / "Connect Instagram"
in their dashboard and complete a Facebook Login popup — no code changes.

The code is already in place. It's gated by four env vars. When these are
populated per tenant, the Channels modal flips from "Not configured" to
"Connect" buttons.

---

## Part 1 — Register the Meta App

1. Go to <https://developers.facebook.com/apps> and click **Create App**.
2. App type: **Business**.
3. App name: `Chiefpa CRM` (or whatever you want). Contact email: your admin email.
4. Business account: pick the Business Manager you've set up for Chiefpa.
5. Create the app. You'll land on the App Dashboard.

### Capture these values

On the app's **Settings → Basic** page, note:
- **App ID** — public, starts with a number (e.g. `1234567890123456`)
- **App Secret** — click "Show" to reveal. Treat this like a password.

Both go into env vars `META_APP_ID` and `META_APP_SECRET` on each tenant's
docker-compose.

---

## Part 2 — Add products

From the left sidebar **Add products**, add:

1. **Webhooks**
2. **Messenger**
3. **Instagram** (the Graph API version, not the old Basic Display)

---

## Part 3 — Configure Webhooks

### 3a. Pick a Verify Token

Generate one and remember it — this is arbitrary, just has to match on both
sides. Something like:

```
openssl rand -hex 24
# → e.g. 4a7b8c9d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f
```

This becomes `META_VERIFY_TOKEN` in tenant env.

### 3b. Subscribe the webhook URL

For each tenant you want to connect:

- **Callback URL**: `https://<tenant>.chiefpa.com/api/webhook/meta`
- **Verify Token**: the one you just generated
- **Subscribe to**: `messages`, `messaging_postbacks`, `messaging_optins`

Click Verify. Meta will hit your URL with a GET; our code returns the
challenge if the verify token matches.

### 3c. Subscribe the Page to the app

In the **Messenger → Settings** → **Webhooks** section:
- Click **Add or Remove Pages**
- Grant access to the Page(s) you want to connect

(Our OAuth callback also does `POST /PAGE_ID/subscribed_apps` automatically
when a tenant connects, so this step is mostly belt-and-braces.)

---

## Part 4 — Configure Facebook Login

From **App Settings → Advanced** (or **Facebook Login for Business → Settings**):

- **Valid OAuth Redirect URIs**: add one entry per tenant subdomain:
  ```
  https://hvac.chiefpa.com/api/channels/meta/callback
  https://chiro.chiefpa.com/api/channels/meta/callback
  https://insurance.chiefpa.com/api/channels/meta/callback
  https://santhi.chiefpa.com/api/channels/meta/callback
  ```
  (add each new tenant subdomain here as you provision them)
- Leave everything else default.

The tenant's `META_REDIRECT_URI` env var must match its entry here exactly,
including the `https://` and trailing path.

---

## Part 5 — App Review (required for production)

The app starts in **Development mode**. You can only test with people listed
in the app's **Roles → Admins/Developers/Testers** section. For real customer
conversations you need App Review.

Submit for review from **App Review → Permissions and Features**. Request:

- `pages_messaging`
- `pages_manage_metadata`
- `pages_show_list`
- `instagram_basic`
- `instagram_manage_messages`
- `business_management`

Meta will ask for:
- **Privacy Policy URL** (public, must mention how you store messages)
- **Data Deletion URL** (or instructions)
- **Terms of Service URL**
- A **screencast** showing the integration end-to-end:
  1. Tenant clicks Connect in the dashboard
  2. Facebook Login popup, pick Page, grant permissions
  3. Inbound customer message appears in the Inbox
  4. Tenant approves the AI draft
  5. Customer receives the reply

Typical turnaround: 3–7 business days.

**Before review, you can already use the code** by listing test accounts under
Roles. They'll be able to send/receive via the app without Meta approval.

---

## Part 6 — Populate tenant env vars

Once you have the values, SSH to the host and update each tenant's
`docker-compose.yml`:

```yaml
services:
  crm:
    environment:
      - META_APP_ID=<app id>
      - META_APP_SECRET=<app secret>
      - META_VERIFY_TOKEN=<your verify token>
      - META_REDIRECT_URI=https://<tenant>.chiefpa.com/api/channels/meta/callback
```

Then restart just the CRM container:

```bash
cd /home/claude/tenants/<tenant>
sudo docker compose up -d crm
```

The Channels modal in the tenant's dashboard will now show **Connect**
buttons instead of "Not configured".

---

## Troubleshooting

**"verify token mismatch" when subscribing the webhook** — `META_VERIFY_TOKEN`
env on the tenant doesn't match what you typed into Meta's webhook form.

**"invalid state" on callback** — Either the state expired (>10 min) or
the tenant's `META_APP_SECRET` doesn't match. Re-check env.

**"no_pages" after Facebook Login** — The FB account that logged in has no
Pages attached to their Business Manager. Make sure the tenant's FB user is
an admin/editor of the Page they want to connect.

**Tokens marked `needs_reconnect`** — Meta rotated or revoked the token.
Open the Channels modal and click Reconnect. Common triggers: password
change on the FB account, the account uninstalled the app from Business
Manager, or the 60-day long-lived token naturally expired without activity.

**App Review rejected** — Usually the screencast was ambiguous about
consent. Re-record explicitly showing "this customer messaged us first,
the business is replying within the 24h window."

---

## Security notes

- **App Secret lives in env vars only**, never in git. The current
  docker-compose template takes it from `$META_APP_SECRET` on the host shell.
- **Per-tenant Page access tokens are Fernet-encrypted** at rest in each
  tenant's SQLite. The encryption key (`TENANT_ENCRYPTION_KEY`) is generated
  per tenant at provision time and lives in that tenant's compose env only.
- If you ever suspect the App Secret leaked, rotate it in Meta App Dashboard →
  Settings → Basic → Reset App Secret, then redeploy all tenants.
