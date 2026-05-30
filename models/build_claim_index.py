"""
Build a semantic index over historical claims.

Encodes each claim's combined text (incident description + adjuster notes
+ claimant email) with a sentence-transformer, persists the embedding
matrix and metadata to disk. The API loads this at startup and serves
nearest-neighbour lookups via cosine similarity.

Output:
  data/features/claim_index.npz  — embeddings + aligned claim_ids
  data/features/claim_index.csv  — claim_id, outcome, days_open, total_claimed
"""
import os

import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer

TEXT_CSV = "data/processed/text_clean.csv"
STRUCTURED_CSV = "data/processed/structured_clean.csv"
OUT_NPZ = "data/features/claim_index.npz"
OUT_META = "data/features/claim_index.csv"

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def run():
    print(f"Loading embedder: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)

    print("Loading claim text + metadata...")
    text = pd.read_csv(TEXT_CSV)
    text["claim_id"] = text["claim_id"].astype(str).str.strip()
    text_cols = [c for c in text.columns if any(k in c.lower() for k in
                 ["desc", "note", "transcript", "email", "text"])]
    text["combined"] = text[text_cols].fillna("").astype(str).agg(" \n ".join, axis=1)

    struct = pd.read_csv(STRUCTURED_CSV)
    struct["claim_id"] = struct["claim_id"].astype(str).str.strip()
    keep = ["claim_id", "target_outcome", "days_open", "total_claimed",
            "incident_type", "policy_type", "approved_amount"]
    keep = [c for c in keep if c in struct.columns]
    struct = struct[keep]

    merged = text[["claim_id", "combined"]].merge(struct, on="claim_id", how="left")
    print(f"Encoding {len(merged)} claims...")
    embeddings = model.encode(
        merged["combined"].tolist(),
        batch_size=32,
        show_progress_bar=True,
        normalize_embeddings=True,   # cosine == dot product after this
    ).astype("float32")

    os.makedirs(os.path.dirname(OUT_NPZ), exist_ok=True)
    np.savez_compressed(OUT_NPZ,
                        embeddings=embeddings,
                        claim_ids=merged["claim_id"].to_numpy())

    merged.drop(columns=["combined"]).to_csv(OUT_META, index=False)

    print(f"\nIndex: {embeddings.shape} saved to {OUT_NPZ}")
    print(f"Meta:  {OUT_META}")


if __name__ == "__main__":
    run()
