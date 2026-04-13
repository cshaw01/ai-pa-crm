# AI-PA CRM — Setup Guide

Follow these steps to spin up a new instance of this project for any business.

---

## 1. Copy the project

```bash
cp -r ai-pa-crm /path/to/new-business-name
cd /path/to/new-business-name
```

---

## 2. Set up Telegram

1. Create a new Telegram bot via [@BotFather](https://t.me/BotFather) — get the bot token
2. Create a new Telegram group and add the bot as admin
3. Enable Topics on the group (Group Settings → Topics)
4. Create two topics:
   - **External** — for incoming customer messages
   - **Internal** — for owner review and AI responses
5. Note the group chat ID and both topic IDs

---

## 3. Provision the database

Create a new PostgreSQL database for this business (one DB per business):

```bash
psql -h <host> -U postgres -f schema.sql
```

Then update the password in the DB and in `config.json`.

---

## 4. Update config.json

```json
{
  "business": {
    "name": "Your Business Name",
    "timezone": "Your/Timezone"
  },
  "db": {
    "url": "postgresql://ai_crm_user:YOUR_PASSWORD@host:5432/ai_crm"
  },
  "claude": {
    "bin": "/home/claude/.local/bin/claude",
    "flags": ["--dangerously-skip-permissions"],
    "model": "claude-sonnet-4-6",
    "project_dir": "/path/to/new-business-name"
  },
  "channels": {
    "telegram": {
      "bot_token": "YOUR_BOT_TOKEN",
      "chat_id": "YOUR_GROUP_CHAT_ID",
      "topics": {
        "external": YOUR_EXTERNAL_TOPIC_ID,
        "internal": YOUR_INTERNAL_TOPIC_ID
      },
      "owners": ["YOUR_TELEGRAM_USER_ID"]
    }
  }
}
```

---

## 5. Rebuild the wiki for this business

The `wiki/` folder contains AC servicing mock data. Replace it entirely.

Open Claude Code in the project directory and run this prompt:

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

Claude will rebuild the entire wiki from scratch with appropriate structure and mock data for the business type.

---

## 6. Start the bridge

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
| `config.json` | ✏️ Update | Business name, DB, Telegram credentials |
| `wiki/` | 🔄 Rebuild | All content is business-specific |
