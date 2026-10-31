"""
End-to-End integration test covering the entire StockModel quantitative workflow.
"""

import numpy as np
import polars as pl
import pytest
from stockmodel.config import SystemConfig, ValidationConfig
from stockmodel.data.synthetic import SyntheticMarketGenerator
from stockmodel.targets.volatility_adjusted import compute_volatility_adjusted_target
from stockmodel.features.pipeline import FeaturePipeline
from stockmodel.models.gating import ComplexityGator
from stockmodel.models.lightgbm_ranker import LightGBMRanker
from stockmodel.backtest.engine import BacktestEngine
from stockmodel.backtest.reporting import compute_metrics, generate_tearsheet


def test_end_to_end_pipeline():
    cfg = SystemConfig()
    cfg.validation = ValidationConfig(
        n_splits=2,
        train_period_days=100,
        test_period_days=30,
        horizon_days=10,
        embargo_buffer_days=5,
    )
    cfg.model.num_boost_round = 50

    # 1. Data generation
    gen = SyntheticMarketGenerator(seed=999)
    raw_df = gen.generate(n_days=180)
    assert raw_df.height > 0

    # 2. Target computation
    target_df = compute_volatility_adjusted_target(raw_df, cfg.target)
    assert "target" in target_df.columns

    # 3. Feature Pipeline
    pipeline = FeaturePipeline(cfg.feature)
    panel_df, feat_cols = pipeline.build_features(target_df)
    assert len(feat_cols) == 7

    pdf = panel_df.to_pandas()

    # 4. Complexity Gating
    gator = ComplexityGator(cfg)
    gate_res = gator.evaluate(pdf, feat_cols, target_col="target")
    assert len(gate_res.fold_evaluations) == 2
    assert -1.0 <= gate_res.lgb_mean_ic <= 1.0

    # 5. Fit model and predict
    valid = pdf.dropna(subset=feat_cols + ["target"])
    ranker = LightGBMRanker(params=cfg.model.lgb_params, num_boost_round=50)
    ranker.fit(valid[feat_cols].to_numpy(), valid["target"].to_numpy(), feature_names=feat_cols)
    pdf["pred"] = ranker.predict(pdf[feat_cols].to_numpy())

    # 6. Backtest simulation
    engine = BacktestEngine(cfg)
    bt_res = engine.run(pdf, pred_col="pred")
    assert bt_res.final_nav > 0
    assert len(bt_res.daily_records) == 180

    # 7. Metrics & Tear-sheet
    metrics = compute_metrics(bt_res.daily_records)
    tearsheet = generate_tearsheet(metrics, oos_ic=gate_res.lgb_mean_ic, oos_icir=gate_res.lgb_icir)
    assert "StockModel Quantitative Swing Strategy Tear-Sheet" in tearsheet
    assert "Sharpe Ratio" in tearsheet
