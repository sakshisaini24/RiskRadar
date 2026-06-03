"""
Salesforce → RiskRadar webhook ingestion.

Recommended: Record-Triggered Flow on Case (create/update) → HTTP POST.
See docs/SALESFORCE_SETUP.md for full org configuration.
"""
import os
from typing import Any, Dict, List, Optional, Tuple

import requests

from api.external_claims import upsert

WEBHOOK_SECRET = os.getenv("SALESFORCE_WEBHOOK_SECRET", "")


def verify_webhook_secret(header_value: Optional[str]) -> bool:
    if not WEBHOOK_SECRET:
        return True
    return (header_value or "").strip() == WEBHOOK_SECRET.strip()


def normalize_webhook_payload(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Accept JSON from Salesforce Flow / Apex.

    Minimum:
      { "salesforce_case_id": "500...", "claim_id": "SF-00001234" }

    Recommended (matches RiskRadar dataset):
      subject, description, policy_type, incident_type, state, days_open,
      total_claimed, activities[{type, subject, body}]
    """
    sf_id = body.get("salesforce_case_id") or body.get("CaseId") or body.get("Id")
    case_num = body.get("salesforce_case_number") or body.get("CaseNumber")
    claim_id = body.get("claim_id")
    if not claim_id:
        if case_num:
            claim_id = f"SF-{case_num}"
        elif sf_id:
            claim_id = f"SF-{sf_id}"
    if not claim_id:
        raise ValueError("Provide claim_id, CaseNumber, or salesforce_case_id")

    return {
        "claim_id": str(claim_id).strip(),
        "salesforce_case_id": str(sf_id or "").strip(),
        "salesforce_case_number": str(case_num or "").strip(),
        "claimant_name": body.get("claimant_name") or body.get("ContactName") or body.get("Subject") or body.get("subject"),
        "age": body.get("age") or body.get("ContactAge"),
        "marital_status": body.get("marital_status") or body.get("Marital_Status__c"),
        "incident_description": body.get("incident_description") or body.get("Description") or body.get("description"),
        "email_transcript": body.get("email_transcript") or "",
        "adjuster_notes": body.get("adjuster_notes") or "",
        "policy_type": body.get("policy_type") or body.get("Policy_Type__c"),
        "incident_type": body.get("incident_type") or body.get("Type") or body.get("Reason"),
        "injury_severity": body.get("injury_severity") or body.get("Injury_Severity__c"),
        "state": body.get("state") or body.get("ContactState") or body.get("MailingState"),
        "days_open": body.get("days_open"),
        "total_claimed": body.get("total_claimed") or body.get("Total_Claimed__c"),
        "insurer_offer": body.get("insurer_offer") or body.get("Insurer_Offer__c"),
        "settlement_gap_pct": body.get("settlement_gap_pct") or body.get("Settlement_Gap__c"),
        "policy_tenure_yrs": body.get("policy_tenure_yrs") or body.get("Policy_Tenure_Yrs__c"),
        "followup_contacts": body.get("followup_contacts") or body.get("Followup_Contacts__c"),
        "doc_requests": body.get("doc_requests") or body.get("Doc_Requests__c"),
        "disputed_items": body.get("disputed_items") or body.get("Disputed_Items__c"),
        "inspections": body.get("inspections") or body.get("Inspections__c"),
        "legal_rep": body.get("legal_rep") or body.get("Legal_Rep__c"),
        "adjuster_level": body.get("adjuster_level") or body.get("Adjuster_Level__c"),
        "payment_status": body.get("payment_status") or body.get("Payment_Status__c"),
        "claim_status": body.get("claim_status") or body.get("Claim_Status__c") or "Open",
        "action_status": body.get("action_status") or body.get("Action_Status__c") or "",
        "doi_complaint": body.get("doi_complaint") or body.get("DOI_Complaint__c"),
        "activities": body.get("activities") or body.get("Activities") or [],
        "structured": body.get("structured") or {},
    }


def ingest_from_webhook(body: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_webhook_payload(body)
    stored = upsert(normalized)
    return {
        "status": "ok",
        "claim_id": stored["claim_id"],
        "salesforce_case_id": stored.get("salesforce_case_id"),
        "source": "salesforce",
    }


def _sf_token() -> Optional[str]:
    url = os.getenv("SF_INSTANCE_URL", "").rstrip("/")
    client_id = os.getenv("SF_CLIENT_ID")
    client_secret = os.getenv("SF_CLIENT_SECRET")
    refresh = os.getenv("SF_REFRESH_TOKEN")
    if not all([url, client_id, client_secret, refresh]):
        return None
    resp = requests.post(
        f"{url}/services/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("access_token")


def pull_open_cases(limit: int = 20) -> Tuple[List[str], Optional[str]]:
    """Optional REST pull when Flow is not ready."""
    base = os.getenv("SF_INSTANCE_URL", "").rstrip("/")
    token = _sf_token()
    if not token:
        return [], "SF OAuth not configured (SF_INSTANCE_URL, SF_CLIENT_ID, SF_CLIENT_SECRET, SF_REFRESH_TOKEN)"

    soql = (
        "SELECT Id, CaseNumber, Subject, Description, Type, Reason, "
        "Contact.Name, Contact.MailingState "
        f"FROM Case WHERE IsClosed = false ORDER BY CreatedDate DESC LIMIT {int(limit)}"
    )
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(
        f"{base}/services/data/v59.0/query",
        params={"q": soql},
        headers=headers,
        timeout=20,
    )
    r.raise_for_status()
    ingested = []
    for case in r.json().get("records") or []:
        contact = case.get("Contact") or {}
        payload = {
            "claim_id": f"SF-{case.get('CaseNumber') or case['Id']}",
            "salesforce_case_id": case["Id"],
            "salesforce_case_number": case.get("CaseNumber"),
            "claimant_name": contact.get("Name") or case.get("Subject"),
            "incident_description": case.get("Description") or "",
            "incident_type": case.get("Type") or case.get("Reason") or "insurance",
            "state": contact.get("MailingState") or "",
            "activities": [],
        }
        ingest_from_webhook(payload)
        ingested.append(payload["claim_id"])
    return ingested, None
