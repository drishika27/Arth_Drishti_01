"""
Trains a real scam/fraud-address classifier on real, labelled Ethereum
address data (see data/SOURCE.md) and saves it for arth_raksha's risk
engine to use as one more explainable signal alongside the rule-based
checks — never as an opaque replacement for them.

Two models are trained and evaluated so the choice of "which one to ship"
is a measured, documented decision rather than a default:

  - Logistic Regression: fully transparent (a signed weight per feature).
  - HistGradientBoostingClassifier: trained as the stronger candidate.

On this dataset the gap turned out to be large (see metrics.json) — for a
safety-critical scam signal, shipping the much weaker linear model just to
get free coefficient-based explanations is the wrong trade-off. So
HistGradientBoostingClassifier is the one wired into the live signal, and
explainability is instead produced per-prediction by single-feature
ablation (see arth_raksha/backend/ml_signal.py): for a given address, each
feature is individually reset to the training-set median and the resulting
change in predicted probability is measured. This gives a real, computed
"why" for that specific prediction — not a global approximation and not
an invented number — without needing an extra SHAP-style dependency.

Run:
    python -m arth_raksha.ml.train
Writes:
    arth_raksha/ml/model/scam_classifier.joblib   (the shipped LR pipeline)
    arth_raksha/ml/model/feature_columns.json     (exact column order)
    arth_raksha/ml/model/feature_medians.json     (for imputing unknown inputs)
    arth_raksha/ml/model/metrics.json             (precision/recall/F1/ROC-AUC for both models)
"""
from __future__ import annotations

import json
import os

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

HERE = os.path.dirname(__file__)
DATA_PATH = os.path.join(HERE, "data", "ethereum_fraud_dataset.csv")
MODEL_DIR = os.path.join(HERE, "model")

# Columns that identify the row rather than describe behavior, plus two
# free-text/high-cardinality categorical columns (the most-sent/received
# ERC20 token *name*) that would need their own encoding strategy and add
# little signal beyond what the numeric ERC20 activity columns already
# capture — dropped explicitly rather than silently mis-encoded as numbers.
NON_FEATURE_COLUMNS = [
    "Index", "Address", "FLAG",
    "ERC20_most_sent_token_type", "ERC20_most_rec_token_type",
]


def load_dataset() -> tuple[pd.DataFrame, pd.Series, list[str]]:
    df = pd.read_csv(DATA_PATH)
    df.columns = [c.strip() for c in df.columns]
    y = df["FLAG"].astype(int)
    feature_cols = [c for c in df.columns if c not in NON_FEATURE_COLUMNS]
    X = df[feature_cols].apply(pd.to_numeric, errors="coerce")
    return X, y, feature_cols


def main():
    os.makedirs(MODEL_DIR, exist_ok=True)
    X, y, feature_cols = load_dataset()
    medians = X.median(numeric_only=True).fillna(0.0)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y
    )

    # -- Logistic Regression: the shipped, explainable signal -----------
    lr_pipeline = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
        ("clf", LogisticRegression(max_iter=2000, class_weight="balanced", random_state=42)),
    ])
    lr_pipeline.fit(X_train, y_train)
    lr_pred = lr_pipeline.predict(X_test)
    lr_proba = lr_pipeline.predict_proba(X_test)[:, 1]

    # -- Gradient Boosting: benchmark only -------------------------------
    gb = HistGradientBoostingClassifier(random_state=42)
    gb.fit(X_train.fillna(medians), y_train)
    gb_pred = gb.predict(X_test.fillna(medians))
    gb_proba = gb.predict_proba(X_test.fillna(medians))[:, 1]

    def eval_block(y_true, pred, proba):
        return {
            "precision": round(precision_score(y_true, pred), 4),
            "recall": round(recall_score(y_true, pred), 4),
            "f1": round(f1_score(y_true, pred), 4),
            "roc_auc": round(roc_auc_score(y_true, proba), 4),
            "confusion_matrix": confusion_matrix(y_true, pred).tolist(),
            "classification_report": classification_report(y_true, pred, output_dict=True),
        }

    lr_metrics = eval_block(y_test, lr_pred, lr_proba)
    gb_metrics = eval_block(y_test, gb_pred, gb_proba)
    metrics = {
        "n_train": len(X_train),
        "n_test": len(X_test),
        "class_balance_test": y_test.value_counts().to_dict(),
        "logistic_regression_benchmark": lr_metrics,
        "gradient_boosting": gb_metrics,
        "shipped_model": "gradient_boosting",
        "shipped_model_rationale": (
            "Logistic regression's coefficients are more directly interpretable, "
            f"but on this held-out test split it trails badly for a safety signal "
            f"(precision {lr_metrics['precision']:.3f}, recall {lr_metrics['recall']:.3f} vs "
            f"gradient boosting's {gb_metrics['precision']:.3f}/{gb_metrics['recall']:.3f}) — "
            "that gap in missed/false-flagged scams matters more than coefficient "
            "transparency here. Gradient boosting is shipped, with per-prediction "
            "explainability provided instead by single-feature ablation (see "
            "ml_signal.py) rather than by the model being linear."
        ),
    }

    with open(os.path.join(MODEL_DIR, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    joblib.dump(gb, os.path.join(MODEL_DIR, "scam_classifier.joblib"))
    with open(os.path.join(MODEL_DIR, "feature_columns.json"), "w") as f:
        json.dump(feature_cols, f, indent=2)
    with open(os.path.join(MODEL_DIR, "feature_medians.json"), "w") as f:
        json.dump({k: float(v) for k, v in medians.items()}, f, indent=2)

    print(f"Trained on {len(X_train)} rows, evaluated on {len(X_test)} held-out rows.")
    print("Logistic Regression (benchmark):", lr_metrics["precision"], lr_metrics["recall"], lr_metrics["roc_auc"])
    print("Gradient Boosting   (shipped):  ", gb_metrics["precision"], gb_metrics["recall"], gb_metrics["roc_auc"])
    print(f"Saved model + metrics to {MODEL_DIR}")


if __name__ == "__main__":
    main()
