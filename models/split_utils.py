"""
Shared deterministic train/test split for Models A and B.

Both models must evaluate on the SAME held-out claim_ids so that the
/metrics endpoint reports true out-of-sample numbers. This module is the
single source of truth for that split.
"""
import os
import pandas as pd
from sklearn.model_selection import train_test_split

HOLDOUT_PATH = "data/features/holdout_claim_ids.csv"
TRAIN_PATH = "data/features/train_claim_ids.csv"
SPLIT_SEED = 42
TEST_SIZE = 0.2


def build_and_save_split(claim_ids, y):
    """Create a stratified 80/20 split and persist both halves to disk."""
    df = pd.DataFrame({"claim_id": claim_ids, "target": y}).reset_index(drop=True)
    train_df, test_df = train_test_split(
        df,
        test_size=TEST_SIZE,
        random_state=SPLIT_SEED,
        stratify=df["target"],
    )
    os.makedirs(os.path.dirname(HOLDOUT_PATH), exist_ok=True)
    train_df[["claim_id", "target"]].to_csv(TRAIN_PATH, index=False)
    test_df[["claim_id", "target"]].to_csv(HOLDOUT_PATH, index=False)
    print(f"[split_utils] Saved {len(train_df)} train + {len(test_df)} holdout claim_ids")
    return set(train_df["claim_id"].astype(str)), set(test_df["claim_id"].astype(str))


def load_holdout_ids():
    """Return the set of claim_ids held out at training time. Empty set if missing."""
    if not os.path.exists(HOLDOUT_PATH):
        return set()
    df = pd.read_csv(HOLDOUT_PATH)
    return set(df["claim_id"].astype(str).str.strip())


def load_train_ids():
    if not os.path.exists(TRAIN_PATH):
        return set()
    df = pd.read_csv(TRAIN_PATH)
    return set(df["claim_id"].astype(str).str.strip())
