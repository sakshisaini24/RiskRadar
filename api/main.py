import json
import os
import re
import pandas as pd
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from dotenv import load_dotenv

from models.ensemble import RiskRadarEnsemble
from api.kanoon import KanoonClient
from api.brief import BriefGenerator
from api.us_case_laws import USLawClient
from api.metrics import compute_metrics, get_metrics, get_holdout_scores
from api.trigger_phrases import detect_triggers
from api.next_action import generate_emails
from api.consensus_analysis import analyze_consensus
from api.risk_calibrator import calibrate_risk
from api.time_to_escalation import predict_timeline, model_stats as tte_stats
from api.similar_claims import find_similar, index_stats as sim_stats
from api.fairness import compute as compute_fairness
from api.feedback import FeedbackPayload, record as record_feedback, summary as feedback_summary, for_claim as feedback_for_claim
from api.drift import compute as compute_drift

load_dotenv()

app = FastAPI(title="RiskRadar AI API v2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ensemble = RiskRadarEnsemble()
kanoon = KanoonClient()
us_law = USLawClient()
ai_factory = BriefGenerator()

LEGAL_CACHE = {}
PREDICT_CACHE = {}

try:
    STRUCTURED_DATA = pd.read_csv("data/processed/structured_clean.csv")
    if "claim_id" in STRUCTURED_DATA.columns:
        STRUCTURED_DATA["claim_id"] = STRUCTURED_DATA["claim_id"].astype(str).str.strip()
    print(f"[Structured] Loaded {len(STRUCTURED_DATA)} rows")
except Exception as e:
    print(f"[Structured] Failed: {e}")
    STRUCTURED_DATA = pd.DataFrame()

UNSTRUCTURED_PATH = "data/raw/RiskRadar_AI_Dataset__2___1_.xlsx"
try:
    UNSTRUCTURED_DATA = pd.read_excel(UNSTRUCTURED_PATH, sheet_name="Unstructured Data", header=1)
    if "Claim ID" in UNSTRUCTURED_DATA.columns:
        UNSTRUCTURED_DATA["Claim ID"] = UNSTRUCTURED_DATA["Claim ID"].astype(str).str.strip()
    print(f"[Unstructured] Loaded {len(UNSTRUCTURED_DATA)} rows")
except Exception as e:
    print(f"[Unstructured] Failed: {e}")
    UNSTRUCTURED_DATA = pd.DataFrame()

try:
    GENAI_DATA = pd.read_excel(UNSTRUCTURED_PATH, sheet_name="GenAI Intelligence Layer", header=1)
    if "Claim ID" in GENAI_DATA.columns:
        GENAI_DATA["Claim ID"] = GENAI_DATA["Claim ID"].astype(str).str.strip()
    print(f"[GenAI] Loaded {len(GENAI_DATA)} rows")
except Exception as e:
    print(f"[GenAI] Failed: {e}")
    GENAI_DATA = pd.DataFrame()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "structured_rows": len(STRUCTURED_DATA) if not STRUCTURED_DATA.empty else 0,
    }


@app.on_event("startup")
async def _startup():
    print("[startup] Computing CALIBRATED model validation metrics...")
    try:
        compute_metrics(
            ensemble, STRUCTURED_DATA, threshold=50.0,
            unstructured_df=UNSTRUCTURED_DATA, genai_df=GENAI_DATA,
        )
    except Exception as e:
        print(f"[startup] Metrics computation failed: {e}")


def get_unstructured_for_claim(claim_id):
    if UNSTRUCTURED_DATA.empty:
        return None
    cid = str(claim_id).strip()
    match = UNSTRUCTURED_DATA[UNSTRUCTURED_DATA["Claim ID"] == cid]
    if match.empty:
        return None
    row = match.iloc[0]

    def clean(v):
        if pd.isna(v):
            return ""
        return str(v).replace("\\n", "\n").strip()

    return {
        "incident_description": clean(row.get("Accident / Incident Description (Unstructured)")),
        "adjuster_notes": clean(row.get("Adjuster Field Notes (Unstructured)")),
        "email_transcript": clean(row.get("Email Transcript — Claimant (Unstructured)")),
    }


