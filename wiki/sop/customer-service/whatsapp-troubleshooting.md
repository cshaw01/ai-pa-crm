# WhatsApp Troubleshooting — SOP

---

## ⚡ ACTION STEPS (When Customer Messages About AC Issue)

**Query:** Customer message pasted (e.g., "AC not cooling, loud noise")

**AI Returns:**
1. **Customer Identification** — Name, location, equipment record (if existing customer)
2. **Likely Diagnosis** — Based on symptoms + equipment history + common issues
3. **Diagnostic Questions** (if needed) — 2-3 targeted questions to narrow down
4. **Parts Check** — If repair needed, what's in stock, which van has it
5. **Draft Messages** — Diagnostic questions OR direct quote (depending on confidence)
6. **Action Buttons** — [SEND DIAGNOSTIC] [SEND DIRECT QUOTE] [EDIT] [CALL]

**Owner:** Reply with SEND DIAGNOSTIC / SEND DIRECT QUOTE / EDIT / CALL

**If SEND DIAGNOSTIC:** Questions sent, customer response tracked, auto-followup with quote
**If SEND DIRECT QUOTE:** Quote sent immediately (fast but may misdiagnose)
**If EDIT:** Owner modifies → sent
**If CALL:** Reminder to call for complex issues or VIP customers

---

## Common Issue Diagnostic Flows

### Not Cooling

**Symptoms:** "AC not cooling" or "not cold enough"

**AI Diagnostic Questions:**
1. "What's the temperature setting on remote? Try 18°C and wait 10 min."
2. "Is the outdoor unit running? Can you hear/see the fan spinning?"
3. "What's the error code? Check LED display."

**Likely Causes (by probability):**
| Cause | % | Signs | Parts Needed |
|-------|---|-------|--------------|
| Low gas | 45% | Outdoor runs but no cool, hissing sound | R32/R410A refrigerant |
| Fan motor failure | 30% | Loud noise, no airflow, error A6 | Fan motor P/N varies |
| Dirty filter/coil | 15% | Weak airflow, gradual decline | No parts (clean only) |
| PCB failure | 10% | Unit won't start, no display | PCB P/N varies |

---

### Water Leakage

**Symptoms:** "Water dripping" or "puddle under AC"

**AI Diagnostic Questions:**
1. "Is water coming from indoor unit or outdoor unit?"
2. "When did it start? Suddenly or gradually?"
3. "Send photo of where water is coming from."

**Likely Causes (by probability):**
| Cause | % | Equipment Type | Parts Needed |
|-------|---|----------------|--------------|
| Drain pump failure | 60% | Cassette, VRF | PAC-SK24SG pump |
| Clogged drain line | 25% | All types | None (clean) |
| Improper install | 10% | New installs (<1 year) | Re-install needed |
| Dirty coil | 5% | Not serviced >1 year | Coil cleaner |

---

### Strange Noise

**Symptoms:** "Making loud noise" or "rattling/buzzing sound"

**AI Diagnostic Questions:**
1. "Is noise from indoor unit or outdoor unit?"
2. "What type of noise? Rattling, buzzing, grinding, or squealing?"
3. "Does noise happen all the time or only when starting?"

**Likely Causes (by probability):**
| Cause | % | Noise Type | Parts Needed |
|-------|---|------------|--------------|
| Fan motor bearing | 40% | Grinding/squealing | Fan motor |
| Loose screws/panel | 25% | Rattling/vibration | None (tighten) |
| Debris in fan | 20% | Buzzing/clunking | None (clean) |
| Compressor issue | 15% | Loud humming | Compressor (major) |

---

### Bad Smell

**Symptoms:** "AC smells bad" or "musty odor"

**AI Diagnostic Questions:**
1. "What kind of smell? Musty, burning, or chemical?"
2. "When did you first notice it?"
3. "When was the last service?"

**Likely Causes (by probability):**
| Cause | % | Smell Type | Action |
|-------|---|------------|--------|
| Dirty evaporator | 50% | Musty/mildew | Chemical wash |
| Dirty filters | 30% | Dusty/stale | Clean/replace filters |
| Electrical issue | 15% | Burning | ⚠️ Turn off, inspect |
| Dead animal in unit | 5% | Rotten | Remove + sanitize |

---

## Message Templates

### Diagnostic Questions (First Response)
```
Hi [Name],

Thanks for messaging. To help you faster:

1. [Question 1]
2. [Question 2]
3. [Question 3]

Reply with answers and I'll advise next steps.

— AirCon KL Support
```

### Direct Quote (High Confidence)
```
Hi [Name],

Based on your description, likely [issue].

We can fix [tomorrow/date]. [Technician] available [time slot].
Parts: [part name] (in stock ✅)
Cost: RM [labor] + RM [part] = RM [total]
Time: About [duration]

Confirm [time]?

— AirCon KL Support
```

### Urgent/Emergency
```
Hi [Name],

This sounds urgent. Let me call you directly in 5 minutes to diagnose properly.

In the meantime:
- [Safety tip if applicable, e.g., "Turn off unit at isolator"]
- [Temporary fix if any, e.g., "Place bucket under leak"]

Talk soon.

— AirCon KL Support
```

---

## Escalation Rules

**Call Instead of WhatsApp If:**
- Customer is VIP (corporate contract >RM 10,000/month)
- Issue involves electrical smell/burning (safety risk)
- Customer has called 2+ times about same issue (frustration risk)
- Issue is complex (VRF system, multiple units, commercial)
- Customer explicitly says "Call me" or "This is urgent"

**Escalate to Owner If:**
- Customer threatens to switch providers
- Customer mentions competitor quote
- Issue requires major repair (compressor, full replacement)
- SLA breach is imminent (corporate client)
- Customer is emotional/angry

---

## Follow-Up Tracking

**After Diagnostic Questions Sent:**
```
📊 TROUBLESHOOTING SESSION

Customer: [Name]
Issue: [Description]
Diagnostic Sent: [Time]
Customer Responded: [Time]
Diagnosis Confirmed: [Issue]

Next Action:
- [ ] Quote sent (awaiting confirmation)
- [ ] Technician scheduled ([Name], [Date/Time])
- [ ] Parts reserved ([Part], [Van/Warehouse])

Follow-Up Due: [Date/Time]
```

**If Customer Doesn't Respond (4 hours later):**
```
Hi [Name],

Just following up on your AC issue. Still need help?

Reply YES and I'll prioritize your case.

— AirCon KL Support
```

---

## Success Metrics

| Metric | Target | Why It Matters |
|--------|--------|----------------|
| First Response Time | <5 minutes | Customer feels valued |
| Diagnosis Accuracy | >85% (first-visit fix) | Fewer call-backs |
| Quote Close Rate | >40% | Revenue generation |
| Customer Satisfaction | >4.5/5 stars | Referrals, retention |

---

## Related
- [[../../troubleshooting/]] — Full diagnostic guides by issue
- [[../../equipment/brands/]] — Brand-specific error codes
- [[../../equipment/parts/]] — Parts inventory + P/N lookup
- [[../../clients/]] — Customer equipment history
