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

## Steps to Build
Prerequisites
| Tool | Version |
|---|---|
| Python |	3.11+ |
| Node.js | 20+ |
| npm	 | comes with Node |


Option A — Quick local run (fastest)
The repo includes trained models and data artifacts, so you usually don’t need to retrain.

1. Clone

git clone https://github.com/sakshisaini24/RiskRadar.git
cd RiskRadar

2. Backend (API)

# Windows
python -m venv venv
venv\Scripts\activate
# macOS/Linux
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

3. Environment (optional)

copy .env.example .env    # Windows
# cp .env.example .env    # macOS/Linux
Edit .env if you want AI briefs or Salesforce:

GROQ_API_KEY — recommended for LLM briefs
GEMINI_API_KEY — optional (or set GEMINI_ENABLED=false)
SALESFORCE_WEBHOOK_SECRET — only if using Salesforce integration

4. Start API

python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
API docs: http://127.0.0.1:8000/docs

5. Frontend (new terminal)

cd frontend
npm install
npm run dev
Open: http://localhost:3000

The frontend talks to the API at http://127.0.0.1:8000 by default.

Option B — Full rebuild (retrain models from data)


pip install -r requirements.txt
python run_pipeline.py
python -m models.train_model_a
python -m models.train_model_b
python -m models.fit_calibrator
python -m models.train_time_to_escalation
python -m models.build_claim_index    # ~30s
python -m models.evaluate
Then start API + frontend as in Option A.

Option C — Docker (API + frontend in one container)

git clone https://github.com/sakshisaini24/RiskRadar.git
cd RiskRadar
docker build -f DockerFile -t riskradar .
docker run -p 8080:8080 --env-file .env riskradar
Open: http://localhost:8080

Live demo (hosted)
https://riskradar-2-mjr7.onrender.com

(Render free tier may sleep; first load can take ~30s.)

You can paste this as-is into email/Slack. If you want a shorter “3-step” version for judges, say the word and I’ll trim it.


