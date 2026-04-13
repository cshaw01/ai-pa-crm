# SOP: Emergency Dispatch

## Purpose
Standard procedure for handling emergency AC service calls (water leak, no cooling, electrical issues)

---

## ⚡ ACTION STEPS (When Emergency Call Received)

**AI Returns:**
1. **Situation Analysis** — Client details, SLA terms, equipment history
2. **Recommended Technician** — Best match (availability, skills, location)
3. **Parts Check** — What's needed, what's in stock, which van has it
4. **Draft Messages** — Customer notification + technician dispatch
5. **Action Buttons** — [ACCEPT] [EDIT] [REJECT] [CALL FIRST]

**Owner:** Reply with ACCEPT / EDIT / REJECT / CALL FIRST

**If ACCEPT:** Both messages sent automatically, follow-up scheduled
**If EDIT:** Owner modifies → sent
**If REJECT:** Owner provides alternative → dispatched
**If CALL FIRST:** Reminder to call customer before dispatching

---

## Emergency Categories

### Priority 1 (2-hour response)
- **Water leakage** in commercial premises (risk of property damage)
- **Electrical smell/burning** (fire risk)
- **No cooling** in server rooms/24/7 operations
- **SLA clients:** Menara KL Office Tower (2-hour SLA)

### Priority 2 (4-hour response)
- **Water leakage** in residential
- **No cooling** in commercial (non-critical)
- **Strange noise** (potential equipment damage)

### Priority 3 (24-hour response)
- **Reduced cooling** (still functional)
- **Bad smell** (health concern, not urgent)
- **Minor issues** (customer convenience)

## Dispatch Workflow

### Step 1: Receive Emergency Call
**Channels:** Phone, WhatsApp, Telegram  
**Information to Collect:**
- [ ] Client name/phone (look up in wiki)
- [ ] Issue description (what, when, where)
- [ ] Unit model (check client record if known)
- [ ] Photos/videos if possible

### Step 2: Classify Priority
Use the priority matrix above  
**If Priority 1:** Continue to Step 3 immediately  
**If Priority 2:** Dispatch within 1 hour  
**If Priority 3:** Schedule next available slot

### Step 3: Check Technician Availability
**Query wiki/technicians/** for:
- Who's available NOW or within 1 hour?
- Who has the right specialization? (VRF, cassette, residential)
- Who's geographically closest?

**Example:**
```
Emergency: Menara KL, water leak, cassette unit
Available: Azman (KLCC area, VRF certified)
ETA: 45 min from current location
```

### Step 4: Check Parts Availability
**For water leakage (most common):**
- Drain pump P/N: PAC-SK24SG → **2 units in stock**
- Wet vac → Available in Van #3
- If stock <2 → Alert to reorder after dispatch

### Step 5: Dispatch Technician
**Inform technician:**
- Client name, location, contact
- Issue description
- Parts to bring
- Expected duration
- Next job (schedule buffer)

**Template Message:**
```
EMERGENCY DISPATCH
Client: [Name]
Location: [Address]
Issue: [Description]
Parts: [List]
ETA: [Time]
Next Job: [Time/Location]
```

### Step 6: Notify Customer
**Send WhatsApp/Call:**
```
[AirCon KL] Dear [Name], technician [Name] is on the way.
ETA: [Time]
Contact: [Tech Phone]
Reference: [Job #]
```

### Step 7: Follow Up
**After technician completes:**
- [ ] Confirm issue resolved
- [ ] Update client record with findings
- [ ] Create invoice (if applicable)
- [ ] Schedule follow-up if needed
- [ ] Reorder parts if used

## SLA Tracking

For corporate clients with SLA:
- **Timer starts:** When emergency call received
- **Timer ends:** When technician arrives on-site
- **Penalty clock:** Starts after SLA period (2hr, 4hr, 6hr based on contract)

**Tracking:**
```
Client: Menara KL Office Tower
SLA: 2 hours
Call Time: 10:00am
Due By: 12:00pm
Tech Dispatched: 10:15am (Azman)
Tech Arrived: 11:30am ✅ (within SLA)
Status: OK (no penalty)
```

## Related
- [[../../wiki/clients/]] - Client SLA terms
- [[../../wiki/technicians/]] - Technician availability
- [[../../equipment/parts/]] - Parts inventory
- [[../../contracts/pricing/]] - Emergency surcharges
