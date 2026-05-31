# Salesforce ↔ RiskRadar Setup Guide

This maps your **RiskRadar hackathon dataset** to a live **Salesforce Case** with Activities (emails, calls, tasks).

---

## How data maps

| RiskRadar (training data) | Salesforce source |
|---------------------------|-------------------|
| `claim_id` (e.g. CLM-2024-10000) | `SF-{CaseNumber}` (stable, human-readable) |
| `claimant_name` | Contact.Name or Case.Subject |
| `policy_type` | Custom: `Policy_Type__c` |
| `incident_type` | Case.Type or Case.Reason |
| `injury_severity` | Custom: `Injury_Severity__c` |
| `state` | Contact.MailingState |
| `days_open` | TODAY − Case.CreatedDate |
| `total_claimed` | Custom: `Total_Claimed__c` |
| `insurer_offer` | Custom: `Insurer_Offer__c` |
| `settlement_gap_pct` | Formula or custom field |
| `followup_contacts`, `doc_requests`, … | Matching custom fields |
| **Incident description** (unstructured) | Case.Description |
| **Email transcript** (unstructured) | EmailMessage records on Case |
| **Adjuster notes** (unstructured) | Task (calls) + internal notes |

**Scoring for SF claims:** hybrid — Model B on combined text + approximate Model A from Case fields (see `api/sf_scoring.py`). Similar-claims / full timeline may be limited until the claim is in the embedding index.

---

## Part 1 — Salesforce custom fields (on Case)

Create these fields on **Case** (API names must match, or update Apex/Flow JSON):

| Label | API Name | Type | Example values |
|-------|----------|------|----------------|
| Policy Type | `Policy_Type__c` | Picklist | Auto, Health, Liability |
| Total Claimed | `Total_Claimed__c` | Currency | 42000 |
| Insurer Offer | `Insurer_Offer__c` | Currency | 18000 |
| Injury Severity | `Injury_Severity__c` | Picklist | Minor Soft Tissue, No Injury |
| Follow-up Contacts | `Followup_Contacts__c` | Number | 3 |
| Doc Requests | `Doc_Requests__c` | Number | 2 |
| Disputed Items | `Disputed_Items__c` | Number | 1 |
| Inspections | `Inspections__c` | Number | 1 |
| Legal Rep | `Legal_Rep__c` | Text/Picklist | Attorney, None |
| Adjuster Level | `Adjuster_Level__c` | Picklist | Junior, Mid-Level, Supervisor |
| Payment Status | `Payment_Status__c` | Picklist | Pending, Approved, Disputed |
| DOI Complaint | `DOI_Complaint__c` | Checkbox | true/false |

Use **standard** fields where possible: `Subject`, `Description`, `Type`, `Reason`, `ContactId`.

---

## Part 2 — RiskRadar API (already in code)

| Endpoint | Purpose |
|----------|---------|
| `POST /integrations/salesforce/webhook` | Receive Case + activities from SF |
| `GET /integrations/salesforce/status` | Check integration health |
| `POST /integrations/salesforce/sync` | Optional REST pull (OAuth) |
| `GET /claims` | Queue includes SF claims |
| `GET /predict/{claim_id}` | Deep dive (e.g. `SF-00001234`) |

**Environment variables** (Render or `.env`):

```env
SALESFORCE_WEBHOOK_SECRET=your-long-secret
```

Optional OAuth pull:

```env
SF_INSTANCE_URL=https://yourorg.my.salesforce.com
SF_CLIENT_ID=...
SF_CLIENT_SECRET=...
SF_REFRESH_TOKEN=...
```

---

## Part 3 — Salesforce org setup (step by step)

### A. Remote Site Setting (if using Apex callout)

1. **Setup** → **Remote Site Settings** → **New**
2. **Remote Site URL:** `https://YOUR-APP.onrender.com` (no trailing slash)
3. Active ✓

### B. Named Credential (recommended)

1. **Setup** → **Named Credentials** → **New Legacy**
2. **Label:** `RiskRadar`
3. **URL:** `https://YOUR-APP.onrender.com/integrations/salesforce`
4. **Identity Type:** Named Principal
5. Add custom header: `X-RiskRadar-Secret` = same as `SALESFORCE_WEBHOOK_SECRET`

Webhook full path: `https://YOUR-APP.onrender.com/integrations/salesforce/webhook`

### C. Record-Triggered Flow (no Apex — good for demos)

**Option 1 — Case only (simplest)**

