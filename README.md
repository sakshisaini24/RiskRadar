# RiskRadar AI — Escalation Intelligence for Insurance Claims

> Catches **~78% of escalations at filing time**, predicts **when** each will
> escalate (**MAE ±37 days**), shows the **5 most similar past claims**, and
> hands the adjuster a grounded legal brief + drafted response —
> cutting 45 minutes of manual research down to under 10.

[Problem statement · Predicting When a Dispute Will Escalate]

---


**Embedding index:** 550 claims × 384-dim sentence-transformer embeddings
(`all-MiniLM-L6-v2`), cosine-ranked nearest-neighbour lookup.

---

## Architecture

```
Excel (550 claims, labelled)
   │
   ▼
pipeline/  step_01..04     ─►  data/features/feature_matrix.csv
                                data/processed/text_clean.csv
   │
   ▼
models/                    Model A: XGBoost (structured, SHAP explainer)
   │                       Model B: TF-IDF + XGBoost (text, 1k features)
   │                       ── frozen 80/20 holdout (split_utils.py)
   │                       ── isotonic calibrator fit on holdout
   │                       ── time-to-escalation regressor (R²=0.81)
   │                       ── sentence-transformer claim index (550×384)
   ▼
api/   FastAPI              /claims           triage queue
   │                        /predict/{id}     full per-claim intelligence
   │                        /metrics          holdout recall/precision/F1
   │                        /metrics/holdout_scores  raw y_true/probs (slider)
   │                        /evaluation/report + /evaluation/plot/{name}
   │                        /similar/{id}     embedding NN search
   │                        /fairness         recall by state/age/policy
   │                        /drift            PSI per feature
   │                        /feedback         POST agree/disagree
   │                        /feedback/summary disagreement rate
   ▼
frontend/ Next.js 16        /           Triage Queue + Honest Perf Card
   (React 19, Tailwind 4)   /claim?id=  Single-claim deep dive
                            - ROI calculator (threshold-linked)
                            - Time-to-escalation widget
                            - Similar past claims
                            - Adjuster feedback buttons
                            - Audit trail panel (score construction,
                              SHAP, citation grounding)
```

---

## Tech stack

| Layer | Stack |
|---|---|
| ML | XGBoost 2.0, scikit-learn (IsotonicRegression, PSI), SHAP |
| NLP / embeddings | sentence-transformers (MiniLM-L6), TF-IDF |
| Text LLMs | Groq Llama 3.1, Google Gemini 2.5 Flash — **temperature=0, citation-grounded** |
| Legal lookup | Indian Kanoon API, CourtListener (US) |
| API | FastAPI + Uvicorn |
| Frontend | Next.js 16, React 19, Tailwind CSS 4, ReactMarkdown |
| Persistence | SQLite (feedback log), .joblib / .json (model artifacts) |

---

## Run it

```bash
# 1. Python env + deps
python -m venv venv && ./venv/Scripts/activate  # Windows
pip install -r requirements.txt

# 2. Rebuild pipeline + models
py run_pipeline.py
py -m models.train_model_a       # saves holdout_claim_ids.csv
py -m models.train_model_b       # reuses same holdout
py -m models.fit_calibrator      # isotonic calibrator
py -m models.train_time_to_escalation
py -m models.build_claim_index   # ~30s for 550 claims
py -m models.evaluate            # writes data/features/eval/*.png

# 3. API
py -m uvicorn api.main:app --host 127.0.0.1 --port 8000

# 4. Frontend (separate shell)
cd frontend && npm install && npm run dev
# open http://localhost:3000
```

Set `GEMINI_API_KEY` and `GROQ_API_KEY` in `.env` to enable LLM briefs.
Leave blank and the UI gracefully skips those panels.

---
