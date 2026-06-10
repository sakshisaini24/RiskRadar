# Google Slides — Technology Stack (1 slide)

**Title:** Technology Stack  
**Subtitle:** End-to-end escalation intelligence — from labelled claims to production adjuster workflow

---

## Layout: 2 rows × 3 columns

### Machine Learning & Data
- Python 3.11 · Pandas · NumPy
- XGBoost (structured + text classifiers)
- scikit-learn (TF-IDF, Isotonic calibration, PSI)
- SHAP explainability · 29-feature matrix
- Time-to-escalation regressor (XGBoost)
- sentence-transformers (MiniLM-L6-v2, 550×384 index)

### AI & Language Layer
- Groq — Llama 3.1 / 3.3 (briefs, emails, actions)
- Google Gemini 2.5 Flash (second opinion)
- Temperature = 0 · citation-grounded prompts
- Trigger-phrase lexicon (rule-based NLP)
- RAG-style legal briefs with allowlist validation

### Backend API
- FastAPI + Uvicorn (REST)
- Pydantic · python-dotenv
- `/predict` · `/claims` · `/metrics` · `/feedback`
- Risk calibrator (64/28/8 blend)
- Similar-claims NN · drift · fairness endpoints

### Frontend
- Next.js 16 · React 19 · TypeScript
- Tailwind CSS 4
- Triage queue · single-claim deep dive
- Live ROI calculator · adjuster verdict UI
- ReactMarkdown for AI brief rendering

### Integrations & Legal Data
- Salesforce — Apex Case sync + REST webhook
- Indian Kanoon API (India precedents)
- CourtListener API (US case law)
- External claims store (SF + demo cases)

### Deploy & Persistence
- Docker (FastAPI + Next.js + nginx)
- Render (cloud web services)
- SQLite — adjuster feedback log
- joblib / JSON — trained model artifacts
- Excel/CSV — 550-claim labelled dataset

---

**Footer (one line):**  
*Core principle: ML scores the risk · LLMs explain and draft · humans decide · every legal citation is retrieved and validated*

---

## 20-second speaker note

> "We built on a modern but pragmatic stack: XGBoost and SHAP for explainable scoring, sentence-transformers for similar-claim lookup, Groq and Gemini for grounded briefs at temperature zero, FastAPI and Next.js for the product, and Salesforce plus Kanoon and CourtListener for real legal and workflow integration — all deployed on Render with Docker."
