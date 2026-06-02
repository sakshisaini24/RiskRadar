# Business impact slide — Google Slides (40 seconds)

## Import the slide

1. Upload **`docs/RiskRadar_Business_Impact.pptx`** to Google Drive.
2. **Open with** → **Google Slides** → **Save as Google Slides**.

Regenerate:

```powershell
py scripts\generate_impact_slide.py
```

---

## What’s on the slide (matches your live ROI calculator)

| Metric | Value | How it’s derived |
|--------|-------|------------------|
| **Adjuster hours returned** | **108 hrs/mo** | 175 deep reviews/mo × **37 min** saved (45→8 min workflow) |
| **Early escalations surfaced** | **~74/mo** | 500 claims × 35% escalate × (77% − 35% recall lift) |
| **Catch-rate lift** | **120%** | 77% conservative recall vs 35% random triage |
| **Labor savings** | **~$71K/yr** | 108 hrs/mo × $55/hr |
| **Modeled loss avoidance** | **~$637M/yr** | ~74 early catches/mo × **~$723K** cost-per-miss × 12 |

*Portfolio defaults: 500 claims/month, $289K average claim, 3.5× escalated-cost multiplier — same inputs as the green ROI panel on your queue page.*

---

## 40-second speaker script (read aloud)

> **“Here’s the business impact in numbers your CFO would ask for.”**
>
> **“On a five-hundred-claim-per-month book, specialists today spend about forty-five minutes per deep review. RiskRadar cuts that toward eight — thirty-seven minutes returned per case. That’s over one hundred adjuster hours a month back on the floor — about seventy-one thousand dollars a year in labor at conservative rates.”**
>
> **“On risk, we don’t replace gut feel with another dashboard. On holdout data we use a conservative seventy-seven percent recall — versus roughly thirty-five percent if you triage at random. That surfaces about seventy-four additional escalations per month while the cheap-resolution window is still open.”**
>
> **“If an escalated file runs even a fraction of industry legal-and-settlement drag, each early catch is worth hundreds of thousands in modeled exposure — our live ROI calculator lets you stress-test that assumption on stage.”**
>
> **“Faster triage, earlier flags, dollars and hours you can measure — not another reactive legal bill.”**

*(~38–42 seconds at a steady pace)*

---

## If a judge pushes back on $637M

**Say:** “That’s the **scenario output** when you apply our default book size and a 3.5× escalated-cost multiplier to each additional case we catch versus random triage — not a guaranteed savings line. The **defensible floor** is operational: **108 hours** and **~$71K** labor. The upside is loss avoidance per early escalation; we show the math live and you can dial claim value and multiplier down in the demo.”

**Then:** Open the queue page → scroll to **Business Impact · ROI Calculator** → toggle sliders.

---

## Build manually in Google Slides

- **Theme:** Emerald green background `#064E3B`, amber `#FBBF24` for big numbers.
- **Title:** Quantifiable business impact
- **Four stat cards:** 108 hrs · ~74/mo · 120% lift · $71K/yr
- **Banner:** $637M annual modeled escalation avoidance (footnote: 3.5× multiplier, adjustable)
- **Footer:** Live ROI in product · 77% conservative recall

---

## Demo tip (10 seconds after this slide)

Transition: *“These aren’t slide math — they’re the same formulas running in the app.”* → show ROI panel with **Planning mode · 77% recall** enabled.
