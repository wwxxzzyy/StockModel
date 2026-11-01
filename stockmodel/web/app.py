"""
FastAPI Backend Application for StockModel Web UI.
"""

import os
import platform
import socket
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd
import polars as pl
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

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

START_TIME = time.time()
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="StockModel Alpha Platform",
    description="Quantitative Swing Behavior Engine & Cross-Sectional Alpha Dashboard",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory cache for fast interactive panel generation
_PANEL_CACHE: Dict[str, Any] = {}


def _get_panel(days: int = 252, seed: int = 42, source: str = "synthetic"):
    cache_key = f"{days}_{seed}_{source}"
    if cache_key in _PANEL_CACHE:
        return _PANEL_CACHE[cache_key]

    cfg = SystemConfig()
    moomoo_file = Path("data/moomoo_panel.parquet")
    if source == "moomoo":
        if not moomoo_file.exists():
            # Attempt auto-fetch baseline panel
            try:
                from stockmodel.data.moomoo_loader import MoomooMarketLoader
                loader = MoomooMarketLoader(host=os.environ.get("MOOMOO_HOST", "192.168.1.20"))
                ok, _ = loader.check_connection()
                if ok:
                    loader.save_panel(output_path=moomoo_file, days=max(days, 60))
                loader.close()
            except Exception:
                pass

        if not moomoo_file.exists():
            raise HTTPException(
                status_code=404,
                detail="Moomoo live data panel not found. Please click 'Sync Live Data' to fetch from stockserver.",
            )

        raw_df = MarketDataLoader.load_file(moomoo_file)
        unique_dates = sorted(raw_df["date"].unique().to_list())
        if len(unique_dates) > days:
            cutoff = unique_dates[-days]
            raw_df = raw_df.filter(pl.col("date") >= cutoff)
    else:
        gen = SyntheticMarketGenerator(seed=seed)
        raw_df = gen.generate(n_days=days)

    target_df = compute_volatility_adjusted_target(raw_df, cfg.target)
    pipeline = FeaturePipeline(cfg.feature)
    panel_df, feat_cols = pipeline.build_features(target_df)
    pdf = panel_df.to_pandas()

    _PANEL_CACHE[cache_key] = (pdf, feat_cols, cfg)
    return pdf, feat_cols, cfg


@app.get("/api/status")
async def get_status():
    """Returns engine telemetry, host stats, and hyperparameter configuration."""
    uptime_sec = int(time.time() - START_TIME)
    cfg = SystemConfig()

    # Memory info
    mem_total_gb = "Unknown"
    mem_avail_gb = "Unknown"
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
            for line in lines:
                if line.startswith("MemTotal:"):
                    mem_total_gb = f"{int(line.split()[1]) / 1024 / 1024:.2f} GB"
                elif line.startswith("MemAvailable:"):
                    mem_avail_gb = f"{int(line.split()[1]) / 1024 / 1024:.2f} GB"
    except Exception:
        pass

    return {
        "status": "online",
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count() or 2,
        "memory_total": mem_total_gb,
        "memory_available": mem_avail_gb,
        "uptime_seconds": uptime_sec,
        "config": {
            "holding_horizon_days": cfg.target.horizon_days,
            "target_volatility_window": cfg.target.vol_lookback_days,
            "rebalance_frequency_days": cfg.execution.rebalance_frequency_days,
            "inertia_exit_percentile": cfg.execution.inertia_exit_percentile,
            "earnings_entry_blackout_days": cfg.execution.earnings_entry_blackout_days,
            "earnings_trim_hours_prior": cfg.execution.earnings_trim_hours_prior,
            "slippage_large_cap_bps": cfg.execution.large_cap_slippage_bps,
            "slippage_mid_cap_bps": cfg.execution.mid_cap_slippage_bps,
            "short_borrow_annual_rate": cfg.execution.annual_short_borrow_bps,
            "gating_target_ic": cfg.gating.min_oos_ic,
            "gating_target_icir": cfg.gating.min_oos_icir,
            "core_features": [
                {"name": "Short Squeeze Pressure", "category": "Market Structure", "formula": "(Short_Interest / ADV20) * ((P - SMA50) / ATR14)"},
                {"name": "Net Gamma Exposure (GEX)", "category": "Derivatives Positioning", "formula": "Sum(Call_GEX - Put_GEX) ATM"},
                {"name": "Put/Call Ratio Momentum", "category": "Derivatives Positioning", "formula": "PCR_10d / PCR_50d"},
                {"name": "Sector-Relative Momentum", "category": "Trend / Relative Strength", "formula": "Return_20d - Sector_Return_20d"},
                {"name": "VWAP Divergence", "category": "Volume Distribution", "formula": "(P - VWAP_20d) / ATR14"},
                {"name": "VIX Term Structure Slope", "category": "Macro / Regime", "formula": "VIX_spot / VIX3M"},
                {"name": "SUE Score", "category": "Fundamental Drift", "formula": "(EPS_act - EPS_cons) / Std(EPS_est) * PEAD_decay"},
            ],
        },
    }


