"""
RiskRadar AI — Phase 2: Ensemble Engine
Combines Model A (Structured) and Model B (NLP) scores.
Calculates SHAP-based warning signs for the UI reasoning layer.
"""

import pandas as pd
import numpy as np
import xgboost as xgb
import joblib
import os

# Paths to artifacts
MODEL_DIR = "models"
DATA_DIR = "data/features"
PROCESSED_DIR = "data/processed"

class RiskRadarEnsemble:
    def __init__(self):
        print("Initializing RiskRadar Ensemble Engine...")
        
        # 1. Load Model A & its metadata
        self.model_a = xgb.XGBClassifier()
        self.model_a.load_model(os.path.join(MODEL_DIR, "model_a_xgb.json"))
        self.meta_a = joblib.load(os.path.join(MODEL_DIR, "model_a_metadata.joblib"))
        self.explainer_a = joblib.load(os.path.join(MODEL_DIR, "model_a_shap.joblib"))
        
        # 2. Load Model B & its Vectorizer
        self.model_b = xgb.XGBClassifier()
        self.model_b.load_model(os.path.join(MODEL_DIR, "model_b_nlp.json"))
        self.vectorizer_b = joblib.load(os.path.join(MODEL_DIR, "model_b_vectorizer.joblib"))
        
        # 3. Load Data for lookups
        self.feature_matrix = pd.read_csv(os.path.join(DATA_DIR, "feature_matrix.csv"))
        self.text_data = pd.read_csv(os.path.join(PROCESSED_DIR, "text_clean.csv"))
        
        # Find text columns dynamically once during init
        self.text_cols = [col for col in self.text_data.columns if any(word in col.lower() for word in ['desc', 'note', 'transcript', 'email', 'text'])]

        # Median feature defaults for Salesforce / external claims
        feat_cols = self.feature_matrix.drop(columns=["claim_id", "target"], errors="ignore")
        self._feature_medians = feat_cols.median(numeric_only=True)

    def _score_text(self, combined_text: str) -> float:
        text = (combined_text or "").strip()
        if not text:
            return 0.5
        X_b = self.vectorizer_b.transform([text])
        return float(self.model_b.predict_proba(X_b)[0, 1])

    def score_external(self, claim_id: str, combined_text: str, feature_row: dict):
        """
        Score a Salesforce claim: Model B on text + approximate Model A from SF fields.
        """
        prob_b = self._score_text(combined_text)
        prob_a = 0.5
        warning_signs = []

        names = self.meta_a["feature_names"]
        row = {n: float(self._feature_medians.get(n, 0)) for n in names}
        for k, v in (feature_row or {}).items():
            if k in row and v is not None:
                try:
                    row[k] = float(v)
                except (TypeError, ValueError):
                    pass

        X_a = pd.DataFrame([row])[names]
        prob_a = float(self.model_a.predict_proba(X_a)[0, 1])

        shap_values = self.explainer_a.shap_values(X_a)
        feature_importance = pd.Series(shap_values[0], index=names)
        for feat, val in feature_importance.sort_values(ascending=False).head(3).items():
            if val > 0:
                warning_signs.append(f"{feat.replace('_', ' ').title()}")

        final_score = (prob_a * 0.4) + (prob_b * 0.6)
        if not warning_signs:
            warning_signs = ["Salesforce claim — activity text signals"]

        return {
            "claim_id": str(claim_id),
            "risk_score_pct": float(round(final_score * 100, 1)),
            "is_high_risk": bool(final_score >= self.meta_a["optimal_threshold"]),
            "model_a_contribution": float(round(prob_a * 100, 1)),
            "model_b_contribution": float(round(prob_b * 100, 1)),
            "top_warning_signs": warning_signs,
            "scoring_mode": "salesforce_hybrid",
        }

    def get_risk_score(self, claim_id):
        """Calculates a weighted probability from both models."""
        
        # Pull structured features for this claim
        row_a = self.feature_matrix[self.feature_matrix['claim_id'] == claim_id]
        if row_a.empty:
            return None
        
        # Get Model A Probability
        X_a = row_a[self.meta_a['feature_names']]
        prob_a = self.model_a.predict_proba(X_a)[0, 1]
        
        # Pull and vectorize text for Model B
        row_b = self.text_data[self.text_data['claim_id'] == claim_id]
        if row_b.empty:
            # Fallback if text data is missing for this ID
            prob_b = 0.5 
        else:
            # Combine all identified text columns for this specific row
            combined_text = " ".join([str(row_b[col].values[0]) for col in self.text_cols])
            X_b = self.vectorizer_b.transform([combined_text])
            prob_b = self.model_b.predict_proba(X_b)[0, 1]
        
        # WEIGHTED ENSEMBLE
        final_score = (prob_a * 0.4) + (prob_b * 0.6)
        
        # Generate SHAP "Warning Signs" from Model A
        shap_values = self.explainer_a.shap_values(X_a)
        
        # Get top 3 positive contributors (red flags)
        feature_importance = pd.Series(shap_values[0], index=self.meta_a['feature_names'])
        red_flags = feature_importance.sort_values(ascending=False).head(3)
        
        warning_signs = []
        for feat, val in red_flags.items():
            if val > 0: 
                warning_signs.append(f"{feat.replace('_', ' ').title()}")

        return {
            "claim_id": str(claim_id), # Ensure ID is a string
            "risk_score_pct": float(round(final_score * 100, 1)), # Cast to float
            "is_high_risk": bool(final_score >= self.meta_a['optimal_threshold']), # Cast to bool
            "model_a_contribution": float(round(prob_a * 100, 1)), # Cast to float
            "model_b_contribution": float(round(prob_b * 100, 1)), # Cast to float
            "top_warning_signs": [str(sign) for sign in warning_signs] # Ensure list of strings
        }

# --- Quick Test ---
if __name__ == "__main__":
    engine = RiskRadarEnsemble()
    # Test with the first claim in the dataset
    sample_id = engine.feature_matrix['claim_id'].iloc[0]
    result = engine.get_risk_score(sample_id)
    print("\n" + "="*40)
    print(f"TEST RESULT FOR CLAIM: {sample_id}")
    for k, v in result.items():
        print(f"  {k:<20}: {v}")
    print("="*40)