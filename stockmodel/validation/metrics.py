"""
Validation metrics and acceptance gating for quantitative alpha models.
Implements Spearman Rank Information Coefficient (IC) and IC Information Ratio (ICIR).
"""

from typing import Dict, Any, Optional, Sequence
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from stockmodel.data.schema import MarketDataSchema


def evaluate_ic(preds: np.ndarray, targets: np.ndarray) -> float:
    """
    Calculates Spearman Rank Information Coefficient between predictions and targets.

    Args:
        preds: 1D array of predicted scores.
        targets: 1D array of realized cross-sectional targets.

    Returns:
        float: Spearman rank correlation in [-1.0, 1.0]. Returns 0.0 if insufficient valid pairs.
    """
    preds = np.asarray(preds)
    targets = np.asarray(targets)
    valid_mask = ~np.isnan(preds) & ~np.isnan(targets)
    if np.sum(valid_mask) < 2:
        return 0.0

    p_clean = preds[valid_mask]
    t_clean = targets[valid_mask]
    if np.all(p_clean == p_clean[0]) or np.all(t_clean == t_clean[0]):
        return 0.0

    res = spearmanr(p_clean, t_clean)
    stat = getattr(res, "statistic", None)
    if stat is None:
        stat = res[0]
    return float(stat) if not np.isnan(stat) else 0.0


def evaluate_daily_ic_series(
    df: pd.DataFrame,
    pred_col: str = "pred",
    target_col: str = "target",
    date_col: str = MarketDataSchema.DATE,
) -> pd.Series:
    """
    Computes cross-sectional Spearman Rank IC for every unique timestamp t.
    """
    daily_ics = {}
    for dt, group in df.groupby(date_col):
        ic = evaluate_ic(group[pred_col].to_numpy(), group[target_col].to_numpy())
        daily_ics[dt] = ic
    return pd.Series(daily_ics, name="daily_ic").sort_index()


def evaluate_icir(ic_series: Sequence[float], annualization_factor: float = 252.0) -> float:
    """
    Computes the annualized Information Ratio of Information Coefficient (ICIR):
        ICIR = ( E[IC_t] / Std(IC_t) ) * sqrt(252)
    """
    arr = np.asarray(ic_series, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 2:
        return 0.0

    std = float(np.std(arr, ddof=1))
    if std < 1e-8:
        return 0.0

    mean_ic = float(np.mean(arr))
    return float((mean_ic / std) * np.sqrt(annualization_factor))


def check_acceptance_gate(
    mean_ic: float,
    icir: float,
    baseline_ic: Optional[float] = None,
    min_ic: float = 0.035,
    min_icir: float = 0.75,
) -> Dict[str, Any]:
    """
    Evaluates model performance against Section 3.2 Acceptance Gate:
    - Out-of-sample IC >= 0.035
    - ICIR >= 0.75
    - If baseline_ic given: model IC > baseline_ic (Complexity Gating)

    Returns:
        dict containing pass status and breakdown.
    """
    pass_ic = mean_ic >= min_ic
    pass_icir = icir >= min_icir
    pass_baseline = (baseline_ic is None) or (mean_ic > baseline_ic)

    overall_pass = pass_ic and pass_icir and pass_baseline

    return {
        "passed": bool(overall_pass),
        "mean_ic": float(mean_ic),
        "target_ic": float(min_ic),
        "pass_ic": bool(pass_ic),
        "icir": float(icir),
        "target_icir": float(min_icir),
        "pass_icir": bool(pass_icir),
        "baseline_ic": float(baseline_ic) if baseline_ic is not None else None,
        "pass_baseline": bool(pass_baseline),
    }