def get_legal_context(incident, trigger_phrases=None, top_warnings=None):
    if incident in LEGAL_CACHE:
        return LEGAL_CACHE[incident]

    in_cases, in_status = [], "ok"
    try:
        in_cases = kanoon.search_precedents(incident, "") or []
        for c in in_cases:
            c["jurisdiction"] = "India"
            c["headline"] = re.sub("<[^<]+?>", "", c.get("headline", "") or "")
        if not in_cases:
            in_status = "empty"
    except Exception as e:
        print(f"[Kanoon] Exception: {e}")
        in_status = "error"

    us_cases, us_status, matched_query = us_law.search_us_precedents_matched(
        incident, trigger_phrases, top_warnings
    )
    us_spotlight_description = us_law.generate_case_brief(us_cases[0]) if us_cases else None

    result = {
        "in_cases": in_cases,
        "in_status": in_status,
        "us_cases": us_cases,
        "us_status": us_status,
        "us_spotlight_description": us_spotlight_description,
        "matched_query": matched_query,
    }
    LEGAL_CACHE[incident] = result
    return result


@app.get("/metrics")
async def metrics_endpoint():
    base = get_metrics()
    base["time_to_escalation"] = tte_stats()
    base["similarity_index"] = sim_stats()
    return base


@app.get("/metrics/holdout_scores")
async def holdout_scores_endpoint():
    """Raw (y_true, calibrated_prob) arrays for the UI threshold slider."""
    return get_holdout_scores()


@app.get("/fairness")
async def fairness_endpoint(threshold: float = 50.0):
    """Recall/precision stratified by state, age bucket, policy type."""
    return compute_fairness(threshold=threshold)


@app.post("/feedback")
async def feedback_submit(payload: FeedbackPayload):
    """Record an adjuster's agreement/disagreement with the model."""
    return record_feedback(payload)


@app.get("/feedback/summary")
async def feedback_summary_endpoint():
    """Aggregate disagreement rate + recent events for the dashboard badge."""
    return feedback_summary()


@app.get("/feedback/claim/{claim_id}")
async def feedback_for_claim_endpoint(claim_id: str):
    return {"claim_id": claim_id, "events": feedback_for_claim(claim_id)}


@app.get("/drift")
async def drift_endpoint():
    """Population stability index (PSI) per monitored feature."""
    return compute_drift()


@app.get("/similar/{claim_id}")
async def similar_endpoint(claim_id: str, top_k: int = 5):
    result = find_similar(claim_id, top_k=top_k)
    if result is None:
        raise HTTPException(status_code=404,
                            detail="Claim not found or similarity index unavailable")
    return result


EVAL_DIR = "data/features/eval"


@app.get("/evaluation/report")
async def evaluation_report():
    """Full holdout evaluation: full / adversarial_text / structured_only scenarios."""
    path = os.path.join(EVAL_DIR, "eval_report.json")
    if not os.path.exists(path):
        return {"status": "missing", "note": "Run `py -m models.evaluate` to generate."}
    with open(path) as f:
        return {"status": "ok", **json.load(f)}


@app.get("/evaluation/plot/{name}")
async def evaluation_plot(name: str):
    """Serve one of the generated evaluation PNGs."""
    allowed = {"calibration_curve", "pr_curve", "lift_chart", "confusion_matrices"}
    if name not in allowed:
        raise HTTPException(status_code=404, detail="Unknown plot")
    path = os.path.join(EVAL_DIR, f"{name}.png")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Plot not generated")
    return FileResponse(path, media_type="image/png")


