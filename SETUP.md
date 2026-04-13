# AI-PA CRM — Setup Guide

Follow these steps to spin up a new instance of this project for any business.
Steps 1–3 are manual. Steps 4–5 are AI-guided — paste the prompts into Claude Code and it will handle the rest.

---

## 1. Copy the project

```bash
cp -r ai-pa-crm /path/to/new-business-name
cd /path/to/new-business-name
```

---

## 2. Create config.json

```bash
cp config.example.json config.json
```

`config.json` is gitignored and will never be committed. All credentials live here only.

---

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

## 4. Run the configuration setup prompt

Open Claude Code in the project directory and paste this prompt. Claude will ask you for each credential, explain where to find it, and write it directly into `config.json`.

```
Please set up config.json for this new AI-PA CRM instance.

Walk me through each required value one section at a time. For each value:
- Tell me what it is
- Tell me exactly where/how to get it if I don't already have it
- Wait for me to provide it
- Write it into config.json before moving to the next section

Sections to complete in order:
1. Business details (name, timezone)
2. Database (host, password)
3. Claude CLI path (confirm the binary exists on this machine)
4. Telegram bot token
5. Telegram group chat ID
6. Telegram topic IDs (external and internal)
7. Telegram owner user ID

For Telegram items, provide step-by-step instructions using @BotFather and @userinfobot as needed.
Once all values are filled in, confirm config.json is complete and valid JSON.
```

---

## 5. Run the wiki + demo data setup prompt

Once config is done, paste this prompt. Claude will interview you about the business, then build the wiki, seed realistic contacts, populate the inbox with demo messages, and configure the dashboard for the industry. Fill in the placeholders first.

```
This project is being set up for a new business. Before doing anything, ask me the following questions one at a time and wait for my answer before continuing:

1. What industry or type of business is this? (e.g. F&B, law firm, e-commerce, real estate, beauty salon, logistics)
2. What is the business name and which city/country?
3. Who are the typical customers — consumers, businesses, or both?
4. What are the main things customers contact you about? (e.g. bookings, quotes, complaints, orders, enquiries)
5. What channels do customers reach you on? (WhatsApp, Instagram DMs, email, Telegram, walk-in)
6. How many mock clients do you want? (suggest: 5–8, mix of new and returning)
7. How many mock staff/team members?

Once you have all answers, do the following in order:

WIKI SETUP
1. Delete all existing content inside wiki/ (keep the folder)
2. Design a folder structure appropriate for this industry (clients, leads, staff, products/services, pricing, SOPs, etc.)
3. Create realistic mock records tailored to the industry — names, contact details, history, statuses
4. Create wiki/INDEX.md as a two-level index pointing to each subfolder's _INDEX.md
5. Create _INDEX.md inside each subfolder with record-level rows and identifier fields (phone, email, Instagram handle, etc.)
6. Every client/contact file must have an ## Interaction Log section at the bottom
7. Mark 1–2 clients as urgent/overdue and 1–2 as new leads

INBOX DEMO DATA
Seed 4–6 realistic pending approval messages in the SQLite database at data/crm.db, covering:
- At least one message from a known returning client (complaint or follow-up)
- At least one new enquiry from an unknown contact (new lead)
- At least one message that came via each of the channels the business uses (WhatsApp, Instagram, email, etc.)
- A mix of tones: friendly enquiry, urgent complaint, price question, booking request
Use the db.py helper or insert directly via sqlite3. Match the sender names and identifiers to wiki contacts where possible.

CONTACT TAGS
Decide on 2–4 contact categories that make sense for this industry (e.g. for a salon: Regular, Walk-in, Lead).
Update the contacts array in config.json — each entry needs:
  { "type": "slug", "label": "Display Name", "path": "wiki/path/to/folder" }
The dashboard reads this config to build filter chips and resolve contact paths automatically.
Make sure the wiki folder paths match exactly what you created in the wiki setup above.

QUICK QUESTIONS
Replace the 6 quick-question chips in static/index.html with questions relevant to this industry and business type. Examples for a salon: "Any bookings today?", "Low product stock?", "Follow-ups needed?". Pick questions the owner would actually ask daily.

Finally, confirm everything is set up and tell me the URL to open the dashboard.
```

---

## 6. Start the services

The local SQLite database (`data/crm.db`) is created automatically on first run — no setup needed.

**Option A — temporary (stops when you disconnect):**
```bash
python3 web.py &
python3 bridge.py
```

**Option B — persistent via systemd (recommended):**
```bash
# Copy and enable both service files
cp ai-pa-crm-web.service ~/.config/systemd/user/
cp ai-pa-crm.service ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now ai-pa-crm-web
systemctl --user enable --now ai-pa-crm

# Stay running after you log out
loginctl enable-linger $USER
```

Check they started:
```bash
systemctl --user status ai-pa-crm-web
systemctl --user status ai-pa-crm
```

---

## 7. Verify and open the dashboard

```bash
# Confirm web server is listening
curl -s http://localhost:PORT/api/status
```

Open `http://YOUR_SERVER_IP:PORT` in a browser. You should see the business name in the header, contacts loaded, and inbox populated with demo messages.

**Confirm Telegram is working:** send a message to the external topic of your group. Within ~10 seconds it should appear in the inbox as a pending approval.

---

## 8. Provision PostgreSQL (optional — production only)

The default setup uses SQLite which is sufficient for a single-user instance. When you're ready for production:

```bash
psql -h YOUR_DB_HOST -U postgres -f schema.sql
```

Then update `db.url` in `config.json` and restart the web service.

---

## What stays the same across all instances

| File | Reuse | Notes |
|------|-------|-------|
| `bridge.py` | ✅ Unchanged | No business logic |
| `channels/` | ✅ Unchanged | Generic channel abstraction |
| `CLAUDE.md` | ✅ Unchanged | Generic instructions, reads business name from config |
| `schema.sql` | ✅ Unchanged | Generic schema |
| `config.example.json` | ✅ Unchanged | Template — never edit directly |
| `config.json` | ✏️ Generated | Created in Step 4, gitignored |
| `wiki/` | 🔄 Rebuilt | Created in Step 5, business-specific |
| `data/crm.db` | 🔄 Auto-created | SQLite, created on first run |
