"""
Mandatory Earnings Blackout and Binary Gap Risk Management.

Rules:
1. No new entry allowed <= 3 trading days prior to scheduled quarterly earnings release.
2. Open positions are automatically trimmed by 50% or closed 48 hours (~2 trading days)
   prior to an earnings print to eliminate binary gap risk.
"""

from enum import Enum
from typing import Dict, Set, Tuple
import pandas as pd


class EarningsRiskAction(str, Enum):
    NO_RESTRICTION = "NO_RESTRICTION"
    BLOCK_NEW_ENTRY = "BLOCK_NEW_ENTRY"
    TRIM_OR_CLOSE = "TRIM_OR_CLOSE"


def apply_earnings_blackouts(
    current_holdings: Dict[str, float],
    candidate_symbols: Set[str],
    days_to_earnings_map: Dict[str, int],
    entry_blackout_days: int = 3,
    trim_days_prior: int = 2,
    trim_ratio: float = 0.50,
) -> Tuple[Dict[str, float], Set[str]]:
    """
    Applies earnings risk controls to existing holdings and entry candidate baskets.

    Args:
        current_holdings: Dict of symbol -> current weight.
        candidate_symbols: Set of symbols nominated by ranker for new entry.
        days_to_earnings_map: Dict of symbol -> days remaining until scheduled earnings.
        entry_blackout_days: Entry forbidden if days_to_earnings <= entry_blackout_days.
        trim_days_prior: Existing holdings trimmed if days_to_earnings <= trim_days_prior.
        trim_ratio: Fraction to reduce holding by (default 0.50 for 50% trim).

    Returns:
        Tuple of (adjusted_holdings, approved_entry_candidates)
    """
    # 1. Filter candidate entries
    approved_candidates = set()
    for s in candidate_symbols:
        dte = days_to_earnings_map.get(s, 999)
        if dte > entry_blackout_days:
            approved_candidates.add(s)

    # 2. Adjust existing holdings
    adjusted_holdings: Dict[str, float] = {}
    for s, w in current_holdings.items():
        dte = days_to_earnings_map.get(s, 999)
        if dte <= trim_days_prior:
            # Trim holding by 50%
            adjusted_holdings[s] = w * (1.0 - trim_ratio)
        else:
            adjusted_holdings[s] = w

    return adjusted_holdings, approved_candidates
