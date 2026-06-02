# Problem slide — Google Slides

## Option A — Import PowerPoint (editable in Slides)

1. Open [Google Drive](https://drive.google.com) → **New** → **File upload**.
2. Upload `docs/RiskRadar_Problem_Statement.pptx` (generate it first — see below).
3. Right-click → **Open with** → **Google Slides**.
4. **File** → **Save as Google Slides**.

Regenerate the `.pptx`:

```powershell
py -m pip install python-pptx
py scripts\generate_problem_slide.py
```

## Option B — Screenshot (no Python needed)

1. Double-click `docs/problem-slide.html` (opens in Chrome/Edge).
2. Press **F11** for fullscreen (optional).
3. **Win + Shift + S** → capture the slide.
4. In Google Slides: **Insert** → **Image** → **Upload from computer**.
5. Resize to fill the 16:9 slide; add a blank dark background behind if needed.

## Option C — Build by hand

Use the copy and layout tables below.

---

## Build manually in Google Slides (if you prefer)

**Slide setup:** Blank slide · **16:9** · Background `#0F172A` (slate-900) · Accent `#FB923C` (orange)

### Title (top)

| Element | Text |
|--------|------|
| **Headline** | When escalation is obvious, it's already too late |
| **Subtitle** | Insurance claims · legal risk · early intervention |

Font: **Arial** or **Roboto** · Headline 32–36 pt white · Subtitle 14 pt `#94A3B8`

### Left column — THE PAIN

1. **Specialists guess** — Gut feel + manual review of voluminous notes and structured data  
2. **Reactive, not predictive** — Red flags appear after the low-cost resolution window closes  
3. **Two costs** — Legal fees can exceed claim value · ~45 min/case on manual research  

**Closing (bold):** We need intelligence that reads between the lines—before cases hit a point of no return.

### Right column — THE STAKES (stacked boxes + ▼ between)

| Step | Title | Subtext |
|------|--------|---------|
| 1 | CLAIM FILE | Notes · emails · calls · forms |
| 2 | TODAY | Manual review · slow · subjective |
| 3 | ESCALATION OBVIOUS | Window for cheap fix — closed |
| 4 | TOO LATE | Legal fees ↑ · leverage ↓ |

**Three stat boxes (bottom right):**

| Stat | Label |
|------|--------|
| $$$ | Legal spend can exceed claim value |
| 45 min | Per case manual research |
| ? | Risk hidden in unstructured notes |

### Footer

RiskRadar — predict escalation early · explain why · act before legal costs run away

---

## 30-second speaker script

> In insurance, the expensive failures aren't always the biggest claims—they're the ones that quietly turn into legal fights.  
> Today, specialists use gut feel and manual reviews across voluminous notes and structured data. That's reactive: by the time escalation is obvious, the window for a low-cost early resolution is gone.  
> The damage is twofold: legal fees that can eventually exceed the claim itself, and operational drag—specialists spending up to forty-five minutes per case on research.  
> What's missing is intelligence that reads between the lines of adjuster notes and flags high-risk cases before they reach a point of no return.  
> That's the problem RiskRadar solves.

---

**Next slide:** Business impact (40 sec) → see `docs/GOOGLE_SLIDES_IMPACT.md` and `docs/RiskRadar_Business_Impact.pptx`.

## Google Slides tips

- **Insert → Theme builder** is not needed; one slide is enough for the problem beat.
- Use **View → Grid view** to duplicate this slide for “Solution” / “Demo” later.
- For finals, **File → Publish to the web** only if you need a kiosk loop; otherwise present live from Slides.
