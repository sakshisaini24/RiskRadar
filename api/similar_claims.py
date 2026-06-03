"""
Nearest-neighbour lookup over the claim embedding index.

Given a claim_id, returns the top-K most textually similar historical
claims along with their outcomes — so the adjuster can see how similar
profiles resolved. This is a huge trust signal: instead of a black-box
risk score, they see "5 of your 5 closest matches escalated."

External / demo claims are not in the embedding index; those use a
TF-IDF fallback (same vectorizer as Model B) over historical claim text.
"""
import os
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity

INDEX_NPZ = "data/features/claim_index.npz"
INDEX_META = "data/features/claim_index.csv"
TEXT_CSV = "data/processed/text_clean.csv"
STRUCTURED_CSV = "data/processed/structured_clean.csv"
VECTORIZER_PATH = "models/model_b_vectorizer.joblib"

_EMBEDS: Optional[np.ndarray] = None
_IDS: Optional[np.ndarray] = None
_META: Optional[pd.DataFrame] = None
_TFIDF_VEC = None
_TFIDF_MATRIX = None
_TFIDF_IDS: Optional[np.ndarray] = None
_TFIDF_META: Optional[pd.DataFrame] = None


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


def _load_tfidf_fallback() -> bool:
    global _TFIDF_VEC, _TFIDF_MATRIX, _TFIDF_IDS, _TFIDF_META
    if _TFIDF_MATRIX is not None:
        return True
    paths = (VECTORIZER_PATH, TEXT_CSV, STRUCTURED_CSV)
    if not all(os.path.exists(p) for p in paths):
        return False
    try:
        _TFIDF_VEC = joblib.load(VECTORIZER_PATH)
        text = pd.read_csv(TEXT_CSV)
        text["claim_id"] = text["claim_id"].astype(str).str.strip()
        text_cols = [
            c for c in text.columns
            if any(k in c.lower() for k in ["desc", "note", "transcript", "email", "text"])
        ]
        combined = text[text_cols].fillna("").astype(str).agg(" \n ".join, axis=1)
        _TFIDF_MATRIX = _TFIDF_VEC.transform(combined.tolist())
        _TFIDF_IDS = text["claim_id"].to_numpy()

        struct = pd.read_csv(STRUCTURED_CSV)
        struct["claim_id"] = struct["claim_id"].astype(str).str.strip()
        keep = ["claim_id", "target_outcome", "days_open", "total_claimed",
                "incident_type", "policy_type", "approved_amount"]
        keep = [c for c in keep if c in struct.columns]
        _TFIDF_META = struct[keep]
        print(f"[similar_claims] TF-IDF fallback ready: {len(_TFIDF_IDS)} claims")
        return True
    except Exception as e:
        print(f"[similar_claims] TF-IDF fallback load failed: {e}")
        return False


def _neighbours_from_indices(
    query_claim_id: str,
    top_idx: np.ndarray,
    sims: np.ndarray,
    ids: np.ndarray,
    meta_df: pd.DataFrame,
) -> dict:
    neighbours = []
    esc_count = 0
    for j in top_idx:
        nid = str(ids[j])
        if nid == query_claim_id:
            continue
        row = meta_df[meta_df["claim_id"] == nid]
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
        "query_claim_id": str(query_claim_id).strip(),
        "neighbours": neighbours,
        "escalated_in_top_k": esc_count,
        "top_k": len(neighbours),
        "escalation_rate_in_neighbourhood":
            round(esc_count / len(neighbours), 3) if neighbours else 0.0,
    }


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

    return _neighbours_from_indices(cid, top_idx, sims, _IDS, _META)


def find_similar_by_text(combined_text: str, query_claim_id: str, top_k: int = 5) -> Optional[dict]:
    """Nearest neighbours for Salesforce/demo claims using Model B TF-IDF vectors."""
    text = (combined_text or "").strip()
    if not text or not _load_tfidf_fallback():
        return None
    assert _TFIDF_VEC is not None and _TFIDF_MATRIX is not None
    assert _TFIDF_IDS is not None and _TFIDF_META is not None

    q = _TFIDF_VEC.transform([text])
    sims = cosine_similarity(q, _TFIDF_MATRIX)[0]
    cid = str(query_claim_id).strip()
    ranked = np.argsort(-sims)
    selected = []
    for j in ranked:
        if str(_TFIDF_IDS[j]) == cid:
            continue
        selected.append(j)
        if len(selected) >= top_k:
            break
    if not selected:
        return None
    return _neighbours_from_indices(cid, np.array(selected), sims, _TFIDF_IDS, _TFIDF_META)


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
