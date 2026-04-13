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
pip install requests
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

## 5. Run the wiki setup prompt

Once config is done, paste this prompt to build the wiki from scratch for the new business. Fill in the placeholders first.

```
This project is being set up for a new business.

Business name: [name]
Business type: [e.g. corporate gifting, plumbing, restaurant, law firm]
Location: [city/country]
Number of mock clients: [e.g. 8 — mix of corporate and individual]
Number of mock staff: [e.g. 3]

Please:
1. Delete all existing content inside wiki/ (keep the folder itself)
2. Design a wiki folder structure appropriate for this business type
3. Create realistic mock data for all clients, staff, products/services, pricing, and SOPs
4. Create wiki/INDEX.md as a two-level index pointing to each subfolder
5. Create _INDEX.md inside each subfolder with record-level listings and identifier fields (phone, email, etc.)
6. Ensure every client/contact file has an ## Interaction Log section at the bottom
7. Update the Records count in wiki/INDEX.md to match what was created
```

---

## 6. Provision the database

```bash
psql -h YOUR_DB_HOST -U postgres -f schema.sql
```

When prompted, use the password you set in Step 4.

---

## 7. Start the bridge

```bash
python3 bridge.py
```

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
