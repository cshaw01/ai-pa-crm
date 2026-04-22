# Mock Data Setup Guide

When creating a new tenant with sample data, use this guide to build realistic wiki content and inbox entries. Default reference: **Malaysia (KL / Selangor)**.

---

## 1. Business Identity

Set in `config.json`:
```json
{
  "business": {
    "name": "Business Name Sdn Bhd",
    "timezone": "Asia/Kuala_Lumpur"
  }
}
```

- Use Malaysian business naming conventions (e.g., "Sdn Bhd", "Enterprise")
- Timezone: `Asia/Kuala_Lumpur` (UTC+8)
- Currency: RM (Ringgit Malaysia)
- Phone format: `+60 1X-XXX XXXX` (mobile) or `+60 3-XXXX XXXX` (KL landline)

---

## 2. Wiki Structure

Every tenant wiki follows this layout:

```
wiki/
├── INDEX.md                    # Root index — lists all folders
├── clients/ or patients/
│   ├── <type1>/_INDEX.md       # e.g. commercial, residential, active
│   │   └── <record>.md
│   └── <type2>/_INDEX.md
├── leads/_INDEX.md
│   └── <lead>.md
├── services/_INDEX.md          # Pricing, packages, service types
│   └── <detail>.md             # Breakdowns by category
├── staff/_INDEX.md
│   └── <person>.md
├── schedule/_INDEX.md          # Current week's jobs
│   └── week-YYYY-MM-DD.md
└── sops/_INDEX.md
    └── <procedure>.md
```

### Index Tables

Each `_INDEX.md` must have a markdown table. The **column headers matter** — the frontend uses them for contact matching:

| Column | Used For |
|--------|----------|
| `Phone` or `Phone / WhatsApp` | Primary phone matching |
| `Email` | Email matching |
| `Identifier` | Catch-all matching (phone, email, social handle) |
| `Contact` | Contact person name (for commercial clients) |
| `Name` or `Company` or `Name / Identifier` | Display name + name-based matching |
| `Status` | Triage — keywords `OVERDUE`, `TODAY` trigger urgent styling |

### Record Files

Each contact/client/patient file should include:
- **Profile section** — key details, identifiers, address
- **Service/policy/treatment history** — table with dates, types, staff
- **Interaction log** — table with date, channel, direction, summary

---

## 3. Services & Pricing

Create detailed pricing files, broken down by category. Include:
- **Service types** with price ranges in RM
- **Parts / equipment** with stock levels and unit costs
- **Packages / plans** (e.g., maintenance contracts, treatment packages)
- **Brand-specific** details where relevant

This data is what the AI uses to answer pricing questions accurately. Generic or missing pricing data leads to vague AI responses.

---

## 4. Staff

Each staff member file should include:
- Contact details (phone, WhatsApp, email)
- Certifications / qualifications
- Schedule (working hours, on-call rotation)
- Specialisation (what types of work they handle)
- Territory / coverage area

Use Malaysian names reflecting the country's diversity (Malay, Chinese, Indian, etc.).

---

## 5. Schedule

Create a weekly schedule file showing:
- Each day's jobs with time, assigned staff, client, location, status
- Status markers: ✅ Completed, 🔄 In progress, ⏳ Scheduled, Pending confirmation
- Notes section for anything requiring attention

---

## 6. Inbox Mock Data (pending_approvals)

Insert sample inbox entries into the SQLite database at `/app/data/crm.db` table `pending_approvals`.

### Required Variety

Include a mix of these message types:

| Type | Description | Has Contact Record? |
|------|-------------|-------------------|
| **New prospect** | First-time inquiry, no existing record | No — analysis says "New contact" |
| **Existing client — simple question** | Schedule check, pricing question, appointment confirm | Yes |
| **Existing client — urgent request** | Equipment failure, emergency, SLA issue | Yes |
| **Existing client — follow-up** | Responding to a quote, confirming a booking | Yes |
| **Lead — conversion** | Lead confirming they want to proceed | Yes (in leads) |
| **Lead — new inquiry** | Inquiry from referral or web form | Yes (in leads) |
| **Bilingual message** | Message in Malay (or other local language) | Either |
| **Commercial client** | Business-to-business with contract context | Yes |

### Ensuring Contact Matching

For inbox entries to link to contacts in the CRM:
- The `identifier` field must match a value in the contact's index table
- Phone numbers: use the exact format from the `_INDEX.md` (e.g., `+60 12-888 3201`)
- Emails: exact match
- The `sender_name` should match the contact person's name for name-based fallback matching

### Table Schema

```sql
INSERT INTO pending_approvals (
    id,                -- UUID string
    identifier,        -- phone/email matching a contact record
    identifier_type,   -- 'phone', 'email'
    channel,           -- 'whatsapp', 'email', 'phone', 'walk-in', 'web'
    sender_name,       -- display name
    original_message,  -- the actual message text
    analysis,          -- AI analysis (who they are, history, recommendation)
    draft,             -- AI-drafted reply (plain text with \n for newlines)
    status,            -- 'pending'
    kind,              -- 'inbound' or 'outbound'
    created_at,        -- ISO 8601 datetime
    updated_at         -- ISO 8601 datetime
) VALUES (...);
```

### Stagger timestamps

Set `created_at` at varied intervals to create realistic triage grouping:
- 1–2 entries from 3–6 hours ago (shows in "Waiting > 1 hour" group)
- 2–3 entries from 15–60 mins ago (shows in "Today" group)
- 1–2 entries from < 15 mins ago (shows as fresh)

---

## 7. Malaysian Reference Data

### Common Locations (KL / Selangor)

**Residential areas:** Petaling Jaya (SS2, Damansara, Bandar Utama), Subang Jaya, Shah Alam, Puchong, Cheras, Ampang, Wangsa Maju, Setapak, Taman Melawati, Mont Kiara, Bangsar, TTDI

**Commercial areas:** KL City Centre (Jln Sultan Ismail, Bukit Bintang, KLCC), Bangsar, Mid Valley, Mutiara Damansara, Cyberjaya, Menara/office towers

### Phone Number Formats
- Mobile: `+60 1X-XXX XXXX` (e.g., `+60 12-345 6789`)
- Landline KL: `+60 3-XXXX XXXX`

### Common Channels
- **WhatsApp** is the dominant business communication channel in Malaysia
- Email for formal/commercial correspondence
- Phone calls for urgent matters
- Walk-ins for retail/clinic businesses
- Instagram / Facebook for lead generation

### Language
- Business communication: English or Malay (or mix)
- Include at least one Malay-language message in the inbox
- Chinese and Tamil names should be represented among contacts
- Use appropriate greetings: "Assalamualaikum", "Hi", etc.

### Currency & Pricing
- All prices in RM (Ringgit Malaysia)
- Include SST (Sales & Service Tax, 8%) notes where relevant
- Payment terms: Malaysian business norms (30-day for commercial, upfront for residential)

### Address Format
```
[Unit/Lot], Jalan [Street Name],
[Taman/Area], [Postcode] [City/State]
```
Example: `22, Jalan SS 2/30, Petaling Jaya, 47300 Selangor`