@app.get("/claims")
async def claims_list():
    """Queue list — uses calibrated scores so the rankings match the detail view."""
    if STRUCTURED_DATA.empty:
        return {"claims": [], "total": 0}

    claims = []
    for _, row in STRUCTURED_DATA.iterrows():
        cid = row.get("claim_id")
        risk = 0.0
        is_high = False
        try:
            raw = ensemble.get_risk_score(cid)
            if raw:
                # Get unstructured for calibration
                email_text, adjuster_text, triggers = "", "", None
                if not UNSTRUCTURED_DATA.empty:
                    u = UNSTRUCTURED_DATA[UNSTRUCTURED_DATA["Claim ID"] == cid]
                    if not u.empty:
                        email_text = str(u.iloc[0].get("Email Transcript — Claimant (Unstructured)", "") or "")
                        adjuster_text = str(u.iloc[0].get("Adjuster Field Notes (Unstructured)", "") or "")
                        triggers = detect_triggers(cid, email_text, adjuster_text, genai_df=GENAI_DATA)

                calibrated = calibrate_risk(raw, triggers, email_text, adjuster_text)
                risk = float(calibrated.get("risk_score_pct", 0))
                is_high = bool(calibrated.get("is_high_risk", False))
        except Exception as e:
            print(f"[claims] Error for {cid}: {e}")

        claims.append({
            "claim_id": cid,
            "claimant_name": str(row.get("claimant_name", row.get("Claimant Name", "")) or ""),
            "policy_type": str(row.get("policy_type", row.get("Policy Type", "")) or ""),
            "incident_type": str(row.get("incident_type", row.get("Incident Type", "")) or "").strip("[]'\""),
            "days_open": int(row.get("days_open", row.get("Days Open", 0)) or 0),
            "total_claimed": float(row.get("total_claimed", row.get("Total Claimed ($)", 0)) or 0),
            "state": str(row.get("state", row.get("State", "")) or ""),
            "risk_score_pct": round(risk, 2),
            "is_high_risk": is_high,
        })

    claims.sort(key=lambda c: c["risk_score_pct"], reverse=True)

    total = len(claims)
    high_risk_count = sum(1 for c in claims if c["is_high_risk"])
    avg_risk = sum(c["risk_score_pct"] for c in claims) / total if total else 0
    avg_days = sum(c["days_open"] for c in claims) / total if total else 0

    return {
        "claims": claims,
        "total": total,
        "high_risk_count": high_risk_count,
        "avg_risk": round(avg_risk, 2),
        "avg_days_open": round(avg_days, 1),
    }


@app.get("/predict/{claim_id}")
async def get_prediction(claim_id: str):
    claim_id = str(claim_id).strip()

    if claim_id in PREDICT_CACHE:
        return PREDICT_CACHE[claim_id]

    raw_results = ensemble.get_risk_score(claim_id)
    if not raw_results:
        raise HTTPException(status_code=404, detail="Claim not found")

    incident = "insurance"
    if not STRUCTURED_DATA.empty:
        match = STRUCTURED_DATA[STRUCTURED_DATA["claim_id"] == claim_id]
        if not match.empty:
            incident = str(match.iloc[0].get("incident_type", "insurance")).strip("[]'\"")

    unstructured = get_unstructured_for_claim(claim_id)

    triggers = None
    if unstructured:
        triggers = detect_triggers(
            claim_id,
            unstructured.get("email_transcript", ""),
            unstructured.get("adjuster_notes", ""),
            genai_df=GENAI_DATA,
        )

    # CALIBRATE the risk score using both structured + unstructured signal
    email_text = unstructured.get("email_transcript", "") if unstructured else ""
    adjuster_text = unstructured.get("adjuster_notes", "") if unstructured else ""
    results = calibrate_risk(raw_results, triggers, email_text, adjuster_text)

    risk_pct = float(results.get("risk_score_pct", 0))
    is_high_risk = bool(results.get("is_high_risk", False))
    top_warnings = results.get("top_warning_signs", []) or []
    trigger_phrases = triggers.get("phrases", []) if triggers else []

    legal = get_legal_context(incident, trigger_phrases, top_warnings)
    all_precedents = legal["in_cases"] + legal["us_cases"]

    ai_consensus_briefs = ai_factory.generate_all(results, all_precedents)

    consensus = analyze_consensus(
        ai_consensus_briefs.get("groq_llama"),
        ai_consensus_briefs.get("google_gemini"),
        risk_pct,
    )

    next_action_emails = generate_emails(
        claim_id=claim_id,
        risk_pct=risk_pct,
        is_high_risk=is_high_risk,
        incident=incident,
        trigger_phrases=trigger_phrases,
        top_warnings=top_warnings,
        email_excerpt=email_text,
    )

    timeline = predict_timeline(claim_id)
    similar = find_similar(claim_id, top_k=5)

    response = {
        "claim_id": claim_id,
        "ml_analysis": results,
        "timeline": timeline,
        "similar_claims": similar,
        "legal_context": {
            "incident_type": incident,
            "precedents": all_precedents,
            "us_search_status": legal["us_status"],
            "india_search_status": legal["in_status"],
            "us_spotlight_description": legal["us_spotlight_description"],
            "matched_query": legal.get("matched_query"),
        },
        "ai_consensus": ai_consensus_briefs,
        "consensus_analysis": consensus,
        "communication_audit": unstructured,
        "trigger_analysis": triggers,
        "next_action_emails": next_action_emails,
    }

    PREDICT_CACHE[claim_id] = response
    return response


@app.post("/cache/clear")
async def clear_cache():
    LEGAL_CACHE.clear()
    PREDICT_CACHE.clear()
    return {"status": "cleared"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)