import json
import os
import re
from typing import Any, Dict, Optional

import pandas as pd
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
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
from api.action_plan import generate_action_plan, extract_from_brief
from api.consensus_analysis import analyze_consensus
from api.risk_calibrator import calibrate_risk
from api.time_to_escalation import predict_timeline, model_stats as tte_stats
from api.similar_claims import find_similar, index_stats as sim_stats
from api.fairness import compute as compute_fairness
from api.feedback import FeedbackPayload, record as record_feedback, summary as feedback_summary, for_claim as feedback_for_claim
from api.drift import compute as compute_drift
from api.external_claims import (
    combined_text,
    get as get_external_claim,
    list_all as list_external_claims,
    reload_from_disk,
)
from api.sf_scoring import build_feature_row
from api.integrations.salesforce import (
    ingest_from_webhook,
    pull_open_cases,
    verify_webhook_secret,
)

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
        "external_claims": len(list_external_claims()),
    }


@app.on_event("startup")
async def _startup():
    reload_from_disk()
    print("[startup] Computing CALIBRATED model validation metrics...")
    try:
        compute_metrics(
            ensemble, STRUCTURED_DATA, threshold=50.0,
            unstructured_df=UNSTRUCTURED_DATA, genai_df=GENAI_DATA,
        )
    except Exception as e:
        print(f"[startup] Metrics computation failed: {e}")

    if os.getenv("SF_SYNC_ON_STARTUP", "").lower() in ("1", "true", "yes"):
        try:
            ids, err = pull_open_cases(limit=int(os.getenv("SF_SYNC_LIMIT", "25")))
            if err:
                print(f"[startup] SF sync skipped: {err}")
            else:
                print(f"[startup] SF sync restored {len(ids)} open case(s)")
        except Exception as e:
            print(f"[startup] SF sync failed: {e}")


def get_unstructured_for_claim(claim_id):
    cid = str(claim_id).strip()
    ext = get_external_claim(cid)
    if ext:
        return {
            "incident_description": ext.get("incident_description") or "",
            "adjuster_notes": ext.get("adjuster_notes") or "",
            "email_transcript": ext.get("email_transcript") or "",
            "source": "salesforce",
            "salesforce_case_id": ext.get("salesforce_case_id"),
            "salesforce_case_number": ext.get("salesforce_case_number"),
            "claimant_name": ext.get("claimant_name"),
            "age": ext.get("age"),
            "marital_status": ext.get("marital_status"),
            "activities": ext.get("activities") or [],
            "activities_count": len(ext.get("activities") or []),
        }

    if UNSTRUCTURED_DATA.empty:
        return None
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
        "source": "dataset",
    }


def _score_claim(cid: str, email_text: str = "", adjuster_text: str = "", genai_df=None):
    raw = ensemble.get_risk_score(cid)
    if not raw:
        ext = get_external_claim(cid)
        if ext:
            text = combined_text(ext)
            features = build_feature_row(ext)
            raw = ensemble.score_external(cid, text, features)
        else:
            return None, None, None
    triggers = detect_triggers(cid, email_text, adjuster_text, genai_df=genai_df)
    calibrated = calibrate_risk(raw, triggers, email_text, adjuster_text)
    return raw, triggers, calibrated


def _queue_row(row_dict: Dict[str, Any], source: str) -> Dict[str, Any]:
    cid = row_dict["claim_id"]
    email_text = row_dict.get("email_text", "")
    adjuster_text = row_dict.get("adjuster_text", "")
    risk, is_high = 0.0, False
    try:
        _, _, calibrated = _score_claim(cid, email_text, adjuster_text, genai_df=GENAI_DATA)
        if calibrated:
            risk = float(calibrated.get("risk_score_pct", 0))
            is_high = bool(calibrated.get("is_high_risk", False))
    except Exception as e:
        print(f"[claims] Error for {cid}: {e}")

    out = {
        "claim_id": cid,
        "claimant_name": row_dict.get("claimant_name", ""),
        "policy_type": row_dict.get("policy_type", ""),
        "incident_type": str(row_dict.get("incident_type", "")).strip("[]'\""),
        "days_open": int(row_dict.get("days_open") or 0),
        "total_claimed": float(row_dict.get("total_claimed") or 0),
        "state": row_dict.get("state", ""),
        "risk_score_pct": round(risk, 2),
        "is_high_risk": is_high,
        "source": source,
    }
    if source == "salesforce":
        out["salesforce_case_id"] = row_dict.get("salesforce_case_id")
        out["salesforce_case_number"] = row_dict.get("salesforce_case_number")
    return out


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


