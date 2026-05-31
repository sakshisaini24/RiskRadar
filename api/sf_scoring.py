"""
Build a scoring payload for Salesforce-ingested claims.

Dataset claims use the full feature_matrix. External claims approximate
Model A inputs from SF Case fields + use Model B on activity text.
"""
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

FEATURE_MATRIX = "data/features/feature_matrix.csv"
STRUCTURED = "data/processed/structured_clean.csv"

_MEDIANS: Optional[pd.Series] = None
_CAT_DEFAULTS: Optional[Dict[str, int]] = None


def _load_medians():
    global _MEDIANS, _CAT_DEFAULTS
    if _MEDIANS is not None:
        return
    try:
        fm = pd.read_csv(FEATURE_MATRIX)
        num = fm.drop(columns=["claim_id", "target"], errors="ignore")
        _MEDIANS = num.median(numeric_only=True)
        _CAT_DEFAULTS = {}
        for col in [c for c in num.columns if c.endswith("_enc")]:
            _CAT_DEFAULTS[col] = int(fm[col].mode().iloc[0]) if not fm[col].mode().empty else 0
    except Exception:
        _MEDIANS = pd.Series(dtype=float)
        _CAT_DEFAULTS = {}


def _encode_like_training(value: str, field: str) -> int:
    """Best-effort label encoding using training CSV unique values."""
    try:
        df = pd.read_csv(STRUCTURED)
        col = field.replace("_enc", "")
        if col not in df.columns:
            return 0
        classes = sorted(df[col].astype(str).unique().tolist())
        val = str(value or "").strip()
        if val in classes:
            return classes.index(val)
        val_lower = val.lower()
        for i, c in enumerate(classes):
            if val_lower in str(c).lower() or str(c).lower() in val_lower:
                return i
        return 0
    except Exception:
        return 0


def build_feature_row(ext: Dict[str, Any]) -> Dict[str, float]:
    """Map external claim → Model A feature vector (median defaults + SF overrides)."""
    _load_medians()
    row = _MEDIANS.to_dict() if _MEDIANS is not None else {}

    total = float(ext.get("total_claimed") or 0)
    offer = float(ext.get("insurer_offer") or 0)
    gap = float(ext.get("settlement_gap_pct") or 0)
    if gap == 0 and total > 0 and offer >= 0:
        gap = max(0.0, (total - offer) / total * 100)

    days_open = int(ext.get("days_open") or 0)
    followup = int(ext.get("followup_contacts") or 0)
    docs = int(ext.get("doc_requests") or 0)
    disputed = int(ext.get("disputed_items") or 0)
    inspections = int(ext.get("inspections") or 0)
    tenure = float(ext.get("policy_tenure_yrs") or 0)
    doi = int(ext.get("doi_complaint") or 0)

    legal_rep = str(ext.get("legal_rep") or "")
    has_legal = 1 if any(k in legal_rep.lower() for k in ("attorney", "lawyer", "legal", "litigation")) else 0
    adj_level = str(ext.get("adjuster_level") or "")

    overrides = {
        "days_open": days_open,
        "log_claim_amount": float(np.log1p(total)),
        "offer_to_claim_ratio": min(1.0, offer / total) if total > 0 else 0.0,
        "settlement_gap_pct": gap,
        "large_settlement_gap": 1 if gap > 40 else 0,
        "dispute_density": followup + docs + disputed + inspections * 2,
        "legal_pressure_index": doi * 3,
        "has_legal_rep": has_legal,
        "is_junior_adjuster": 1 if "junior" in adj_level.lower() else 0,
        "short_tenure": 1 if 0 < tenure < 2 else 0,
        "policy_tenure_yrs": tenure,
        "followup_contacts": followup,
        "doc_requests": docs,
        "disputed_items": disputed,
        "inspections": inspections,
        "claim_age_bucket": _age_bucket(days_open),
    }
    row.update({k: v for k, v in overrides.items() if k in row or True})

    for enc_field, src in [
        ("policy_type_enc", ext.get("policy_type")),
        ("incident_type_enc", ext.get("incident_type")),
        ("injury_severity_enc", ext.get("injury_severity") or "Unknown"),
        ("adjuster_level_enc", ext.get("adjuster_level") or "Mid-Level"),
        ("payment_status_enc", ext.get("payment_status") or "Pending"),
    ]:
        row[enc_field] = _encode_like_training(str(src or ""), enc_field)

    if _CAT_DEFAULTS:
        for k, v in _CAT_DEFAULTS.items():
            row.setdefault(k, v)

    return row


def _age_bucket(days_open: int) -> float:
    if days_open <= 30:
        return 0.0
    if days_open <= 90:
        return 1.0
    if days_open <= 180:
        return 2.0
    if days_open <= 365:
        return 3.0
    return 4.0
