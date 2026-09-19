"""
Loads the trained scam/fraud classifier (arth_raksha/ml/train.py) and
scores a wallet-behavior feature vector — one more scored signal for
risk_engine.py to blend alongside the rule-based checks in rules.py, never
a replacement for them and never surfaced as a bare number.

Per-prediction explainability via single-feature ablation: for the exact
input given, each feature that differs from its training-set median is
individually reset to that median and the resulting change in predicted
probability is measured. The features with the largest real effect on
*this* prediction are reported — computed fresh every time, not a cached
global importance score.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import joblib
import pandas as pd

_HERE = os.path.dirname(__file__)
_MODEL_DIR = os.path.join(_HERE, "..", "ml", "model")


@dataclass
class MLSignalResult:
    probability: float
    top_contributors: list[tuple[str, float]] = field(default_factory=list)  # (feature, probability_delta)
    features_used: int = 0
    features_imputed: int = 0
    model_version: str = "gradient_boosting_v1"

    @property
    def feature_coverage(self) -> float:
        total = self.features_used + self.features_imputed
        return round(self.features_used / total, 3) if total else 0.0


class ScamClassifierSignal:
    def __init__(self):
        self._model = None
        self._feature_columns: list[str] = []
        self._medians: dict[str, float] = {}
        self._load()

    def _load(self) -> None:
        model_path = os.path.join(_MODEL_DIR, "scam_classifier.joblib")
        cols_path = os.path.join(_MODEL_DIR, "feature_columns.json")
        medians_path = os.path.join(_MODEL_DIR, "feature_medians.json")
        if not (os.path.exists(model_path) and os.path.exists(cols_path) and os.path.exists(medians_path)):
            return
        self._model = joblib.load(model_path)
        with open(cols_path) as f:
            self._feature_columns = json.load(f)
        with open(medians_path) as f:
            self._medians = json.load(f)

    @property
    def available(self) -> bool:
        return self._model is not None

    def score(self, features: dict[str, float], top_n: int = 3) -> MLSignalResult:
        if not self.available:
            raise RuntimeError(
                "Scam classifier model not found — run `python -m arth_raksha.ml.train` first."
            )

        row: list[float] = []
        used = 0
        imputed = 0
        for col in self._feature_columns:
            val = features.get(col)
            if val is not None:
                row.append(float(val))
                used += 1
            else:
                row.append(self._medians.get(col, 0.0))
                imputed += 1

        def _predict(values: list[float]) -> float:
            frame = pd.DataFrame([values], columns=self._feature_columns)
            return float(self._model.predict_proba(frame)[0, 1])

        proba = _predict(row)

        contributions: list[tuple[str, float]] = []
        for i, col in enumerate(self._feature_columns):
            median = self._medians.get(col, 0.0)
            if row[i] == median:
                continue
            ablated = row.copy()
            ablated[i] = median
            contributions.append((col, proba - _predict(ablated)))

        contributions.sort(key=lambda t: abs(t[1]), reverse=True)
        return MLSignalResult(
            probability=proba,
            top_contributors=contributions[:top_n],
            features_used=used,
            features_imputed=imputed,
        )


_signal = ScamClassifierSignal()


def get_signal() -> ScamClassifierSignal:
    return _signal