@app.post("/integrations/salesforce/webhook")
async def salesforce_webhook(
    request: Request,
    x_riskradar_secret: Optional[str] = Header(None, alias="X-RiskRadar-Secret"),
):
    """Inbound from Salesforce when a Case is created or updated."""
    if not verify_webhook_secret(x_riskradar_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON body required")
    try:
        result = ingest_from_webhook(body)
        PREDICT_CACHE.pop(result["claim_id"], None)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/integrations/salesforce/sync")
async def salesforce_sync(limit: int = 20):
    """Pull open Cases via Salesforce REST (optional)."""
    ids, err = pull_open_cases(limit=limit)
    if err:
        raise HTTPException(status_code=503, detail=err)
    for cid in ids:
        PREDICT_CACHE.pop(cid, None)
    return {"status": "ok", "ingested": len(ids), "claim_ids": ids}


@app.get("/integrations/salesforce/status")
async def salesforce_status():
    ext = list_external_claims()
    return {
        "external_claim_count": len(ext),
        "webhook_secret_configured": bool(os.getenv("SALESFORCE_WEBHOOK_SECRET")),
        "oauth_configured": bool(os.getenv("SF_REFRESH_TOKEN")),
        "recent": [
            {
                "claim_id": c["claim_id"],
                "salesforce_case_id": c.get("salesforce_case_id"),
                "salesforce_case_number": c.get("salesforce_case_number"),
            }
            for c in ext[:5]
        ],
    }


@app.get("/claims")
async def claims_list():
    """Dataset claims + Salesforce-ingested claims."""
    claims = []
    seen = set()

    if not STRUCTURED_DATA.empty:
        for _, row in STRUCTURED_DATA.iterrows():
            cid = str(row.get("claim_id"))
            seen.add(cid)
            email_text, adjuster_text = "", ""
            if not UNSTRUCTURED_DATA.empty:
                u = UNSTRUCTURED_DATA[UNSTRUCTURED_DATA["Claim ID"] == cid]
                if not u.empty:
                    email_text = str(u.iloc[0].get("Email Transcript — Claimant (Unstructured)", "") or "")
                    adjuster_text = str(u.iloc[0].get("Adjuster Field Notes (Unstructured)", "") or "")
            claims.append(_queue_row({
                "claim_id": cid,
                "claimant_name": str(row.get("claimant_name", "") or ""),
                "policy_type": str(row.get("policy_type", "") or ""),
                "incident_type": row.get("incident_type", ""),
                "days_open": row.get("days_open", 0),
                "total_claimed": row.get("total_claimed", 0),
                "state": str(row.get("state", "") or ""),
                "email_text": email_text,
                "adjuster_text": adjuster_text,
            }, "dataset"))

    for ext in list_external_claims():
        cid = str(ext["claim_id"])
        if cid in seen:
            continue
        seen.add(cid)
        claims.append(_queue_row({
            "claim_id": cid,
            "claimant_name": ext.get("claimant_name") or "Salesforce Case",
            "policy_type": ext.get("policy_type") or "Unknown",
            "incident_type": ext.get("incident_type") or "insurance",
            "days_open": ext.get("days_open") or 0,
            "total_claimed": ext.get("total_claimed") or 0,
            "state": ext.get("state") or "",
            "email_text": ext.get("email_transcript") or "",
            "adjuster_text": ext.get("adjuster_notes") or "",
            "salesforce_case_id": ext.get("salesforce_case_id"),
            "salesforce_case_number": ext.get("salesforce_case_number"),
        }, "salesforce"))

    claims.sort(key=lambda c: c["risk_score_pct"], reverse=True)
    total = len(claims)
    sf_count = sum(1 for c in claims if c.get("source") == "salesforce")

    return {
        "claims": claims,
        "total": total,
        "high_risk_count": sum(1 for c in claims if c["is_high_risk"]),
        "avg_risk": round(sum(c["risk_score_pct"] for c in claims) / total, 2) if total else 0,
        "avg_days_open": round(sum(c["days_open"] for c in claims) / total, 1) if total else 0,
        "salesforce_count": sf_count,
    }


@app.get("/predict/{claim_id}")
async def get_prediction(claim_id: str):
    claim_id = str(claim_id).strip()

    if claim_id in PREDICT_CACHE:
        return PREDICT_CACHE[claim_id]

    unstructured = get_unstructured_for_claim(claim_id)
    email_text = unstructured.get("email_transcript", "") if unstructured else ""
    adjuster_text = unstructured.get("adjuster_notes", "") if unstructured else ""

    _, triggers, results = _score_claim(
        claim_id, email_text, adjuster_text, genai_df=GENAI_DATA
    )
    if not results:
        raise HTTPException(status_code=404, detail="Claim not found")

    incident = "insurance"
    ext = get_external_claim(claim_id)
    if ext:
        incident = str(ext.get("incident_type") or "insurance").strip("[]'\"")
    elif not STRUCTURED_DATA.empty:
        match = STRUCTURED_DATA[STRUCTURED_DATA["claim_id"] == claim_id]
        if not match.empty:
            incident = str(match.iloc[0].get("incident_type", "insurance")).strip("[]'\"")

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

    brief_for_plan = (
        ai_consensus_briefs.get("groq_llama")
        or ai_consensus_briefs.get("google_gemini")
        or ""
    )
    brief_ok = bool(
        brief_for_plan
        and "error:" not in str(brief_for_plan).lower()
        and "key missing" not in str(brief_for_plan).lower()
    )

    recommended_actions = generate_action_plan(
        claim_id=claim_id,
        risk_pct=risk_pct,
        is_high_risk=is_high_risk,
        incident=incident,
        trigger_phrases=trigger_phrases,
        top_warnings=top_warnings,
        brief_text=brief_for_plan if brief_ok else "",
    )
    if not recommended_actions.get("steps"):
        fallback = extract_from_brief(ai_consensus_briefs.get("groq_llama"))
        if not fallback:
            fallback = extract_from_brief(ai_consensus_briefs.get("google_gemini"))
        if fallback:
            recommended_actions = {"steps": fallback, "source": "brief"}

    timeline = predict_timeline(claim_id)
    similar = find_similar(claim_id, top_k=5)

    response = {
        "claim_id": claim_id,
        "source": (unstructured or {}).get("source", "dataset"),
        "salesforce_case_id": (unstructured or {}).get("salesforce_case_id"),
        "salesforce_case_number": (unstructured or {}).get("salesforce_case_number"),
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
        "recommended_actions": recommended_actions,
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