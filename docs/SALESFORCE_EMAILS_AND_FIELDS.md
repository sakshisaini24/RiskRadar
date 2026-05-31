# Salesforce: Emails, Call Logs, Claimant Name & Age

## Why you didn’t see “claimant name / age” fields in Setup

| Field | Status | Where it comes from |
|-------|--------|---------------------|
| **Claimant name** | Already supported | **Contact** on the Case (`Contact.Name`), or Case **Subject** if no Contact |
| **Age** | Now supported | **Contact → Birthdate** (Apex calculates age), or send `age` in webhook JSON |
| **Marital status** | Optional | Contact custom field `Marital_Status__c` or JSON `marital_status` |

We did **not** ask you to create a separate `Claimant_Name__c` on Case because Salesforce already has **Contact** — that’s the standard pattern.

Your **ML model** was trained on `claimant_name` and `age` in Excel, but **age is not in the XGBoost feature matrix** (only used for fairness slices in the dashboard). So age improves the **UI and future fairness**, not the core score today.

---

## How RiskRadar uses activities (emails vs calls)

Your Excel **Unstructured Data** sheet has three text columns:

| Excel column | Salesforce source | Activity `type` |
|--------------|-------------------|-----------------|
| Email Transcript — Claimant | **EmailMessage** on Case | `email` |
| Adjuster Field Notes | **Log a Call**, **Tasks**, **Case Comments** | `call`, `task`, `note` |
| Accident / Incident Description | **Case.Description** | (Case field, not activity) |

The webhook merges activities into `email_transcript` and `adjuster_notes` before scoring.

---

## Part 1 — Salesforce setup for emails

### Option A — Send email from the Case (easiest for demo)

1. Open a **Case**.
2. Click **Email** (or **Send Email** in the activity composer).
3. Send or log an email related to the Case.
4. Salesforce creates an **EmailMessage** record linked to the Case.

### Option B — Email-to-Case (production-style)

1. **Setup** → search **Email-to-Case** → **New**.
2. Create routing address (e.g. `claims@yourcompany.com`).
3. Emails to that address create/update Cases and **EmailMessage** rows.

### Important

- If you only use the **manual webhook JSON** test, emails work because `activities` is in the JSON.
- If you use **Flow without Apex**, Flow often sends `"activities": []` — **no emails**.
- Use **Apex `RiskRadarCaseSync`** (updated in repo) to query **EmailMessage** automatically.

### Re-sync after an email is logged

Create a second Flow:

1. **Object:** Task **OR** EmailMessage (if available as trigger)
2. **When:** record created
3. **Action:** **Send Case to RiskRadar** with parent Case Id

Or: edit Case and save again to re-fire the Case Flow.

---

## Part 2 — Salesforce setup for call logs

1. Open the **Case**.
2. Click **Log a Call** (or **New Task** → Type = Call).
3. Fill:
   - **Subject:** e.g. `Follow-up with claimant`
   - **Comments / Description:** what was said (this is the “adjuster notes” text)
4. **Save**.

Apex reads `Task` where `WhatId` = Case Id and `CallType` / `TaskSubtype = Call`.

---

## Part 3 — Claimant name, age, state

### On every Case

1. **Contact Name** (required for good demos):
   - Create or select a **Contact** on the Case (**Contact Name** lookup).
   - RiskRadar uses `Contact.Name` as `claimant_name`.

2. **Age**:
   - On **Contact**, set **Birthdate**.
   - Apex computes age and sends `"age": 42` in the webhook.

3. **State**:
   - **Contact → Mailing State** → maps to RiskRadar `state`.

### Optional custom field

| Label | API Name | Object |
|-------|----------|--------|
| Marital Status | `Marital_Status__c` | Contact |

Add to Apex SELECT if you create it:

```apex
Contact.Marital_Status__c
```

And in payload:

```apex
'marital_status' => c.Contact != null ? c.Contact.Marital_Status__c : null,
```

---

## Part 4 — Deploy updated Apex

1. Open **Developer Console** → **File** → **New** → **Apex Class** → `RiskRadarCaseSync`.
2. Paste from `salesforce/RiskRadarCaseSync.cls`.
3. Set `WEBHOOK_URL` and `WEBHOOK_SECRET` at the top of the class.
4. Fix custom field API names if your org differs (`Followup_Contacts__c` vs `Follow_up_Contacts__c`).
5. **Save**.

### Flow (same as before)

- **Record-Triggered Flow** on **Case** (create + update).
- Action: **Send Case to RiskRadar**.
- Input: `{!$Record.Id}`.

### Optional second Flow

- **Task** → after insert → get Case Id from `WhatId` → **Send Case to RiskRadar**.

---

## Part 5 — Verify emails/calls reached RiskRadar

### Test with PowerShell (includes activities)

```powershell
$secret = "RrSf_2026_xK9mP2vL7nQ4"
$body = Get-Content .\scripts\demo_salesforce_webhook.json -Raw
Invoke-RestMethod -Uri "http://127.0.0.1:8000/integrations/salesforce/webhook" `
  -Method POST -ContentType "application/json" `
  -Headers @{ "X-RiskRadar-Secret" = $secret } -Body $body
```

### In the UI

Open claim **SF-00001234** → **Communication audit** panel should show:

- Email transcript (from `activities` type `email`)
- Adjuster notes (from `call` / `note`)

### API check

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/predict/SF-00001234"
```

Look at `communication_audit.email_transcript` and `adjuster_notes` — should be non-empty.

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|--------|-----|
| No emails in RiskRadar | No EmailMessage on Case | Send email from Case; enable Email-to-Case |
| No call logs | No Task on Case | Use **Log a Call** |
| Empty activities with Flow | Flow doesn’t query emails | Use Apex class |
| Wrong claimant name | No Contact on Case | Link Contact; or name comes from Subject only |
| No age | No Birthdate on Contact | Fill Contact Birthdate |
| Apex compile error | Wrong field API name | Match fields in Setup → Object Manager |

---

## Field checklist (Case + Contact)

**Case (custom)** — claim financials / policy  
`Policy_Type__c`, `Total_Claimed__c`, `Insurer_Offer__c`, … (see main setup doc)

**Case (standard)** — `Subject`, `Description`, `Type`, `ContactId`

**Contact (standard)** — `Name`, `Birthdate`, `MailingState`

**Activities** — `EmailMessage`, `Task` (calls), `CaseComment` (optional)
