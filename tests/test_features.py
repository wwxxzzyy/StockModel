"""
Unit tests for 7-feature pipeline and normalizations.
"""

import numpy as np
import polars as pl
import pytest
from stockmodel.data.synthetic import SyntheticMarketGenerator
from stockmodel.features.pipeline import FeaturePipeline
from stockmodel.features.normalizer import compute_rolling_zscore, compute_cross_sectional_rank
from stockmodel.config import FeatureConfig


def test_feature_pipeline_columns_and_bounds():
    gen = SyntheticMarketGenerator(seed=456)
    df = gen.generate(n_days=70)

    cfg = FeatureConfig()
    pipeline = FeaturePipeline(cfg)
    feat_df, feat_cols = pipeline.build_features(df)

    assert len(feat_cols) == 7
    expected_cols = [
        "feat_short_squeeze_pressure",
        "feat_net_gex",
        "feat_pcr_momentum",
        "feat_sector_relative_momentum",
        "feat_vwap_divergence",
        "feat_vix_slope",
        "feat_sue_score",
    ]
    assert feat_cols == expected_cols

    # Verify all 7 features are present
    for col in expected_cols:
        assert col in feat_df.columns
        valid_vals = feat_df.filter(pl.col(col).is_not_null())[col].to_numpy()
        assert len(valid_vals) > 0
        assert np.all(valid_vals >= -1.0 - 1e-6)
        assert np.all(valid_vals <= 1.0 + 1e-6)


def test_rolling_zscore_expression():
    df = pl.DataFrame({
        "symbol": ["A"] * 30,
        "val": list(range(30)),
    })
    expr = compute_rolling_zscore("val", window_size=10, min_samples=5)
    res = df.select(expr)["val_z60"].to_numpy()
    assert np.isnan(res[0])
    assert not np.isnan(res[10])
    # For monotonically increasing, latest value is above rolling mean, so z > 0
    assert res[10] > 0
