"""
Persist claims ingested from Salesforce.

Uses a JSON file on disk (survives local restarts) plus optional SQLite legacy.
Paths are anchored to the project root so cwd does not matter.
"""
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Project root = parent of api/
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE_PATH = os.getenv(
    "EXTERNAL_CLAIMS_STORE",
    os.path.join(_ROOT, "data", "external_claims_store.json"),
)
DB_PATH = os.getenv(
    "EXTERNAL_CLAIMS_DB",
    os.path.join(_ROOT, "data", "external_claims.db"),
)

_STORE: Dict[str, Dict[str, Any]] = {}


def _ensure_data_dir():
    os.makedirs(os.path.dirname(STORE_PATH) or ".", exist_ok=True)


def _hydrate_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize stored row for API consumers."""
    d = dict(raw)
    if "activities_json" in d and "activities" not in d:
        try:
            d["activities"] = json.loads(d.get("activities_json") or "[]")
        except Exception:
            d["activities"] = []
        d.pop("activities_json", None)
    if "structured_json" in d and "structured" not in d:
        try:
            d["structured"] = json.loads(d.get("structured_json") or "{}")
        except Exception:
            d["structured"] = {}
        d.pop("structured_json", None)
    d.pop("raw_json", None)
    return d


def _load_json_store() -> Dict[str, Dict[str, Any]]:
    _ensure_data_dir()
    if not os.path.exists(STORE_PATH):
        return {}
    try:
        with open(STORE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return {str(r["claim_id"]): r for r in data if r.get("claim_id")}
        if isinstance(data, dict):
            return {str(k): v for k, v in data.items()}
    except Exception as e:
        print(f"[external_claims] Failed to load JSON store: {e}")
    return {}


def _save_json_store():
    _ensure_data_dir()
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_STORE, f, indent=2, default=str)
    os.replace(tmp, STORE_PATH)


def _migrate_sqlite_to_json():
    """One-time import if JSON empty but legacy SQLite has rows."""
    if _STORE or not os.path.exists(DB_PATH):
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM external_claims").fetchall()
        conn.close()
        for r in rows:
            rec = _hydrate_record(dict(r))
            cid = str(rec.get("claim_id", "")).strip()
            if cid:
                _STORE[cid] = rec
        if _STORE:
            _save_json_store()
            print(f"[external_claims] Migrated {len(_STORE)} claim(s) from SQLite → JSON")
    except Exception as e:
        print(f"[external_claims] SQLite migration skipped: {e}")


def reload_from_disk():
    """Call on startup to refresh in-memory store."""
    global _STORE
    _STORE = _load_json_store()
    _migrate_sqlite_to_json()
    print(f"[external_claims] Loaded {len(_STORE)} Salesforce claim(s) from {STORE_PATH}")


reload_from_disk()


def _activities_to_text(payload: Dict[str, Any]) -> tuple[str, str]:
    activities = payload.get("activities") or []
    if not isinstance(activities, list):
        activities = []

    email_parts: List[str] = []
    note_parts: List[str] = []

    for act in activities:
        if not isinstance(act, dict):
            continue
        kind = str(act.get("type") or act.get("Type") or "").lower()
        subject = str(act.get("subject") or act.get("Subject") or "")
        body = str(
            act.get("body")
            or act.get("TextBody")
            or act.get("summary")
            or act.get("Description")
            or act.get("description")
            or ""
        ).strip()
        block = f"{subject}\n{body}".strip() if subject else body
        if not block:
            continue
        if kind in ("email", "emailmessage"):
            email_parts.append(block)
        elif kind in ("call", "task", "note", "log"):
            note_parts.append(f"[{kind.upper()}] {block}")

    email = (payload.get("email_transcript") or "\n\n---\n\n".join(email_parts)).strip()
    notes = (payload.get("adjuster_notes") or "\n\n---\n\n".join(note_parts)).strip()
    return email, notes


def upsert(payload: Dict[str, Any]) -> Dict[str, Any]:
    claim_id = str(payload.get("claim_id") or "").strip()
    if not claim_id:
        raise ValueError("claim_id is required")

    email_transcript, adjuster_notes = _activities_to_text(payload)
    incident_description = str(
        payload.get("incident_description")
        or payload.get("description")
        or payload.get("Description")
        or ""
    ).strip()

    structured = payload.get("structured") or {}
    if not isinstance(structured, dict):
        structured = {}

    activities = payload.get("activities") or []
    now = datetime.now(timezone.utc).isoformat()

    row = {
        "claim_id": claim_id,
        "salesforce_case_id": str(
            payload.get("salesforce_case_id") or payload.get("case_id") or payload.get("Id") or ""
        ),
        "salesforce_case_number": str(
            payload.get("salesforce_case_number") or payload.get("CaseNumber") or ""
        ),
        "claimant_name": str(
            payload.get("claimant_name")
            or payload.get("ContactName")
            or payload.get("subject")
            or payload.get("Subject")
            or "Salesforce Case"
        ),
        "age": _optional_int(payload.get("age") or payload.get("Age") or payload.get("ContactAge")),
        "marital_status": str(payload.get("marital_status") or payload.get("Marital_Status__c") or ""),
        "policy_type": str(
            payload.get("policy_type") or structured.get("policy_type") or payload.get("Policy_Type__c") or "Unknown"
        ),
        "incident_type": str(
            payload.get("incident_type") or structured.get("incident_type") or payload.get("Type") or "insurance"
        ),
        "injury_severity": str(
            payload.get("injury_severity") or structured.get("injury_severity") or payload.get("Injury_Severity__c") or ""
        ),
        "state": str(payload.get("state") or structured.get("state") or payload.get("State") or ""),
        "days_open": int(payload.get("days_open") or structured.get("days_open") or 0),
        "total_claimed": float(payload.get("total_claimed") or structured.get("total_claimed") or payload.get("Total_Claimed__c") or 0),
        "insurer_offer": float(payload.get("insurer_offer") or structured.get("insurer_offer") or payload.get("Insurer_Offer__c") or 0),
        "settlement_gap_pct": float(payload.get("settlement_gap_pct") or structured.get("settlement_gap_pct") or 0),
        "policy_tenure_yrs": float(payload.get("policy_tenure_yrs") or structured.get("policy_tenure_yrs") or 0),
        "followup_contacts": int(payload.get("followup_contacts") or structured.get("followup_contacts") or 0),
        "doc_requests": int(payload.get("doc_requests") or structured.get("doc_requests") or 0),
        "disputed_items": int(payload.get("disputed_items") or structured.get("disputed_items") or 0),
        "inspections": int(payload.get("inspections") or structured.get("inspections") or 0),
        "legal_rep": str(payload.get("legal_rep") or structured.get("legal_rep") or ""),
        "adjuster_level": str(payload.get("adjuster_level") or structured.get("adjuster_level") or ""),
        "payment_status": str(payload.get("payment_status") or structured.get("payment_status") or ""),
        "claim_status": str(payload.get("claim_status") or structured.get("claim_status") or "Open"),
        "action_status": str(payload.get("action_status") or structured.get("action_status") or ""),
        "doi_complaint": int(payload.get("doi_complaint") or structured.get("doi_complaint") or 0),
        "email_transcript": email_transcript,
        "adjuster_notes": adjuster_notes,
        "incident_description": incident_description,
        "activities": activities,
        "updated_at": now,
    }

    _STORE[claim_id] = row
    _save_json_store()
    return row


def get(claim_id: str) -> Optional[Dict[str, Any]]:
    cid = str(claim_id).strip()
    rec = _STORE.get(cid)
    return _hydrate_record(rec) if rec else None


def list_all() -> List[Dict[str, Any]]:
    rows = sorted(_STORE.values(), key=lambda r: r.get("updated_at") or "", reverse=True)
    return [_hydrate_record(r) for r in rows]


def _optional_int(val) -> Optional[int]:
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def combined_text(row: Dict[str, Any]) -> str:
    parts = []
    incident_type = str(row.get("incident_type") or "").strip()
    if incident_type:
        parts.append(f"Incident type: {incident_type}.")
    parts.extend([
        row.get("incident_description") or "",
        row.get("email_transcript") or "",
        row.get("adjuster_notes") or "",
    ])
    return " ".join(p for p in parts if p).strip()
