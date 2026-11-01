"""
Command Line Interface (CLI) for StockModel.
"""

import argparse
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import polars as pl
from stockmodel.config import SystemConfig
from stockmodel.data.synthetic import SyntheticMarketGenerator
from stockmodel.data.loader import MarketDataLoader
from stockmodel.targets.volatility_adjusted import compute_volatility_adjusted_target
from stockmodel.features.pipeline import FeaturePipeline
from stockmodel.models.gating import ComplexityGator
from stockmodel.models.ablation import FeatureAblationStudy
from stockmodel.models.lightgbm_ranker import LightGBMRanker
from stockmodel.execution.rebalance import RebalanceManager
from stockmodel.backtest.engine import BacktestEngine
from stockmodel.backtest.reporting import compute_metrics, generate_tearsheet


def cmd_check_gate(args):
    """Executes purged walk-forward cross-validation and complexity gating."""
    print("=" * 70)
    print("StockModel: Running Purged Walk-Forward Complexity Gating...")
    print("=" * 70)

    cfg = SystemConfig()
    if args.data:
        print(f"Loading data from: {args.data}")
        raw_df = MarketDataLoader.load_file(args.data)
    else:
        print(f"Generating synthetic market panel (n_days={args.days})...")
        gen = SyntheticMarketGenerator(seed=args.seed)
        raw_df = gen.generate(n_days=args.days)

    print("Computing volatility-adjusted targets (H=15)...")
    target_df = compute_volatility_adjusted_target(raw_df, cfg.target)

    print("Building 7-feature pipeline...")
    pipeline = FeaturePipeline(cfg.feature)
    panel_df, feat_cols = pipeline.build_features(target_df)

    pdf = panel_df.to_pandas()
    gator = ComplexityGator(cfg)
    result = gator.evaluate(pdf, feat_cols, target_col="target")

    print("\n" + result.summary())
    print("\nFold Breakdown:")
    for f in result.fold_evaluations:
        beat = "[X]" if f.lgb_outperformed else "[ ]"
        print(f"  Fold {f.fold_idx} | Train: {f.train_start} -> {f.train_end} | Test: {f.test_start} -> {f.test_end} | GBDT IC: {f.lgb_ic:.4f} | ENet IC: {f.elastic_ic:.4f} | GBDT Won: {beat}")

    if not result.passed:
        print("\n[WARNING] Model did not meet acceptance gate criteria.")
        sys.exit(1)
    else:
        print("\n[SUCCESS] Model passed all acceptance criteria and benchmark gates.")


def cmd_run_backtest(args):
    """Executes full end-to-end backtesting simulation."""
    print("=" * 70)
    print("StockModel: Running Quantitative Swing Behavior Backtest...")
    print("=" * 70)

    cfg = SystemConfig()
    if args.data:
        print(f"Loading data from: {args.data}")
        raw_df = MarketDataLoader.load_file(args.data)
    else:
        print(f"Generating synthetic market panel (n_days={args.days})...")
        gen = SyntheticMarketGenerator(seed=args.seed)
        raw_df = gen.generate(n_days=args.days)

    print("Computing volatility-adjusted targets (H=15)...")
    target_df = compute_volatility_adjusted_target(raw_df, cfg.target)

    print("Building 7-feature pipeline...")
    pipeline = FeaturePipeline(cfg.feature)
    panel_df, feat_cols = pipeline.build_features(target_df)

    pdf = panel_df.to_pandas()
    # Fit model on training slice or out-of-fold walk-forward predictions
    print("Fitting model across walk-forward folds...")
    gator = ComplexityGator(cfg)
    gating_res = gator.evaluate(pdf, feat_cols, target_col="target")
    print(f"OOS GBDT IC: {gating_res.lgb_mean_ic:.4f} | ICIR: {gating_res.lgb_icir:.2f} | Baseline ENet IC: {gating_res.elastic_mean_ic:.4f}")

    # Generate full rolling predictions for the backtest
    # Fit LightGBM ranker on full available valid sample
    valid_train = pdf.dropna(subset=feat_cols + ["target"])
    ranker = LightGBMRanker(params=cfg.model.lgb_params, num_boost_round=cfg.model.num_boost_round)
    ranker.fit(valid_train[feat_cols].to_numpy(), valid_train["target"].to_numpy(), feature_names=feat_cols)

    # Predict on entire panel
    pdf["pred"] = ranker.predict(pdf[feat_cols].to_numpy())

    print("Simulating execution under friction, weekly rebalance, inertia & blackouts...")
    engine = BacktestEngine(cfg)
    btest_res = engine.run(pdf, pred_col="pred")

    metrics = compute_metrics(btest_res.daily_records)
    tearsheet = generate_tearsheet(
        metrics,
        title="StockModel Quantitative Swing Strategy Backtest",
        oos_ic=gating_res.lgb_mean_ic,
        oos_icir=gating_res.lgb_icir,
    )

    print("\n" + tearsheet)
    print("\nTotal Trade Turnover:  ", f"{btest_res.total_turnover:.2f}x")
    print("Total Friction Cost:   ", f"{btest_res.total_friction_cost * 10000:.1f} bps")
    print("Final Portfolio NAV:   ", f"${btest_res.final_nav:,.2f}")


