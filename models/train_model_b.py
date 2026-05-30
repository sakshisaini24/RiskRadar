"""
RiskRadar AI — Phase 2: Model B (NLP Risk Scorer)
Trains an XGBoost model on TF-IDF vectorized text data.
"""

import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score
import joblib
import os

from models.split_utils import load_holdout_ids, load_train_ids, build_and_save_split

# Paths
TEXT_DATA = "data/processed/text_clean.csv"
STRUC_DATA = "data/processed/structured_clean.csv" 
MODEL_DIR = "models"

def load_and_merge():
    print("Loading and merging text data with targets...")
    df_text = pd.read_csv(TEXT_DATA)
    df_target = pd.read_csv(STRUC_DATA)[["claim_id", "target"]]
    
    # Debug: Print columns to help you see what's actually in the CSV
    print(f"Columns found in text_clean.csv: {df_text.columns.tolist()}")
    
    df = pd.merge(df_text, df_target, on="claim_id")
    
    # DYNAMIC COLUMN PICKER: Find columns that look like text fields
    # This fixes the KeyError by looking for keywords
    text_cols = [col for col in df.columns if any(word in col.lower() for word in ['desc', 'note', 'transcript', 'email', 'text'])]
    
    print(f"Using these columns for NLP training: {text_cols}")
    
    # Combine text fields safely
    df["combined_text"] = df[text_cols].fillna("").agg(" ".join, axis=1)
    
    return df

def train_nlp_model(df):
    print("Vectorizing text (TF-IDF)...")

    vectorizer = TfidfVectorizer(
        stop_words='english',
        max_features=1000,
        ngram_range=(1, 2)
    )

    X_tfidf = vectorizer.fit_transform(df["combined_text"])
    y = df["target"]

    # Reuse the canonical holdout created by Model A so both models are
    # evaluated on the identical set of claim_ids.
    holdout_ids = load_holdout_ids()
    train_ids = load_train_ids()
    if not holdout_ids or not train_ids:
        print("[Model B] No canonical split found, creating one now.")
        train_ids, holdout_ids = build_and_save_split(df["claim_id"], y)

    claim_str = df["claim_id"].astype(str)
    train_mask = claim_str.isin(train_ids).values
    test_mask = claim_str.isin(holdout_ids).values

    X_train = X_tfidf[train_mask]
    X_test = X_tfidf[test_mask]
    y_train = y[train_mask]
    y_test = y[test_mask]

    print("Training XGBoost (Model B)...")
    
    # HACKATHON WINNER TIP: Handle class imbalance
    pos_weight = (len(y_train) - sum(y_train)) / sum(y_train)

    model_b = xgb.XGBClassifier(
        n_estimators=150,
        max_depth=4,
        learning_rate=0.05,
        scale_pos_weight=pos_weight, # Crucial for unbalanced data
        objective='binary:logistic',
        random_state=42
    )
    
    model_b.fit(X_train, y_train)
    
    # Evaluation
    probs = model_b.predict_proba(X_test)[:, 1]
    # Use 0.35 threshold for better recall on high-risk cases
    preds = (probs >= 0.35).astype(int) 
    
    print("\nModel B Performance (Tuned for Recall):")
    print(classification_report(y_test, preds))
    print(f"Model B AUC: {roc_auc_score(y_test, probs):.3f}")
    
    return model_b, vectorizer

def run():
    os.makedirs(MODEL_DIR, exist_ok=True)
    
    try:
        df = load_and_merge()
        model_b, vectorizer = train_nlp_model(df)
        
        print(f"\nSaving NLP artifacts to {MODEL_DIR}/...")
        model_b.save_model(os.path.join(MODEL_DIR, "model_b_nlp.json"))
        joblib.dump(vectorizer, os.path.join(MODEL_DIR, "model_b_vectorizer.joblib"))
        
        print(f"\n{'='*50}\nSuccess: Model B (NLP) trained and saved.\n{'='*50}")
    except Exception as e:
        print(f"\n[ERROR] Pipeline failed: {e}")

if __name__ == "__main__":
    run()