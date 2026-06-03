"""Seed open, high-risk demo cases for finals (no adjuster action taken yet)."""
from api.external_claims import get, upsert

DEMO_CLAIM_IDS = ("SF-DEMO-2001", "SF-DEMO-2002", "SF-DEMO-2003")


def _demo_payloads():
    return [
        {
            "claim_id": "SF-DEMO-2001",
            "salesforce_case_id": "500DEMO2001",
            "salesforce_case_number": "DEMO-2001",
            "claimant_name": "Linda Moore",
            "age": 74,
            "marital_status": "Divorced",
            "policy_type": "Liability",
            "incident_type": "Vehicle Theft",
            "injury_severity": "Moderate Laceration",
            "state": "NY",
            "days_open": 142,
            "total_claimed": 333692,
            "insurer_offer": 110447,
            "settlement_gap_pct": 66.9,
            "policy_tenure_yrs": 22,
            "followup_contacts": 8,
            "doc_requests": 5,
            "disputed_items": 6,
            "inspections": 5,
            "legal_rep": "Attorney retained — demand letter sent",
            "adjuster_level": "Mid-Level",
            "payment_status": "Disputed",
            "doi_complaint": 0,
            "claim_status": "Open",
            "action_status": "No action taken",
            "incident_description": (
                "On 2024-03-08, claimant Linda Moore reported theft of vehicle from a "
                "retail parking lot in New York. Her 2022 Ford Explorer was stolen while "
                "she was shopping; NYPD precinct report #2024-VT-1187 was filed the same day. "
                "Police report submitted. GPS data provided by claimant supports the vehicle "
                "was taken from the lot. Comprehensive claim filed under Liability policy for "
                "vehicle replacement value of $333,692 plus personal property removed with the "
                "vehicle. Insurer requested additional documentation including proof of ownership "
                "history, keys, and title, which claimant provided within 10 days. Some delay in "
                "processing has occurred due to SIU review flag for high claimed value vs regional "
                "vehicle theft baseline. Insurer offer of $110,447 leaves a 67% settlement gap. "
                "Independent appraiser replacement-cost estimate is substantially higher than "
                "insurer ACV calculation. Claimant sustained Moderate Laceration at the scene "
                "documented in ER visit records."
            ),
            "email_transcript": (
                "From: linda.moore@email.com\n"
                "Subject: Final notice before legal action — stolen vehicle Claim SF-DEMO-2001\n\n"
                "My vehicle was stolen from the retail parking lot and your offer does not reflect "
                "the replacement cost documented in the police report and independent appraisal. "
                "I have retained legal counsel. Your offer is unacceptable. If I do not hear from "
                "a supervisor within 48 hours I will proceed with litigation. This delay is causing "
                "severe financial hardship."
            ),
            "adjuster_notes": (
                "Vehicle theft file — liability coverage. Police report and GPS ping log on file. "
                "Claim open 142 days. High settlement gap on stolen vehicle ACV vs claimant "
                "replacement-cost demand. Attorney on file; demand letter received. Claimant "
                "hostile on last call regarding repeated theft documentation requests. Multiple "
                "proof-of-ownership submissions completed. No senior review scheduled yet. "
                "Recommend immediate escalation review."
            ),
            "activities": [
                {
                    "type": "email",
                    "subject": "Final notice before legal action",
                    "body": "Retained attorney. Proceeding with litigation if no response.",
                    "incoming": True,
                },
                {
                    "type": "call",
                    "subject": "Outbound — offer discussion",
                    "body": "Claimant refused offer; requested supervisor callback.",
                },
            ],
        },
        {
            "claim_id": "SF-DEMO-2002",
            "salesforce_case_id": "500DEMO2002",
            "salesforce_case_number": "DEMO-2002",
            "claimant_name": "James Rivera",
            "age": 58,
            "marital_status": "Married",
            "policy_type": "Health",
            "incident_type": "Medical Negligence",
            "injury_severity": "Fracture",
            "state": "CA",
            "days_open": 96,
            "total_claimed": 519750,
            "insurer_offer": 185000,
            "settlement_gap_pct": 64.4,
            "policy_tenure_yrs": 11,
            "followup_contacts": 12,
            "doc_requests": 9,
            "disputed_items": 4,
            "inspections": 2,
            "legal_rep": "Attorney",
            "adjuster_level": "Junior",
            "payment_status": "Denied",
            "doi_complaint": 1,
            "claim_status": "Open",
            "action_status": "No action taken",
            "incident_description": "Delayed treatment allegation. DOI complaint filed.",
            "email_transcript": (
                "I filed a complaint with the Department of Insurance. "
                "My attorney says you are acting in bad faith. "
                "I need a written response within 5 business days."
            ),
            "adjuster_notes": (
                "DOI complaint logged. Junior adjuster assigned — no supervisor touch yet. "
                "Medical records still disputed. No settlement authority increase."
            ),
            "activities": [
                {
                    "type": "email",
                    "subject": "DOI complaint reference",
                    "body": "Bad faith allegation. Attorney copied on all correspondence.",
                    "incoming": True,
                }
            ],
        },
        {
            "claim_id": "SF-DEMO-2003",
            "salesforce_case_id": "500DEMO2003",
            "salesforce_case_number": "DEMO-2003",
            "claimant_name": "Maria Santos",
            "age": 41,
            "marital_status": "Single",
            "policy_type": "Property",
            "incident_type": "Water Damage",
            "injury_severity": "No Injury",
            "state": "TX",
            "days_open": 67,
            "total_claimed": 287400,
            "insurer_offer": 72000,
            "settlement_gap_pct": 74.9,
            "policy_tenure_yrs": 6,
            "followup_contacts": 7,
            "doc_requests": 6,
            "disputed_items": 5,
            "inspections": 3,
            "legal_rep": "Public Adjuster",
            "adjuster_level": "Mid-Level",
            "payment_status": "Disputed",
            "doi_complaint": 0,
            "claim_status": "Open",
            "action_status": "No action taken",
            "incident_description": "Pipe burst caused major water damage. Public adjuster engaged.",
            "email_transcript": (
                "This is the third time I submitted the same documentation. "
                "I am frustrated and need a supervisor to review my file immediately. "
                "Your delays are unacceptable."
            ),
            "adjuster_notes": (
                "Repeated document submissions. Claimant frustrated. Public adjuster involved. "
                "No action plan logged in SF yet."
            ),
            "activities": [
                {
                    "type": "note",
                    "subject": "Internal note",
                    "body": "Awaiting triage — no outreach logged this week.",
                }
            ],
        },
    ]


def seed_demo_claims(force: bool = False) -> int:
    """Insert or refresh demo open cases. Returns count newly created."""
    created = 0
    for payload in _demo_payloads():
        cid = payload["claim_id"]
        if not get(cid):
            created += 1
        upsert(payload)
    if created:
        print(f"[demo] Seeded {created} open high-risk demo case(s): {', '.join(DEMO_CLAIM_IDS)}")
    else:
        print(f"[demo] Refreshed demo case fixtures ({len(DEMO_CLAIM_IDS)} cases)")
    return created