1. **Setup** → **Flows** → **New Flow** → **Record-Triggered Flow**
2. Object: **Case**, Trigger: **A record is created or updated**
3. Entry: `IsClosed = false`
4. **Action:** *Send HTTP Request* (or use **Apex Action** if HTTP not available in your edition)

If your org has **External Services** or **HTTP Callout** in Flow:

- **Method:** POST  
- **URL:** `https://YOUR-APP.onrender.com/integrations/salesforce/webhook`  
- **Header:** `X-RiskRadar-Secret` = your secret  
- **Body (JSON):**

```json
{
  "claim_id": "SF-{!$Record.CaseNumber}",
  "salesforce_case_id": "{!$Record.Id}",
  "salesforce_case_number": "{!$Record.CaseNumber}",
  "claimant_name": "{!$Record.Subject}",
  "incident_description": "{!$Record.Description}",
  "policy_type": "{!$Record.Policy_Type__c}",
  "incident_type": "{!$Record.Type}",
  "state": "",
  "days_open": 0,
  "total_claimed": {!$Record.Total_Claimed__c},
  "activities": []
}
```

**Option 2 — Apex + Flow (emails + calls)**

1. Deploy `salesforce/RiskRadarCaseSync.cls` (adjust custom field API names to match your org).
2. **Flow** on Case Create/Update → **Action** → **Send Case to RiskRadar** (invocable).
3. Apex gathers EmailMessage + Task and POSTs full payload.

### D. When to fire the Flow

| Event | Recommendation |
|-------|----------------|
| Case **created** | Yes — appears in triage immediately |
| Case **updated** | Yes — refresh score when new email/call logged |
| EmailMessage **created** | Optional second flow — re-sync parent Case |

For finals, **Case create + update** is enough if activities are on the Case before sync, or use Apex to pull latest activities each time.

---

## Part 4 — Test without Salesforce

```powershell
cd C:\Users\202121\Desktop\riskradar
$body = Get-Content .\scripts\demo_salesforce_webhook.json -Raw
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/integrations/salesforce/webhook" `
  -Method POST `
  -ContentType "application/json" `
  -Headers @{ "X-RiskRadar-Secret" = "change-me-to-a-long-random-string" } `
  -Body $body
```

Then open:

- Queue: http://localhost:3000 — look for **SF-00001234** with Salesforce badge  
- Detail: http://localhost:3000/claim?id=SF-00001234  

On Render (same origin):

```powershell
Invoke-RestMethod -Uri "https://YOUR-APP.onrender.com/integrations/salesforce/webhook" ...
```

---

## Part 5 — Webhook JSON reference

Minimum payload:

```json
{
  "salesforce_case_id": "500xx000001234ABC",
  "claim_id": "SF-00001234"
}
```

Full payload (matches dataset + activities):

```json
{
  "claim_id": "SF-00001234",
  "salesforce_case_id": "500xx...",
  "salesforce_case_number": "00001234",
  "claimant_name": "Jane Smith",
  "description": "Incident narrative...",
  "policy_type": "Auto",
  "incident_type": "Collision",
  "state": "TX",
  "days_open": 12,
  "total_claimed": 42000,
  "insurer_offer": 18000,
  "activities": [
    { "type": "email", "subject": "Re: claim", "body": "I will contact my attorney" },
    { "type": "call", "summary": "Claimant upset about delay" }
  ]
}
```

Activity `type` values: `email`, `call`, `task`, `note` → merged into email vs adjuster text like your Excel **Unstructured Data** sheet.

---

## Part 6 — Demo script for judges

1. Create Case in Salesforce with Description + log a call/email.  
2. Flow fires → RiskRadar webhook.  
3. Show Render URL triage queue — **Salesforce** badge, risk %.  
4. Open claim — triggers, brief, same UX as dataset claims.  
5. Say: *"Phase 2 writes `Escalation_Risk__c` back to the Case for Omni routing."*

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| 401 Invalid secret | Match `X-RiskRadar-Secret` and `SALESFORCE_WEBHOOK_SECRET` |
| Claim not in queue | Check `/integrations/salesforce/status` |
| Low score / no SHAP | SF uses hybrid scoring; add more text in activities |
| Flow HTTP blocked | Use Apex `@future(callout=true)` |
| CORS | Not needed — server-to-server webhook |

---

## Files added in repo

| File | Role |
|------|------|
| `api/external_claims.py` | SQLite store for SF cases |
| `api/integrations/salesforce.py` | Webhook + optional pull |
| `api/sf_scoring.py` | Map SF fields → ML features |
| `salesforce/RiskRadarCaseSync.cls` | Apex template |
| `scripts/demo_salesforce_webhook.json` | Local test payload |
