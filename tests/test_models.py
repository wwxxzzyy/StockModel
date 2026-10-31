"""
Unit tests for ElasticNet and LightGBM ranker models.
"""

import numpy as np
import pytest
from stockmodel.models.elastic_net import ElasticNetRanker
from stockmodel.models.lightgbm_ranker import LightGBMRanker


def test_elastic_net_ranker():
    rng = np.random.default_rng(42)
    X = rng.normal(size=(200, 5))
    # y is positively correlated with feature 0
    y = 0.5 * X[:, 0] + rng.normal(scale=0.1, size=200)

    model = ElasticNetRanker(alpha=0.01, l1_ratio=0.5)
    model.fit(X, y, feature_names=[f"f_{i}" for i in range(5)])

    preds = model.predict(X)
    assert len(preds) == 200

    importances = model.get_feature_importances()
    assert "f_0" in importances
    # Feature 0 should have highest weight
    assert max(importances, key=importances.get) == "f_0"


def test_lightgbm_ranker():
    rng = np.random.default_rng(42)
    X_tr = rng.normal(size=(300, 5))
    y_tr = 0.8 * X_tr[:, 0] + rng.normal(scale=0.1, size=300)
    X_va = rng.normal(size=(100, 5))
    y_va = 0.8 * X_va[:, 0] + rng.normal(scale=0.1, size=100)

    model = LightGBMRanker(num_boost_round=100, early_stopping_rounds=20)
    model.fit(X_tr, y_tr, X_val=X_va, y_val=y_va, feature_names=[f"f_{i}" for i in range(5)])

    preds = model.predict(X_va)
    assert len(preds) == 100

    importances = model.get_feature_importances()
    assert "f_0" in importances
    assert importances["f_0"] > 0.0
