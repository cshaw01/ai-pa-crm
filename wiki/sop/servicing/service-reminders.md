# Service Reminders — SOP

---

## ⚡ ACTION STEPS (When Checking Renewals/Due Services)

**Query:** "Who needs servicing in next [X] days?" or "Show me renewals due"

**AI Returns:**
1. **Priority-Sorted List** — Overdue (🔴) → This Week (🟡) → Next Week (🟢)
2. **Client Details** — Units, contract value, contact info, notes
3. **Draft Messages** — Personalized WhatsApp for each client
4. **Revenue at Risk** — Total contract value highlighted
5. **Action Buttons** — [SEND ALL] [SELECTIVE] [EDIT ALL] [EDIT INDIVIDUAL] [SKIP OVERDUE]

**Owner:** Reply with SEND ALL / SELECTIVE / EDIT / SKIP OVERDUE

**If SEND ALL:** All messages sent, responses tracked
**If SELECTIVE:** Owner chooses which to send (e.g., "Send 2,3,4,5 — I'll call #1 personally")
**If EDIT ALL:** Owner modifies all → sent
**If EDIT INDIVIDUAL:** Owner selects specific messages to edit
**If SKIP OVERDUE:** Reminder created to call overdue client directly

---

## Service Frequency Guidelines

### Residential Clients
- **Standard:** Every 6 months (2x per year)
- **High Usage:** Every 4 months (3x per year) — if AC runs daily
- **Low Usage:** Once per year — if unit rarely used

### Corporate Clients
- **Monthly:** High-traffic areas (retail, food courts, server rooms)
- **Quarterly:** Standard offices, meeting rooms
- **Ad-hoc:** Low-usage spaces, storage areas

---

## Reminder Timing

| Client Type | First Reminder | Second Reminder | Final Notice |
|-------------|---------------|-----------------|--------------|
| Residential | 7 days before | 3 days before | Day of (morning) |
| Corporate | 14 days before | 7 days before | 3 days before |
| Overdue | Immediate | 3 days later | 7 days later (call) |

---

## Draft Message Templates

### Residential (Standard)
```
Salam [Name],

Your AC service is due [Date]. [Technician] available [Time Slot].

[Unit Count] units ([Brand]), estimated [Duration].

Reply YES to confirm or suggest alternative time.

— AirCon KL Service Team
```

### Residential (Overdue)
```
Hi [Name],

Your AC service is overdue by [X] days/weeks. Our records show [specific issue if any].

Available slots:
- [Option 1]
- [Option 2]

Please reply with preferred time. We prioritize overdue customers.

— AirCon KL Service Team
```

### Corporate (Monthly)
```
Hi [Name],

[Technician] will service [Unit Count] units on [Date] ([Time Range]).

Please ensure:
- [Site-specific requirement 1]
- [Site-specific requirement 2]

Reply to confirm or reschedule.

— AirCon KL Service Team
```

### Corporate (Overdue/SLA Risk)
```
Hi [Name],

Your service is overdue by [X] days. This may affect your SLA terms and warranty coverage.

We can prioritize your service this week. Available:
- [Option 1]
- [Option 2]

Please confirm urgently.

— AirCon KL Service Team
```

---

## Follow-Up Tracking

**After Messages Sent:**
- Track response rate (target: >80% within 24hrs)
- Flag non-responders for phone call
- Update service schedule based on confirmations
- Send reminder to technician 1 day before

**Sample Follow-Up Report:**
```
📊 SERVICE REMINDER RESULTS

Sent: 6 messages (9:00am)
Responses (2 hrs later):
- ✅ Confirmed: 5/6 (83%)
- ⏳ Pending: 1/6 (Singh — call recommended)

Schedule Updated:
- 2026-04-12: Pavilion Retail (confirmed)
- 2026-04-15: TechCorp + Ahmad Rahman (confirmed)
- 2026-04-18: Menara KL (confirmed)
- 2026-04-20: KL Sentral (confirmed)

Action Required:
- Call Harjit Singh (overdue 22 days) — Owner to handle
```

---

## Revenue Protection

**Annual Value per Client:**
| Client Type | Avg Annual Value | At Risk if Churned |
|-------------|-----------------|-------------------|
| Residential | RM 200-400 | RM 200-400/year |
| Small Corporate | RM 5,000-15,000 | RM 5,000-15,000/year |
| Medium Corporate | RM 20,000-50,000 | RM 20,000-50,000/year |
| Large Corporate | RM 100,000+ | RM 100,000+/year |

**Example:** Menara KL Office Tower
- Monthly: RM 18,000
- Annual: RM 216,000
- If churned due to missed service: **RM 216,000/year lost**
- Cost of AI assistant: Pays for itself 100x+

---

## Related
- [[../../clients/]] — All client records with service dates
- [[../../technicians/]] — Technician schedules + availability
- [[../../contracts/pricing/]] — Contract values by client
- [[../../sop/customer-service/whatsapp-response]] — Message templates
