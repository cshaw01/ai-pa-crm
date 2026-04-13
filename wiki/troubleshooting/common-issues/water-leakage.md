# Troubleshooting: Water Leakage

## Issue Overview
Water leakage is the #1 emergency call reason, especially for cassette and VRF systems.

---

## ⚡ ACTION STEPS (When Water Leak Reported)

**AI Returns:**
1. **Client Lookup** — Equipment type (cassette vs split), known issues, SLA terms
2. **Likely Cause** — Categorized by probability (pump 60%, clog 25%, install 10%, coil 5%)
3. **Parts Needed** — P/N, stock level, which van has it
4. **Recommended Technician** — Availability + specialization match
5. **Draft Messages** — Customer + technician dispatch
6. **Action Buttons** — [ACCEPT DISPATCH] [EDIT] [CALL CUSTOMER FIRST] [SEND TROUBLESHOOTING STEPS]

**Owner:** Reply with ACCEPT DISPATCH / EDIT / CALL CUSTOMER / SEND TROUBLESHOOTING

**If ACCEPT DISPATCH:** Technician sent with parts, ETA given to customer
**If EDIT:** Owner changes technician/parts → dispatched
**If CALL CUSTOMER:** Gathering more details before dispatch
**If SEND TROUBLESHOOTING:** Customer guided through diagnosis first

---

## Symptom
Water dripping from indoor unit, pooling on floor/ceiling, water stains

## Likely Causes (by probability)

### 1. Drainage Pump Failure (60% of cases)
**Common on:** Mitsubishi cassette units, VRF systems  
**Symptoms:** 
- Water in drain pan
- Pump not running (no humming sound)
- Often intermittent before total failure

**Diagnosis:**
1. Remove cassette panel
2. Check drain pan water level
3. Test pump with 24V direct power
4. If pump doesn't run → replace

**Part Needed:** PAC-SK24SG (Mitsubishi), S211366 (Daikin)  
**Stock Level:** 2 units (need to reorder)  
**Time to Fix:** 45-60 min

### 2. Clogged Drain Line (25% of cases)
**Common on:** All types, especially if not serviced regularly  
**Symptoms:**
- Water backs up in drain pan
- Slow drainage when testing
- Algae/debris visible in drain line

**Diagnosis:**
1. Pour water in drain pan
2. Observe drainage speed
3. If slow → flush with air/water pressure

**Part Needed:** None (cleaning only)  
**Time to Fix:** 30 min

### 3. Improper Installation (10% of cases)
**Symptoms:**
- Unit not level
- Drain pipe has sags/low points
- Leaking from connections

**Diagnosis:**
1. Check unit level with spirit level
2. Inspect drain pipe routing
3. Check connection points

**Part Needed:** May need to re-install/re-route  
**Time to Fix:** 2-4 hours (may need 2 technicians)

### 4. Dirty Evaporator Coil (5% of cases)
**Symptoms:**
- Coil heavily soiled
- Water doesn't sheet properly
- Algae buildup on coil fins

**Diagnosis:**
1. Visual inspection of coil
2. Check for water beading (should sheet smoothly)

**Part Needed:** Coil cleaner (chemical wash may be needed)  
**Time to Fix:** 60-90 min

## Quick Diagnostic Flow

```
Customer reports leak
    ↓
Ask: Where is water coming from?
    ├─ Indoor unit ceiling area → Cassette/VRF → Likely drain pump
    ├─ Indoor unit wall area → Split → Likely drain line
    └─ Outdoor unit → Normal (condensation)
    ↓
Ask: When did it start?
    ├─ Suddenly → Pump failure
    ├─ Gradually → Clogged line
    └─ After rain → External leak (not AC)
    ↓
Dispatch decision:
    ├─ Cassette/VRF + sudden → Bring drain pump (PAC-SK24SG)
    ├─ Split + gradual → Bring cleaning kit
    └─ Unknown → Diagnostic visit
```

## Parts Required (Always Bring for Cassette Emergency)
- [ ] PAC-SK24SG drainage pump (2 in stock)
- [ ] Wet vac (for water extraction)
- [ ] Towels/buckets
- [ ] Multimeter (test pump voltage)

## Related
- [[../../equipment/brands/mitsubishi]] - Mitsubishi pump P/N
- [[../../equipment/parts/drainage-pumps]] - Pump specifications
- [[../../sop/operations/emergency-dispatch]] - Emergency response procedure
- [[../../clients/corporate/menara-kl-office-tower]] - Has known drainage issue
