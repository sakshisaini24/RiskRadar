"""
Persist claims ingested from Salesforce.

Maps to RiskRadar dataset fields:
  structured  → structured_clean.csv columns (policy_type, days_open, total_claimed, …)
  unstructured → text_clean.csv (incident, adjuster notes, email transcript)
"""
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DB_PATH = os.getenv("EXTERNAL_CLAIMS_DB", "data/external_claims.db")


def _conn():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _ensure():
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS external_claims (
                claim_id TEXT PRIMARY KEY,
                salesforce_case_id TEXT,
                salesforce_case_number TEXT,
                claimant_name TEXT,
                age INTEGER,
                marital_status TEXT,
                policy_type TEXT,
                incident_type TEXT,
                injury_severity TEXT,
                state TEXT,
                days_open INTEGER DEFAULT 0,
                total_claimed REAL DEFAULT 0,
                insurer_offer REAL DEFAULT 0,
                settlement_gap_pct REAL DEFAULT 0,
                policy_tenure_yrs REAL DEFAULT 0,
                followup_contacts INTEGER DEFAULT 0,
                doc_requests INTEGER DEFAULT 0,
                disputed_items INTEGER DEFAULT 0,
                inspections INTEGER DEFAULT 0,
                legal_rep TEXT,
                adjuster_level TEXT,
                payment_status TEXT,
                doi_complaint INTEGER DEFAULT 0,
                email_transcript TEXT,
                adjuster_notes TEXT,
                incident_description TEXT,
                activities_json TEXT,
                structured_json TEXT,
                raw_json TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )


_ensure()


def _migrate_columns(conn):
    """Add columns for older SQLite DBs without recreating the table."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(external_claims)")}
    for name, typedef in [("age", "INTEGER"), ("marital_status", "TEXT")]:
        if name not in existing:
            conn.execute(f"ALTER TABLE external_claims ADD COLUMN {name} {typedef}")


def _activities_to_text(payload: Dict[str, Any]) -> tuple[str, str]:
    """Split activities into email transcript vs adjuster notes."""
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
            prefix = f"[{kind.upper()}] "
            note_parts.append(prefix + block)

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
        "doi_complaint": int(payload.get("doi_complaint") or structured.get("doi_complaint") or 0),
        "email_transcript": email_transcript,
        "adjuster_notes": adjuster_notes,
        "incident_description": incident_description,
        "activities_json": json.dumps(payload.get("activities") or []),
        "structured_json": json.dumps(structured),
        "raw_json": json.dumps(payload),
        "updated_at": now,
    }

    with _conn() as conn:
        _migrate_columns(conn)
        conn.execute(
            """
            INSERT INTO external_claims (
                claim_id, salesforce_case_id, salesforce_case_number, claimant_name,
                age, marital_status,
                policy_type, incident_type, injury_severity, state, days_open,
                total_claimed, insurer_offer, settlement_gap_pct, policy_tenure_yrs,
                followup_contacts, doc_requests, disputed_items, inspections,
                legal_rep, adjuster_level, payment_status, doi_complaint,
                email_transcript, adjuster_notes, incident_description,
                activities_json, structured_json, raw_json, updated_at
            ) VALUES (
                :claim_id, :salesforce_case_id, :salesforce_case_number, :claimant_name,
                :age, :marital_status,
                :policy_type, :incident_type, :injury_severity, :state, :days_open,
                :total_claimed, :insurer_offer, :settlement_gap_pct, :policy_tenure_yrs,
                :followup_contacts, :doc_requests, :disputed_items, :inspections,
                :legal_rep, :adjuster_level, :payment_status, :doi_complaint,
                :email_transcript, :adjuster_notes, :incident_description,
                :activities_json, :structured_json, :raw_json, :updated_at
            )
            ON CONFLICT(claim_id) DO UPDATE SET
                salesforce_case_id=excluded.salesforce_case_id,
                salesforce_case_number=excluded.salesforce_case_number,
                claimant_name=excluded.claimant_name,
                age=excluded.age,
                marital_status=excluded.marital_status,
                policy_type=excluded.policy_type,
                incident_type=excluded.incident_type,
                injury_severity=excluded.injury_severity,
                state=excluded.state,
                days_open=excluded.days_open,
                total_claimed=excluded.total_claimed,
                insurer_offer=excluded.insurer_offer,
                settlement_gap_pct=excluded.settlement_gap_pct,
                policy_tenure_yrs=excluded.policy_tenure_yrs,
                followup_contacts=excluded.followup_contacts,
                doc_requests=excluded.doc_requests,
                disputed_items=excluded.disputed_items,
                inspections=excluded.inspections,
                legal_rep=excluded.legal_rep,
                adjuster_level=excluded.adjuster_level,
                payment_status=excluded.payment_status,
                doi_complaint=excluded.doi_complaint,
                email_transcript=excluded.email_transcript,
                adjuster_notes=excluded.adjuster_notes,
                incident_description=excluded.incident_description,
                activities_json=excluded.activities_json,
                structured_json=excluded.structured_json,
                raw_json=excluded.raw_json,
                updated_at=excluded.updated_at
            """,
            row,
        )
    return row


def get(claim_id: str) -> Optional[Dict[str, Any]]:
    cid = str(claim_id).strip()
    with _conn() as conn:
        cur = conn.execute("SELECT * FROM external_claims WHERE claim_id = ?", (cid,))
        r = cur.fetchone()
    if not r:
        return None
    d = dict(r)
    for key in ("activities_json", "structured_json", "raw_json"):
        try:
            parsed_key = key.replace("_json", "") if key != "raw_json" else "raw"
            if key == "activities_json":
                d["activities"] = json.loads(d.pop(key) or "[]")
            elif key == "structured_json":
                d["structured"] = json.loads(d.pop(key) or "{}")
            else:
                d.pop(key, None)
        except Exception:
            if key == "activities_json":
                d["activities"] = []
                d.pop(key, None)
    return d


def list_all() -> List[Dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT claim_id FROM external_claims ORDER BY updated_at DESC"
        ).fetchall()
    return [get(r["claim_id"]) for r in rows if get(r["claim_id"])]


def _optional_int(val) -> Optional[int]:
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def combined_text(row: Dict[str, Any]) -> str:
    parts = [
        row.get("incident_description") or "",
        row.get("email_transcript") or "",
        row.get("adjuster_notes") or "",
    ]
    return " ".join(p for p in parts if p).strip()
