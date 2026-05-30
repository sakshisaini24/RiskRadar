"""
RiskRadar AI — Master Pipeline Runner
Run this single file to execute the full data pipeline:
  01 → Load & clean
  02 → Structured features
  03 → NLP features
  04 → Merge & export feature matrix
"""

import sys
import time

def run_step(name: str, fn):
    print(f"\n{'─'*50}")
    print(f"  Running: {name}")
    print(f"{'─'*50}")
    t0 = time.time()
    result = fn()
    elapsed = round(time.time() - t0, 1)
    print(f"  Done in {elapsed}s")
    return result


if __name__ == "__main__":
    print("\n" + "="*50)
    print("  RiskRadar AI — Data Pipeline")
    print("="*50)

    try:
        import pipeline.step_01_load_and_clean as s1
        import pipeline.step_02_structured_features as s2
        import pipeline.step_03_nlp_features as s3
        import pipeline.step_04_merge_and_export as s4
    except ModuleNotFoundError:
        # Running from pipeline/ folder directly
        sys.path.insert(0, ".")
        import importlib
        s1 = importlib.import_module("01_load_and_clean")
        s2 = importlib.import_module("02_structured_features")
        s3 = importlib.import_module("03_nlp_features")
        s4 = importlib.import_module("04_merge_and_export")

    run_step("Step 1 — Load & clean raw data", s1.run)
    run_step("Step 2 — Structured feature engineering", s2.run)
    run_step("Step 3 — NLP feature extraction", s3.run)
    run_step("Step 4 — Merge & export feature matrix", s4.run)

    print("\n" + "="*50)
    print("  Pipeline complete.")
    print("  Feature matrix → data/features/feature_matrix.csv")
    print("  Feature report → data/features/feature_report.txt")
    print("="*50 + "\n")