@app.get("/api/rank")
async def get_rank(
    days: int = Query(252, ge=60, le=1000),
    seed: int = Query(42, ge=0),
    source: str = Query("synthetic", pattern="^(synthetic|moomoo)$"),
    allow_short: bool = Query(True),
):
    """Generates cross-sectional decile rankings with inverse-ATR weighting."""
    try:
        pdf, feat_cols, cfg = _get_panel(days=days, seed=seed, source=source)

        valid = pdf.dropna(subset=feat_cols + ["target"])
        if len(valid) < 50:
            raise HTTPException(status_code=400, detail="Insufficient valid sample points for training")

        ranker = LightGBMRanker(params=cfg.model.lgb_params, num_boost_round=300)
        ranker.fit(valid[feat_cols].to_numpy(), valid["target"].to_numpy(), feature_names=feat_cols)

        latest_date = pdf["date"].max()
        latest_df = pdf[pdf["date"] == latest_date].copy()
        latest_df["pred"] = ranker.predict(latest_df[feat_cols].to_numpy())

        rebal_mgr = RebalanceManager(
            top_decile_quantile=cfg.execution.long_top_quantile,
            bottom_decile_quantile=cfg.execution.short_bottom_quantile,
            entry_blackout_days=cfg.execution.earnings_entry_blackout_days,
            trim_days_prior=int(cfg.execution.earnings_trim_hours_prior / 24),
            trim_ratio=cfg.execution.earnings_trim_ratio,
        )

        atr_series = pd.Series(dict(zip(latest_df["symbol"], latest_df["atr_14"])))
        dte_map = dict(zip(latest_df["symbol"], latest_df["days_to_earnings"]))

        weights = rebal_mgr.rebalance_portfolio(
            current_holdings={},
            scores_df=latest_df[["symbol", "pred"]],
            atr_series=atr_series,
            days_to_earnings_map=dte_map,
            allow_short=allow_short,
        )

        # Build detailed allocation response
        allocations = []
        for _, row in latest_df.iterrows():
            sym = row["symbol"]
            w = weights.get(sym, 0.0)
            in_blackout = (row["days_to_earnings"] <= cfg.execution.earnings_entry_blackout_days)

            allocations.append({
                "symbol": sym,
                "weight": float(w),
                "weight_pct": round(float(w) * 100, 2),
                "type": "LONG" if w > 0.0001 else ("SHORT" if w < -0.0001 else "FLAT"),
                "pred_score": round(float(row["pred"]), 4),
                "atr_14": round(float(row["atr_14"]), 2),
                "close": round(float(row["close"]), 2),
                "sector": row.get("sector", "Technology"),
                "market_cap": float(row.get("market_cap", 0)),
                "days_to_earnings": int(row["days_to_earnings"]),
                "in_blackout": bool(in_blackout),
                "short_interest": round(float(row.get("short_interest", 0)), 1),
                "pcr_ratio": round(float(row.get("pcr_ratio", 1.0)), 2),
                "sue_score": round(float(row.get("sue_score", 0.0)), 3),
            })

        # Sort: Active allocations first by absolute weight, then non-active
        allocations.sort(key=lambda x: (abs(x["weight"]) > 0, abs(x["weight"])), reverse=True)

        long_weights = sum(a["weight"] for a in allocations if a["weight"] > 0)
        short_weights = sum(abs(a["weight"]) for a in allocations if a["weight"] < 0)
        gross_exposure = long_weights + short_weights
        net_exposure = long_weights - short_weights

        return {
            "source": source,
            "as_of_date": str(latest_date),
            "summary": {
                "long_positions": sum(1 for a in allocations if a["type"] == "LONG"),
                "short_positions": sum(1 for a in allocations if a["type"] == "SHORT"),
                "flat_positions": sum(1 for a in allocations if a["type"] == "FLAT"),
                "gross_exposure_pct": round(gross_exposure * 100, 2),
                "net_exposure_pct": round(net_exposure * 100, 2),
                "total_long_weight_pct": round(long_weights * 100, 2),
                "total_short_weight_pct": round(short_weights * 100, 2),
            },
            "allocations": allocations,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/backtest")
async def get_backtest(
    days: int = Query(300, ge=100, le=1000),
    seed: int = Query(42, ge=0),
    source: str = Query("synthetic", pattern="^(synthetic|moomoo)$"),
    rebalance_freq: Optional[int] = Query(None, ge=1, le=20),
    inertia_pct: Optional[float] = Query(None, ge=0.1, le=0.9),
):
    """Executes full backtest simulation and returns performance tearsheet & time-series."""
    try:
        pdf, feat_cols, cfg = _get_panel(days=days, seed=seed, source=source)

        if rebalance_freq is not None:
            cfg.execution.rebalance_frequency_days = rebalance_freq
        if inertia_pct is not None:
            cfg.execution.inertia_exit_percentile = inertia_pct

        # Evaluate gating
        gator = ComplexityGator(cfg)
        gating_res = gator.evaluate(pdf, feat_cols, target_col="target")

        # Fit LightGBM ranker
        valid_train = pdf.dropna(subset=feat_cols + ["target"])
        ranker = LightGBMRanker(params=cfg.model.lgb_params, num_boost_round=cfg.model.num_boost_round)
        ranker.fit(valid_train[feat_cols].to_numpy(), valid_train["target"].to_numpy(), feature_names=feat_cols)
        pdf["pred"] = ranker.predict(pdf[feat_cols].to_numpy())

        # Run engine
        engine = BacktestEngine(cfg)
        btest_res = engine.run(pdf, pred_col="pred")
        metrics = compute_metrics(btest_res.daily_records)

        # Prepare daily curve
        daily_records = btest_res.daily_records.copy()
        initial_cap = 1_000_000.0
        daily_records["benchmark_nav"] = initial_cap * np.cumprod(1.0 + daily_records["benchmark_return"].fillna(0.0).to_numpy())
        running_max = np.maximum.accumulate(daily_records["nav"].to_numpy())
        daily_records["drawdown"] = (daily_records["nav"].to_numpy() - running_max) / np.maximum(running_max, 1e-8)

        daily_curve = []
        for _, row in daily_records.iterrows():
            daily_curve.append({
                "date": str(row["date"]),
                "nav": round(float(row["nav"]), 2),
                "benchmark_nav": round(float(row["benchmark_nav"]), 2),
                "net_return": round(float(row["net_return"]), 4),
                "benchmark_return": round(float(row["benchmark_return"]), 4),
                "drawdown_pct": round(float(row["drawdown"]) * 100, 2),
                "turnover": round(float(row.get("turnover", 0.0)), 4),
                "friction_drag": round(float(row.get("friction_drag", 0.0)) * 10000, 2),
            })

        return {
            "source": source,
            "metrics": {
                "total_return_pct": round(metrics.total_return * 100, 2),
                "annualized_return_pct": round(metrics.annualized_return * 100, 2),
                "annualized_volatility_pct": round(metrics.annualized_volatility * 100, 2),
                "sharpe_ratio": round(metrics.sharpe_ratio, 2),
                "sortino_ratio": round(metrics.sortino_ratio, 2),
                "max_drawdown_pct": round(metrics.max_drawdown * 100, 2),
                "calmar_ratio": round(metrics.calmar_ratio, 2),
                "win_rate_pct": round(metrics.win_rate * 100, 2),
                "profit_factor": round(metrics.profit_factor, 2),
                "annualized_turnover": round(metrics.annualized_turnover, 2),
                "total_friction_bps": round(metrics.friction_drag_bps, 1),
                "benchmark_return_pct": round(metrics.benchmark_return * 100, 2),
                "alpha_pct": round(metrics.alpha_over_benchmark * 100, 2),
                "oos_ic": round(gating_res.lgb_mean_ic, 4),
                "oos_icir": round(gating_res.lgb_icir, 2),
                "final_nav": round(btest_res.final_nav, 2),
                "total_turnover": round(btest_res.total_turnover, 2),
            },
            "daily_curve": daily_curve,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/check-gate")
async def get_check_gate(
    days: int = Query(300, ge=100, le=1000),
    seed: int = Query(42, ge=0),
    source: str = Query("synthetic", pattern="^(synthetic|moomoo)$"),
):
    """Executes purged walk-forward cross-validation and complexity gating."""
    try:
        pdf, feat_cols, cfg = _get_panel(days=days, seed=seed, source=source)
        gator = ComplexityGator(cfg)
        result = gator.evaluate(pdf, feat_cols, target_col="target")

        folds = []
        for f in result.fold_evaluations:
            folds.append({
                "fold_idx": f.fold_idx,
                "train_start": str(f.train_start),
                "train_end": str(f.train_end),
                "test_start": str(f.test_start),
                "test_end": str(f.test_end),
                "gbdt_ic": round(f.lgb_ic, 4),
                "elastic_ic": round(f.elastic_ic, 4),
                "gbdt_outperformed": bool(f.lgb_outperformed),
            })

        return {
            "source": source,
            "passed": bool(result.passed),
            "summary": {
                "gbdt_mean_ic": round(result.lgb_mean_ic, 4),
                "gbdt_icir": round(result.lgb_icir, 2),
                "elastic_mean_ic": round(result.elastic_mean_ic, 4),
                "elastic_icir": round(result.elastic_icir, 2),
                "ic_delta": round(result.ic_delta, 4),
                "target_ic": cfg.gating.min_oos_ic,
                "target_icir": cfg.gating.min_oos_icir,
                "pass_ic": bool(result.gate_details.get("pass_ic", False)),
                "pass_icir": bool(result.gate_details.get("pass_icir", False)),
                "pass_baseline": bool(result.gate_details.get("pass_baseline", False)),
            },
            "folds": folds,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ablation")
async def get_ablation(
    days: int = Query(252, ge=100, le=756),
    seed: int = Query(42, ge=0),
    source: str = Query("synthetic", pattern="^(synthetic|moomoo)$"),
):
    """Runs systematic leave-one-feature-out ablation study."""
    try:
        pdf, feat_cols, cfg = _get_panel(days=days, seed=seed, source=source)
        ablation = FeatureAblationStudy(cfg)
        results = ablation.run_study(pdf, feat_cols)

        feature_meta = {
            "feat_short_squeeze_pressure": ("Short Squeeze Pressure", "Market Structure"),
            "feat_net_gex": ("Net Gamma Exposure (GEX)", "Derivatives Positioning"),
            "feat_pcr_momentum": ("Put/Call Ratio Momentum", "Derivatives Positioning"),
            "feat_sector_rel_momentum": ("Sector-Relative Momentum", "Trend / Relative Strength"),
            "feat_vwap_divergence": ("VWAP Divergence", "Volume Distribution"),
            "feat_vix_term_structure": ("VIX Term Structure Slope", "Macro / Regime"),
            "feat_sue_score": ("SUE Score", "Fundamental Drift"),
        }

        output = []
        for r in results:
            pretty_name, category = feature_meta.get(r.feature_name, (r.feature_name, "General"))
            output.append({
                "feature_id": r.feature_name,
                "feature_name": pretty_name,
                "category": category,
                "ic_with_feature": round(r.ic_with_feature, 4),
                "ic_without_feature": round(r.ic_without_feature, 4),
                "ic_delta": round(r.ic_delta, 4),
                "action": r.action,
            })

        output.sort(key=lambda x: x["ic_delta"], reverse=True)
        return {"source": source, "features": output}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/moomoo/status")
async def get_moomoo_status(host: str = "192.168.1.20", port: int = 11111):
    """Checks connectivity to Moomoo OpenD on stockserver and cached panel telemetry."""
    from stockmodel.data.moomoo_loader import MoomooMarketLoader
    loader = MoomooMarketLoader(host=host, port=port)
    ok, msg = loader.check_connection()
    loader.close()

    moomoo_file = Path("data/moomoo_panel.parquet")
    cached = moomoo_file.exists()
    panel_info = {
        "cached": cached,
        "path": str(moomoo_file.resolve()) if cached else None,
        "size_kb": round(moomoo_file.stat().st_size / 1024, 1) if cached else 0,
        "rows": 0,
        "symbols": 0,
        "start_date": None,
        "end_date": None,
        "last_modified": None,
    }
    if cached:
        try:
            df = pl.read_parquet(moomoo_file)
            panel_info["rows"] = df.height
            panel_info["symbols"] = df["symbol"].n_unique()
            dates = df["date"].unique().sort().to_list()
            if dates:
                panel_info["start_date"] = str(dates[0])
                panel_info["end_date"] = str(dates[-1])
            mtime = moomoo_file.stat().st_mtime
            panel_info["last_modified"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
        except Exception:
            pass

    return {
        "connected": ok,
        "message": msg,
        "host": host,
        "port": port,
        "panel": panel_info,
    }


@app.post("/api/moomoo/sync")
async def sync_moomoo_data(
    days: int = Query(252, ge=20, le=504),
    host: str = Query("192.168.1.20"),
    port: int = Query(11111),
    symbols: Optional[str] = Query(None),
):
    """Syncs live data from Moomoo OpenD into data/moomoo_panel.parquet."""
    from stockmodel.data.moomoo_loader import MoomooMarketLoader
    tickers = [s.strip().upper() for s in symbols.split(",")] if symbols else None
    loader = MoomooMarketLoader(host=host, port=port, universe=tickers)
    ok, msg = loader.check_connection()
    if not ok:
        loader.close()
        raise HTTPException(status_code=503, detail=f"OpenD unreachable at {host}:{port}: {msg}")

    out_path = Path("data/moomoo_panel.parquet")
    saved_path = str(loader.save_panel(output_path=out_path, days=days, universe=tickers))
    loader.close()
    _PANEL_CACHE.clear()

    # Read back summary
    df = pl.read_parquet(out_path)
    return {
        "status": "success",
        "message": f"Successfully ingested {df.height} records across {df['symbol'].n_unique()} assets from Moomoo OpenD.",
        "path": saved_path,
        "days": days,
        "rows": df.height,
        "symbols": df["symbol"].n_unique(),
    }


# Static file serving
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse({"status": "StockModel API online. Frontend files missing in static/."})