def cmd_ablation(args):
    """Executes feature ablation study."""
    print("=" * 70)
    print("StockModel: Running Systematic Feature Ablation Study...")
    print("=" * 70)

    cfg = SystemConfig()
    gen = SyntheticMarketGenerator(seed=args.seed)
    raw_df = gen.generate(n_days=args.days)
    target_df = compute_volatility_adjusted_target(raw_df, cfg.target)
    pipeline = FeaturePipeline(cfg.feature)
    panel_df, feat_cols = pipeline.build_features(target_df)

    pdf = panel_df.to_pandas()
    ablation = FeatureAblationStudy(cfg)
    results = ablation.run_study(pdf, feat_cols)

    print("\n| Feature Name | IC With Feature | IC Without Feature | IC Contribution (Delta) | Action |")
    print("| :--- | :--- | :--- | :--- | :--- |")
    for r in results:
        print(f"| {r.feature_name} | {r.ic_with_feature:.4f} | {r.ic_without_feature:.4f} | {r.ic_delta:+.4f} | {r.action} |")


def cmd_rank(args):
    """Outputs current portfolio rankings and decile allocations."""
    cfg = SystemConfig()
    gen = SyntheticMarketGenerator(seed=args.seed)
    raw_df = gen.generate(n_days=args.days)
    target_df = compute_volatility_adjusted_target(raw_df, cfg.target)
    pipeline = FeaturePipeline(cfg.feature)
    panel_df, feat_cols = pipeline.build_features(target_df)
    pdf = panel_df.to_pandas()

    valid = pdf.dropna(subset=feat_cols + ["target"])
    ranker = LightGBMRanker(params=cfg.model.lgb_params, num_boost_round=300)
    ranker.fit(valid[feat_cols].to_numpy(), valid["target"].to_numpy(), feature_names=feat_cols)

    latest_date = pdf["date"].max()
    latest_df = pdf[pdf["date"] == latest_date].copy()
    latest_df["pred"] = ranker.predict(latest_df[feat_cols].to_numpy())

    rebal_mgr = RebalanceManager()
    atr_series = pd.Series(dict(zip(latest_df["symbol"], latest_df["atr_14"])))
    dte_map = dict(zip(latest_df["symbol"], latest_df["days_to_earnings"]))

    weights = rebal_mgr.rebalance_portfolio(
        current_holdings={},
        scores_df=latest_df[["symbol", "pred"]],
        atr_series=atr_series,
        days_to_earnings_map=dte_map,
        allow_short=True,
    )

    print(f"\nAllocations as of {latest_date}:")
    print(f"{'Symbol':<10} {'Weight':>10} {'Type':>8}")
    print("-" * 30)
    for sym, w in sorted(weights.items(), key=lambda x: x[1], reverse=True):
        pos_type = "LONG" if w > 0 else "SHORT"
        print(f"{sym:<10} {w:>9.2%} {pos_type:>8}")


def cmd_serve(args):
    """Starts the StockModel Web UI and API server."""
    import uvicorn
    from stockmodel.web.app import app

    print("=" * 70)
    print(f"StockModel: Starting Professional Web Dashboard on {args.host}:{args.port}...")
    print("=" * 70)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


def main():
    parser = argparse.ArgumentParser(description="StockModel Quantitative Swing Engine")
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # check-gate
    p_gate = subparsers.add_parser("check-gate", help="Run walk-forward complexity gating")
    p_gate.add_argument("--data", type=str, default=None, help="Path to parquet/csv market data")
    p_gate.add_argument("--days", type=int, default=756, help="Synthetic trading days (default: 756)")
    p_gate.add_argument("--seed", type=int, default=42, help="Random seed")

    # run-backtest
    p_bt = subparsers.add_parser("run-backtest", help="Run full simulation backtest")
    p_bt.add_argument("--data", type=str, default=None, help="Path to parquet/csv market data")
    p_bt.add_argument("--days", type=int, default=756, help="Synthetic trading days (default: 756)")
    p_bt.add_argument("--seed", type=int, default=42, help="Random seed")

    # feature-ablation
    p_ab = subparsers.add_parser("feature-ablation", help="Run feature ablation study")
    p_ab.add_argument("--days", type=int, default=756, help="Synthetic trading days")
    p_ab.add_argument("--seed", type=int, default=42, help="Random seed")

    # rank
    p_rk = subparsers.add_parser("rank", help="Generate live decile allocations")
    p_rk.add_argument("--days", type=int, default=252, help="Synthetic trading days (default: 252)")
    p_rk.add_argument("--seed", type=int, default=42, help="Random seed")

    # serve
    p_srv = subparsers.add_parser("serve", help="Start web dashboard and API service")
    p_srv.add_argument("--host", type=str, default="0.0.0.0", help="Host address (default: 0.0.0.0)")
    p_srv.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")

    args = parser.parse_args()
    if args.command == "check-gate":
        cmd_check_gate(args)
    elif args.command == "run-backtest":
        cmd_run_backtest(args)
    elif args.command == "feature-ablation":
        cmd_ablation(args)
    elif args.command == "rank":
        cmd_rank(args)
    elif args.command == "serve":
        cmd_serve(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
