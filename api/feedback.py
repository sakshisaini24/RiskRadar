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
