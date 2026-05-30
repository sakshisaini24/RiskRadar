"""
Nearest-neighbour lookup over the claim embedding index.

Given a claim_id, returns the top-K most textually similar historical
claims along with their outcomes — so the adjuster can see how similar
profiles resolved. This is a huge trust signal: instead of a black-box
risk score, they see "5 of your 5 closest matches escalated."
"""
import os
from typing import Optional

import numpy as np
import pandas as pd

INDEX_NPZ = "data/features/claim_index.npz"
INDEX_META = "data/features/claim_index.csv"

_EMBEDS: Optional[np.ndarray] = None
_IDS: Optional[np.ndarray] = None
_META: Optional[pd.DataFrame] = None


def _load():
    global _EMBEDS, _IDS, _META
    if _EMBEDS is not None:
        return
    if not (os.path.exists(INDEX_NPZ) and os.path.exists(INDEX_META)):
        print("[similar_claims] Index missing — skip.")
        return
    try:
        bundle = np.load(INDEX_NPZ, allow_pickle=True)
        _EMBEDS = bundle["embeddings"]
        _IDS = bundle["claim_ids"].astype(str)
        _META = pd.read_csv(INDEX_META)
        _META["claim_id"] = _META["claim_id"].astype(str).str.strip()
        print(f"[similar_claims] Loaded index: {_EMBEDS.shape}")
    except Exception as e:
        print(f"[similar_claims] Load failed: {e}")


_load()


def find_similar(claim_id: str, top_k: int = 5) -> Optional[dict]:
    if _EMBEDS is None or _IDS is None or _META is None:
        return None
    cid = str(claim_id).strip()
    idx = np.where(_IDS == cid)[0]
    if len(idx) == 0:
        return None
    i = int(idx[0])
    query = _EMBEDS[i]

    # Cosine similarity = dot product (embeddings are L2-normalised)
    sims = _EMBEDS @ query
    # Exclude self
    sims[i] = -np.inf
    top_idx = np.argsort(-sims)[:top_k]

    neighbours = []
    esc_count = 0
    for j in top_idx:
        nid = str(_IDS[j])
        row = _META[_META["claim_id"] == nid]
        meta = {} if row.empty else row.iloc[0].to_dict()
        outcome = str(meta.get("target_outcome", "Unknown"))
        if outcome == "Escalated":
            esc_count += 1
        neighbours.append({
            "claim_id": nid,
            "similarity": round(float(sims[j]), 4),
            "outcome": outcome,
            "days_open": _safe_int(meta.get("days_open")),
            "total_claimed": _safe_float(meta.get("total_claimed")),
            "approved_amount": _safe_float(meta.get("approved_amount")),
            "incident_type": _safe_str(meta.get("incident_type")),
            "policy_type": _safe_str(meta.get("policy_type")),
        })

    return {
        "query_claim_id": cid,
        "neighbours": neighbours,
        "escalated_in_top_k": esc_count,
        "top_k": len(neighbours),
        "escalation_rate_in_neighbourhood":
            round(esc_count / len(neighbours), 3) if neighbours else 0.0,
    }


def index_stats():
    return {
        "available": _EMBEDS is not None,
        "n_claims": int(_EMBEDS.shape[0]) if _EMBEDS is not None else 0,
        "embedding_dim": int(_EMBEDS.shape[1]) if _EMBEDS is not None else 0,
    }


def _safe_int(v):
    try:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        return int(v)
    except Exception:
        return None


def _safe_float(v):
    try:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        return round(float(v), 2)
    except Exception:
        return None


def _safe_str(v):
    if v is None:
        return ""
    if isinstance(v, float) and np.isnan(v):
        return ""
    return str(v).strip("[]'\"")
