"""
High-fidelity synthetic market generator for cross-sectional equities.
Generates realistic point-in-time price, volume, derivatives, macro, and earnings data.
"""

from datetime import date, timedelta
from typing import List, Optional
import numpy as np
import polars as pl
from stockmodel.data.schema import MarketDataSchema, validate_market_data


class SyntheticMarketGenerator:
    """
    Generates multi-asset cross-sectional market data adhering strictly to
    point-in-time hygiene and realistic statistical properties.
    """

    DEFAULT_SECTORS = {
        "Technology": ["AAPL", "MSFT", "NVDA", "AVGO", "ADBE", "ORCL", "CSCO", "CRM", "AMD", "INTC"],
        "Financials": ["JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "SCHW", "AXP", "PNC"],
        "Healthcare": ["JNJ", "UNH", "PFE", "ABBV", "MRK", "TMO", "LLY", "AMGN", "DHR", "BMY"],
        "Consumer": ["AMZN", "TSLA", "WMT", "HD", "MCD", "NKE", "SBUX", "TGT", "COST", "LOW"],
        "Industrials": ["CAT", "DE", "HON", "UNP", "GE", "BA", "LMT", "RTX", "UPS", "FDX"],
        "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "OXY", "MPC", "PSX", "VLO", "HAL"],
    }

    def __init__(self, seed: int = 42):
        self.rng = np.random.default_rng(seed)

    def generate(
        self,
        n_days: int = 756,  # ~3 years of trading days
        start_date: date = date(2023, 1, 3),
        universe: Optional[dict] = None,
    ) -> pl.DataFrame:
        """
        Generates full point-in-time panel dataset for universe across n_days.
        """
        if universe is None:
            universe = self.DEFAULT_SECTORS

        # 1. Generate trading calendar (skipping weekends)
        dates: List[date] = []
        curr = start_date
        while len(dates) < n_days:
            if curr.weekday() < 5:  # Monday to Friday
                dates.append(curr)
            curr += timedelta(days=1)

        # 2. Market and Sector macro factors
        market_daily_ret = self.rng.normal(0.0004, 0.010, size=n_days)
        vix_base = 18.0 + np.cumsum(self.rng.normal(0, 0.5, size=n_days))
        vix_spot = np.clip(vix_base, 11.0, 45.0)
        # VIX term structure: mostly contango (vix_spot / vix_3m < 1.0), occasionally backwardation during spikes
        vix_3m = vix_spot * self.rng.uniform(0.95, 1.15, size=n_days)

        sector_factors = {}
        for sector in universe.keys():
            sector_factors[sector] = 0.6 * market_daily_ret + self.rng.normal(0.0, 0.006, size=n_days)

        records = []
        for sector, symbols in universe.items():
            sector_ret = sector_factors[sector]
            for sym in symbols:
                # Stock specific initial parameters
                initial_price = self.rng.uniform(40.0, 250.0)
                beta = self.rng.uniform(0.7, 1.5)
                idio_vol = self.rng.uniform(0.010, 0.025)
                mkt_cap = self.rng.choice([5e9, 15e9, 50e9, 150e9, 500e9])  # mid vs large cap

                # Earnings cycle every ~63 trading days
                earnings_interval = 63
                cycle_offset = self.rng.integers(0, earnings_interval)

                # Precompute SUE score series and earnings countdown
                sue_series = np.zeros(n_days)
                dte_series = np.zeros(n_days, dtype=int)
                for t in range(n_days):
                    days_into_cycle = (t + cycle_offset) % earnings_interval
                    dte_series[t] = earnings_interval - days_into_cycle
                    quarters_passed = (t + cycle_offset) // earnings_interval
                    quarter_seed = hash((sym, quarters_passed)) % (2**31)
                    q_rng = np.random.default_rng(quarter_seed)
                    base_sue = float(q_rng.normal(0.0, 1.2))
                    sue_series[t] = float(base_sue * np.exp(-days_into_cycle / 40.0))

                # Generate returns with sector loading and non-linear alpha interactions
                # Trees naturally capture joint thresholds (e.g., SUE surprise confirmed by sector strength)
                pead_signal = np.where((sue_series > 0.4) & (sector_ret > 0), 0.0035,
                              np.where((sue_series < -0.4) & (sector_ret < 0), -0.0035, 0.0))
                squeeze_signal = np.where((sue_series > 0.7) & (self.rng.uniform(0, 1, size=n_days) > 0.8), 0.0020, 0.0)
                non_linear_alpha = pead_signal + squeeze_signal
                idio_ret = self.rng.normal(0.0001, idio_vol, size=n_days)
                daily_ret = beta * sector_ret + non_linear_alpha + idio_ret

                # Price series
                price_path = initial_price * np.exp(np.cumsum(daily_ret))
                vol_base = self.rng.uniform(1e6, 8e6)

                for t, dt in enumerate(dates):
                    p_close = float(price_path[t])
                    intra_vol = idio_vol * np.sqrt(p_close) * 0.7
                    p_high = float(p_close * (1.0 + abs(self.rng.normal(0, 0.012))))
                    p_low = float(p_close * (1.0 - abs(self.rng.normal(0, 0.012))))
                    p_open = float(self.rng.uniform(p_low, p_high))
                    p_high = max(p_high, p_open, p_close)
                    p_low = min(p_low, p_open, p_close)

                    vol = int(max(10000, vol_base * (1.0 + self.rng.normal(0, 0.3))))
                    # VWAP close to typical price (H+L+C)/3
                    vwap = float((p_high + p_low + p_close) / 3.0 + self.rng.normal(0, 0.002) * p_close)

                    # Short interest and ADV
                    short_interest = int(vol_base * self.rng.uniform(2.0, 12.0))

                    # Options positioning (GEX & PCR)
                    call_gex = float(self.rng.uniform(5e5, 5e6) * (1.0 if daily_ret[t] > 0 else 0.8))
                    put_gex = float(self.rng.uniform(4e5, 4.5e6) * (1.2 if daily_ret[t] < 0 else 0.7))
                    call_vol = int(vol * self.rng.uniform(0.05, 0.15))
                    put_vol = int(vol * self.rng.uniform(0.04, 0.14))

                    days_to_earnings = int(dte_series[t])
                    sue_score = float(sue_series[t])
                    days_into_cycle = int((t + cycle_offset) % earnings_interval)
                    is_post = bool(days_into_cycle <= 10)
                    last_dt = (dt - timedelta(days=int(days_into_cycle * 7 / 5))).strftime("%Y-%m-%d")
                    next_dt = (dt + timedelta(days=int(days_to_earnings * 7 / 5))).strftime("%Y-%m-%d")
                    status_text = f"Passed {last_dt} ({days_into_cycle}d ago)" if is_post else (f"Blackout: Reports in {days_to_earnings}d" if days_to_earnings <= 3 else f"Reports in {days_to_earnings}d")

                    records.append({
                        MarketDataSchema.DATE: dt,
                        MarketDataSchema.SYMBOL: sym,
                        MarketDataSchema.SECTOR: sector,
                        MarketDataSchema.OPEN: p_open,
                        MarketDataSchema.HIGH: p_high,
                        MarketDataSchema.LOW: p_low,
                        MarketDataSchema.CLOSE: p_close,
                        MarketDataSchema.VOLUME: vol,
                        MarketDataSchema.VWAP: vwap,
                        MarketDataSchema.SHORT_INTEREST: short_interest,
                        MarketDataSchema.ATM_CALL_GEX: call_gex,
                        MarketDataSchema.ATM_PUT_GEX: put_gex,
                        MarketDataSchema.PUT_VOLUME: put_vol,
                        MarketDataSchema.CALL_VOLUME: call_vol,
                        MarketDataSchema.VIX_SPOT: float(vix_spot[t]),
                        MarketDataSchema.VIX_3M: float(vix_3m[t]),
                        MarketDataSchema.DAYS_TO_EARNINGS: int(days_to_earnings),
                        MarketDataSchema.DAYS_SINCE_EARNINGS: int(days_into_cycle),
                        MarketDataSchema.LAST_EARNINGS_DATE: last_dt,
                        MarketDataSchema.NEXT_EARNINGS_DATE: next_dt,
                        MarketDataSchema.IS_POST_EARNINGS: is_post,
                        MarketDataSchema.EARNINGS_STATUS_TEXT: status_text,
                        MarketDataSchema.SUE_SCORE: sue_score,
                        MarketDataSchema.MARKET_CAP: float(mkt_cap),
                    })

        df = pl.DataFrame(records)
        return validate_market_data(df)
