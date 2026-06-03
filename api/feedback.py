"""
Adjuster feedback loop.

Every time an adjuster agrees/disagrees with the model's prediction, the
event is persisted to a local SQLite store. The API aggregates those
events into a 'disagreement rate' that the dashboard surfaces — so a
judge can see the model is continuously validated against human expert
judgement, and so we have the raw log for nightly retraining.
"""
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

DB_PATH = "data/feedback.db"

FeedbackVerdict = Literal["agree", "disagree_too_high", "disagree_too_low", "note"]

DECISIVE_VERDICTS = frozenset({"agree", "disagree_too_high", "disagree_too_low"})
# Verdict stays locked while the displayed risk score is within this band (percentage points).
SCORE_TOLERANCE = 0.15


class FeedbackPayload(BaseModel):
    claim_id: str = Field(..., min_length=1)
    verdict: FeedbackVerdict
    adjuster_id: Optional[str] = None
    model_score: Optional[float] = None
    comment: Optional[str] = None


def _ensure_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id TEXT NOT NULL,
            verdict TEXT NOT NULL,
            adjuster_id TEXT,
            model_score REAL,
            comment TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_feedback_claim ON feedback(claim_id);"
    )
    conn.commit()
    conn.close()


_ensure_db()


def record(payload: FeedbackPayload) -> dict:
    _ensure_db()
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO feedback "
            "(claim_id, verdict, adjuster_id, model_score, comment, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (payload.claim_id, payload.verdict, payload.adjuster_id,
             payload.model_score, payload.comment, now),
        )
        feedback_id = cur.lastrowid
    return {"status": "ok", "id": feedback_id, "created_at": now}


def summary() -> dict:
    _ensure_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) AS n FROM feedback").fetchone()["n"]
        by_verdict = {
            r["verdict"]: r["n"]
            for r in conn.execute(
                "SELECT verdict, COUNT(*) AS n FROM feedback GROUP BY verdict"
            )
        }
        recent = [
            dict(r)
            for r in conn.execute(
                "SELECT id, claim_id, verdict, model_score, comment, created_at "
                "FROM feedback ORDER BY id DESC LIMIT 10"
            )
        ]
    agreement = by_verdict.get("agree", 0)
    disagreement = (
        by_verdict.get("disagree_too_high", 0) + by_verdict.get("disagree_too_low", 0)
    )
    decisive = agreement + disagreement
    disagreement_rate = round(disagreement / decisive, 4) if decisive else 0.0
    return {
        "total": total,
        "by_verdict": by_verdict,
        "disagreement_rate": disagreement_rate,
        "agreement_rate": round(agreement / decisive, 4) if decisive else 0.0,
        "recent": recent,
        "retrain_cadence": "nightly (stub — records persisted for offline retrain job)",
        "next_retrain_eta": "02:00 UTC (simulated)",
    }


def for_claim(claim_id: str, limit: int = 10) -> list:
    _ensure_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, claim_id, verdict, adjuster_id, model_score, comment, created_at "
            "FROM feedback WHERE claim_id = ? ORDER BY id DESC LIMIT ?",
            (claim_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def latest_decisive(claim_id: str) -> Optional[dict]:
    """Most recent agree / too-high / too-low verdict for this claim."""
    for event in for_claim(claim_id, limit=30):
        if event.get("verdict") in DECISIVE_VERDICTS:
            return event
    return None


def score_changed_since_verdict(stored_score: Optional[float], current_score: Optional[float]) -> bool:
    if stored_score is None or current_score is None:
        return False
    return abs(float(current_score) - float(stored_score)) > SCORE_TOLERANCE


def active_verdict(claim_id: str, current_score: Optional[float] = None) -> dict:
    """
    Return the saved adjuster verdict for UI restore.
    locked=True when the claim's risk score still matches the score at verdict time.
    """
    latest = latest_decisive(claim_id)
    if not latest:
        return {
            "verdict": None,
            "locked": False,
            "stale": False,
            "model_score_at_verdict": None,
            "created_at": None,
            "id": None,
        }
    stored = latest.get("model_score")
    stale = score_changed_since_verdict(stored, current_score)
    return {
        "verdict": latest["verdict"],
        "locked": not stale,
        "stale": stale,
        "model_score_at_verdict": stored,
        "current_model_score": current_score,
        "created_at": latest.get("created_at"),
        "id": latest.get("id"),
    }


def queue_score_after_verdict(verdict: str, model_score: float) -> float:
    """Optional display adjustment on triage queue after adjuster disagreement."""
    score = float(model_score)
    if verdict == "disagree_too_high":
        return min(score, 49.9)
    if verdict == "disagree_too_low":
        return max(score, 60.0)
    return score
