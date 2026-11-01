"""
Single Stock Research & Diagnostics Engine.
Provides deep-dive quantitative analysis, model inference, earnings lifecycle,
derivatives positioning, and historical chart telemetry for any user-selected ticker.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import polars as pl

from stockmodel.config import SystemConfig
from stockmodel.data.loader import MarketDataLoader
from stockmodel.data.moomoo_loader import MoomooMarketLoader, SECTOR_MAP, analyze_earnings_lifecycle
from stockmodel.data.schema import MarketDataSchema
from stockmodel.data.synthetic import SyntheticMarketGenerator
from stockmodel.features.pipeline import FeaturePipeline
from stockmodel.models.lightgbm_ranker import LightGBMRanker
from stockmodel.targets.volatility_adjusted import compute_volatility_adjusted_target

logger = logging.getLogger(__name__)


def research_single_stock(
    symbol: str,
    days: int = 252,
    source: str = "moomoo",
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Performs institutional-grade single stock quantitative research.
    Works for any ticker — whether already in the default universe or fetched ad-hoc from OpenD.
    """
    sym = symbol.upper().strip().replace("US.", "")
    cfg = SystemConfig()
    moomoo_file = Path("data/moomoo_panel.parquet")

    # 1. Load or synthesize the cross-sectional benchmark panel
    if source == "moomoo":
        if not moomoo_file.exists():
            loader = MoomooMarketLoader(host=host or os.environ.get("MOOMOO_HOST", "192.168.1.20"), port=port)
            loader.save_panel(output_path=moomoo_file, days=days)
            loader.close()

        raw_df = MarketDataLoader.load_file(moomoo_file)
        unique_dates = sorted(raw_df["date"].unique().to_list())
        if len(unique_dates) > days:
            cutoff = unique_dates[-days]
            raw_df = raw_df.filter(pl.col("date") >= cutoff)
    else:
        gen = SyntheticMarketGenerator(seed=42)
        raw_df = gen.generate(n_days=days)

    target_df = compute_volatility_adjusted_target(raw_df, cfg.target)
    pipeline = FeaturePipeline(cfg.feature)
    panel_df, feat_cols = pipeline.build_features(target_df)
    pdf = panel_df.to_pandas()

    # 2. Check if symbol exists in panel; if not and source==moomoo, fetch ad-hoc from OpenD
    if sym not in pdf["symbol"].unique():
        if source == "moomoo":
            logger.info("Ticker %s not in baseline panel. Ingesting ad-hoc from OpenD...", sym)
            m_host = host or os.environ.get("MOOMOO_HOST", "192.168.1.20")
            loader = MoomooMarketLoader(host=m_host, port=port)
            try:
                sym_bars = loader.fetch_historical_bars([sym], days=days)
                sym_snap = loader.fetch_market_snapshots([sym])
                sym_earn = loader.fetch_earnings_calendar([sym])
                sym_si = loader.fetch_short_interest_data([sym])
                cur_p = float(sym_bars["close"].iloc[-1])
                c_gex, p_gex, c_vol, p_vol = loader.fetch_options_gex(sym, cur_p)
            finally:
                loader.close()

            # Format single stock bars to match schema
            sym_bars["sector"] = SECTOR_MAP.get(sym, "Technology")
            sym_bars["market_cap"] = sym_snap.get(sym, {}).get("market_cap", 50_000_000_000.0)

            # Map macro VIX from existing panel
            vix_map = dict(zip(pdf["date"].astype(str), pdf["vix_spot"]))
            vix3m_map = dict(zip(pdf["date"].astype(str), pdf["vix_3m"]))
            sym_bars["vix_spot"] = sym_bars["date"].map(lambda d: vix_map.get(d, 17.5))
            sym_bars["vix_3m"] = sym_bars["date"].map(lambda d: vix3m_map.get(d, 19.0))

            # Earnings lifecycle
            all_dates = sorted(sym_bars["date"].unique())
            lifecycle_records = [
                analyze_earnings_lifecycle(sym, d, sym_earn.get(sym, []), unique_dates=all_dates)
                for d in sym_bars["date"]
            ]
            lcdf = pd.DataFrame(lifecycle_records)
            for c in lcdf.columns:
                sym_bars[c] = lcdf[c]

            # Short interest
            if sym in sym_si and not sym_si[sym].empty:
                df_si = sym_si[sym]
                sym_bars["short_interest"] = sym_bars["date"].map(
                    lambda d: float(df_si[df_si["date"] <= d]["shares_short"].iloc[-1])
                    if not df_si[df_si["date"] <= d].empty else float(df_si["shares_short"].iloc[0])
                )
            else:
                sym_bars["short_interest"] = (sym_bars["market_cap"] / np.maximum(sym_bars["close"], 1.0)) * 0.025

            sym_bars["sue_score"] = 0.0
            sym_bars["atm_call_gex"] = c_gex
            sym_bars["atm_put_gex"] = p_gex
            sym_bars["call_volume"] = c_vol
            sym_bars["put_volume"] = p_vol

            # Combine and re-run pipeline
            sym_pl = pl.from_pandas(sym_bars).with_columns(pl.col("date").str.to_date().alias("date"))
            combined_raw = pl.concat([raw_df.select(sym_pl.columns), sym_pl], how="vertical_relaxed")
            target_df = compute_volatility_adjusted_target(combined_raw, cfg.target)
            panel_df, feat_cols = pipeline.build_features(target_df)
            pdf = panel_df.to_pandas()
        else:
            raise ValueError(f"Ticker '{sym}' not found in simulation universe.")

    # 3. Train LightGBM model on latest cross-section to get consistent ranking
    valid = pdf.dropna(subset=feat_cols + ["target"])
    ranker = LightGBMRanker(params=cfg.model.lgb_params, num_boost_round=300)
    ranker.fit(valid[feat_cols].to_numpy(), valid["target"].to_numpy(), feature_names=feat_cols)

    latest_date = pdf["date"].max()
    latest_df = pdf[pdf["date"] == latest_date].copy()
    latest_df["pred"] = ranker.predict(latest_df[feat_cols].to_numpy())

    if sym not in latest_df["symbol"].values:
        raise ValueError(f"Ticker '{sym}' has no valid record on latest date {latest_date}.")

    sym_row = latest_df[latest_df["symbol"] == sym].iloc[0]
    sym_history = pdf[pdf["symbol"] == sym].sort_values("date")

    # 4. Cross-sectional ranking percentile
    all_preds = latest_df["pred"].to_numpy()
    sym_score = float(sym_row["pred"])
    percentile = float(round(float((all_preds < sym_score).mean() * 100), 1))
    decile = int(np.clip(int(percentile / 10) + 1, 1, 10))

    # 5. Volatility & Position Sizing
    close_price = float(sym_row["close"])
    atr_14 = float(sym_row.get("atr_14", 5.0))
    atr_pct = round((atr_14 / max(close_price, 0.01)) * 100, 2)
    median_atr = float(latest_df["atr_14"].median()) if "atr_14" in latest_df else 5.0
    suggested_weight_pct = round(float(np.clip((median_atr / max(atr_14, 0.1)) * 10.0, 1.0, 15.0)), 2)

    # 6. Earnings Risk & Lifecycle
    dte = int(sym_row.get("days_to_earnings", 45))
    dse = int(sym_row.get("days_since_earnings", -1)) if pd.notna(sym_row.get("days_since_earnings")) else -1
    is_post = bool(sym_row.get("is_post_earnings", False))
    in_blackout = bool(dte <= cfg.execution.earnings_entry_blackout_days)
    last_earn_date = str(sym_row.get("last_earnings_date", ""))
    next_earn_date = str(sym_row.get("next_earnings_date", ""))
    status_text = str(sym_row.get("earnings_status_text", ""))

    # 7. Signal & Recommendation Decision
    if in_blackout:
        signal = "BLACKOUT_AVOID"
        signal_label = "EARNINGS BLACKOUT — ENTRY FORBIDDEN"
        signal_badge = "blackout"
        signal_color = "#f59e0b"
        recommendation = "AVOID"
        blackout_risk = f"CRITICAL: Reports in {dte}d ({next_earn_date})"
    elif percentile >= 90:
        signal = "STRONG_LONG"
        signal_label = "TOP DECILE STRONG LONG"
        signal_badge = "long"
        signal_color = "#10b981"
        recommendation = "STRONG BUY / LONG"
        blackout_risk = "SAFE: Outside Blackout Window"
    elif percentile >= 70:
        signal = "LONG"
        signal_label = "OUTPERFORM LONG BIAS"
        signal_badge = "long"
        signal_color = "#10b981"
        recommendation = "BUY / ACCUMULATE"
        blackout_risk = "SAFE: Outside Blackout Window"
    elif percentile <= 10:
        signal = "STRONG_SHORT"
        signal_label = "BOTTOM DECILE STRONG SHORT"
        signal_badge = "short"
        signal_color = "#f43f5e"
        recommendation = "STRONG SELL / SHORT"
        blackout_risk = "SAFE: Outside Blackout Window"
    elif percentile <= 30:
        signal = "SHORT"
        signal_label = "UNDERPERFORM SHORT BIAS"
        signal_badge = "short"
        signal_color = "#f43f5e"
        recommendation = "REDUCE / SHORT"
        blackout_risk = "SAFE: Outside Blackout Window"
    else:
        signal = "NEUTRAL"
        signal_label = "NEUTRAL / HOLD"
        signal_badge = "flat"
        signal_color = "#94a3b8"
        recommendation = "HOLD / BENCHMARK WEIGHT"
        blackout_risk = "SAFE: Outside Blackout Window"

    if is_post and not in_blackout:
        blackout_risk = f"POST-EARNINGS: Passed on {last_earn_date} ({dse}d ago) ~{dte}d to next"

    # 8. 7-Feature Detailed Diagnostics
    features_detail = []
    feature_meta = {
        "feat_short_squeeze_pressure": {
            "name": "Short Squeeze Pressure",
            "category": "Market Structure",
            "explain": "Measures potential short squeeze vulnerability via (Short Interest / ADV20) * ((P - SMA50) / ATR14).",
        },
        "feat_net_gex": {
            "name": "Net Gamma Exposure (GEX)",
            "category": "Derivatives Positioning",
            "explain": "Net ATM dealer gamma positioning. Positive GEX acts as volatility dampener; negative GEX fuels momentum.",
        },
        "feat_pcr_momentum": {
            "name": "Put/Call Ratio Momentum",
            "category": "Derivatives Positioning",
            "explain": "10-day vs 50-day Put/Call volume momentum. Decreasing PCR indicates bullish institutional speculation.",
        },
        "feat_sector_relative_momentum": {
            "name": "Sector-Relative Momentum",
            "category": "Trend / Relative Strength",
            "explain": "Excess 20-day return relative to equal-weighted sector benchmark.",
        },
        "feat_vwap_divergence": {
            "name": "VWAP Divergence",
            "category": "Volume Distribution",
            "explain": "Distance of current spot price from 20-day rolling institutional volume-weighted average price in ATR units.",
        },
        "feat_vix_slope": {
            "name": "VIX Term Structure Slope",
            "category": "Macro / Regime",
            "explain": "VIX spot / VIX 3M ratio. Values < 1.0 (Contango) favor equity carry; > 1.0 indicates macro panic.",
        },
        "feat_sue_score": {
            "name": "SUE Score (PEAD Drift)",
            "category": "Fundamental Drift",
            "explain": "Standardized Unexpected Earnings surprise score with exponential decay post announcement.",
        },
    }

    for f_col in feat_cols:
        val = float(sym_row[f_col]) if f_col in sym_row and pd.notna(sym_row[f_col]) else 0.0
        dist = latest_df[f_col].to_numpy()
        f_pct = float(round(float((dist < val).mean() * 100), 1))
        sentiment = "BULLISH" if val > 0.25 else ("BEARISH" if val < -0.25 else "NEUTRAL")

        meta = feature_meta.get(f_col, {"name": f_col, "category": "General", "explain": ""})
        features_detail.append({
            "id": f_col,
            "name": meta["name"],
            "category": meta["category"],
            "score": round(val, 3),
            "percentile": f_pct,
            "sentiment": sentiment,
            "explanation": meta["explain"],
        })

    # 9. Synthetic Rationale Narrative
    narrative_parts = [
        f"{sym} ranks in the {percentile}th percentile (Decile {decile}) with a predicted 2-4W alpha score of {sym_score:+.4f}.",
    ]
    if in_blackout:
        narrative_parts.append(
            f"CRITICAL WARNING: Scheduled earnings release is in {dte} trading day(s) on {next_earn_date}. Under strict risk policy, entry is prohibited to prevent binary gap losses."
        )
    elif is_post:
        narrative_parts.append(
            f"The asset announced earnings {dse} day(s) ago on {last_earn_date}. It is currently in a Post-Earnings Announcement Drift (PEAD) cycle with ~{dte} trading days remaining until next reporting."
        )

    top_feat = max(features_detail, key=lambda x: abs(x["score"]))
    narrative_parts.append(
        f"Primary driver: {top_feat['name']} ({top_feat['score']:+.2f}, {top_feat['sentiment']}). Current 14-day volatility stands at ${atr_14:.2f} ({atr_pct}%), recommending an inverse-ATR position sizing weight of {suggested_weight_pct}%."
    )
    summary_narrative = " ".join(narrative_parts)

    # 10. Chart time-series (last 90 bars)
    chart_bars = sym_history.tail(90)
    chart_series = []
    prev_close = float(chart_bars["close"].iloc[0])
    for _, row in chart_bars.iterrows():
        c = float(row["close"])
        chg = c - prev_close
        prev_close = c
        chart_series.append({
            "date": str(row["date"]).split()[0],
            "open": round(float(row.get("open", c)), 2),
            "high": round(float(row.get("high", c)), 2),
            "low": round(float(row.get("low", c)), 2),
            "close": round(c, 2),
            "volume": int(row.get("volume", 0)),
            "vwap": round(float(row.get("vwap", c)), 2),
            "sma_50": round(float(row.get("sma_50", c)), 2) if "sma_50" in row and pd.notna(row["sma_50"]) else None,
            "atr_14": round(float(row.get("atr_14", 0)), 2) if "atr_14" in row and pd.notna(row["atr_14"]) else None,
            "change": round(chg, 2),
        })

    # Return full dossier
    prev_day_close = float(sym_history["close"].iloc[-2]) if len(sym_history) >= 2 else close_price
    change_1d = round(close_price - prev_day_close, 2)
    change_1d_pct = round((change_1d / max(prev_day_close, 0.01)) * 100, 2)

    return {
        "symbol": sym,
        "name": f"{sym} ({SECTOR_MAP.get(sym, 'Equities')})",
        "sector": SECTOR_MAP.get(sym, "Technology"),
        "as_of_date": str(latest_date).split()[0],
        "source": source,
        "quote": {
            "close": round(close_price, 2),
            "change_1d": change_1d,
            "change_1d_pct": change_1d_pct,
            "open": round(float(sym_row.get("open", close_price)), 2),
            "high": round(float(sym_row.get("high", close_price)), 2),
            "low": round(float(sym_row.get("low", close_price)), 2),
            "volume": int(sym_row.get("volume", 0)),
            "market_cap": float(sym_row.get("market_cap", 0)),
            "market_cap_fmt": f"${float(sym_row.get('market_cap', 0))/1e9:.1f}B",
            "atr_14": round(atr_14, 2),
            "atr_14_pct": atr_pct,
            "sma_50": round(float(sym_row.get("sma_50", close_price)), 2) if pd.notna(sym_row.get("sma_50")) else None,
            "vwap_20": round(float(sym_row.get("vwap", close_price)), 2) if pd.notna(sym_row.get("vwap")) else None,
            "high_52w": round(float(sym_history["high"].max()), 2),
            "low_52w": round(float(sym_history["low"].min()), 2),
        },
        "verdict": {
            "pred_score": round(sym_score, 4),
            "percentile": percentile,
            "decile": decile,
            "signal": signal,
            "signal_label": signal_label,
            "signal_badge": signal_badge,
            "signal_color": signal_color,
            "recommendation": recommendation,
            "suggested_weight_pct": suggested_weight_pct,
            "summary_narrative": summary_narrative,
        },
        "earnings": {
            "days_to_earnings": dte,
            "days_since_earnings": dse,
            "last_earnings_date": last_earn_date,
            "next_earnings_date": next_earn_date,
            "is_post_earnings": is_post,
            "in_blackout": in_blackout,
            "status_text": status_text,
            "blackout_risk": blackout_risk,
        },
        "derivatives": {
            "call_gex": float(sym_row.get("atm_call_gex", 0)),
            "put_gex": float(sym_row.get("atm_put_gex", 0)),
            "net_gex": round(float(sym_row.get("atm_call_gex", 0)) - float(sym_row.get("atm_put_gex", 0)), 1),
            "call_volume": float(sym_row.get("call_volume", 0)),
            "put_volume": float(sym_row.get("put_volume", 0)),
            "pcr_ratio": round(float(sym_row.get("put_volume", 1.0)) / max(float(sym_row.get("call_volume", 1.0)), 1.0), 2),
            "short_interest": float(sym_row.get("short_interest", 0)),
            "adv_20": float(sym_row.get("adv_20", sym_row.get("volume", 1e6))),
            "days_to_cover": round(float(sym_row.get("short_interest", 0)) / max(float(sym_row.get("adv_20", 1e6)), 1.0), 1),
            "gex_regime": "POSITIVE_GEX (Dealer Stability)" if (float(sym_row.get("atm_call_gex", 0)) - float(sym_row.get("atm_put_gex", 0))) >= 0 else "NEGATIVE_GEX (Dealer Momentum)",
        },
        "features": features_detail,
        "history": chart_series,
    }
