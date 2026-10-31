"""
Configuration settings and hyperparameters for StockModel.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List


@dataclass
class TargetConfig:
    """Target variable formulation configuration."""
    horizon_days: int = 15
    vol_lookback_days: int = 20
    annualization_factor: float = 252.0
    rank_range_min: float = -1.0
    rank_range_max: float = 1.0


@dataclass
class FeatureConfig:
    """Feature engineering pipeline configuration."""
    zscore_lookback: int = 60
    atr_period: int = 14
    adv_period: int = 20
    pcr_fast_period: int = 10
    pcr_slow_period: int = 50
    sma_trend_period: int = 50
    vwap_period: int = 20
    sector_momentum_period: int = 20
    epsilon: float = 1e-8


@dataclass
class ValidationConfig:
    """Purged and Embargoed Walk-Forward Validation configuration."""
    n_splits: int = 5
    train_period_days: int = 504  # ~2 years of trading days
    test_period_days: int = 63    # ~1 quarter of trading days
    horizon_days: int = 15
    embargo_buffer_days: int = 5   # total embargo = horizon + buffer = 20 days


@dataclass
class ModelConfig:
    """LightGBM and ElasticNet baseline model hyperparameters."""
    # LightGBM hyperparameters (regularized for low SNR equity tabular data)
    lgb_params: Dict[str, Any] = field(default_factory=lambda: {
        'objective': 'regression',
        'metric': 'rmse',
        'boosting_type': 'gbdt',
        'max_depth': 4,
        'num_leaves': 15,
        'learning_rate': 0.015,
        'feature_fraction': 0.65,
        'bagging_fraction': 0.80,
        'bagging_freq': 1,
        'lambda_l2': 25.0,
        'min_child_samples': 50,
        'verbose': -1,
        'random_state': 42,
    })
    num_boost_round: int = 1200
    early_stopping_rounds: int = 40

    # ElasticNet baseline hyperparameters
    elastic_alpha: float = 0.005
    elastic_l1_ratio: float = 0.5
    elastic_max_iter: int = 2000
    elastic_random_state: int = 42


@dataclass
class GatingConfig:
    """Acceptance criteria and complexity gating benchmarks."""
    min_oos_ic: float = 0.035
    min_oos_icir: float = 0.75
    require_beat_baseline: bool = True


@dataclass
class ExecutionConfig:
    """Portfolio construction, risk allocation, and transaction friction."""
    long_top_quantile: float = 0.10     # Top decile
    short_bottom_quantile: float = 0.10 # Bottom decile
    allow_short: bool = True            # If False, cash-exit bottom decile
    rebalance_frequency_days: int = 5   # Weekly reranking
    inertia_exit_percentile: float = 0.60 # Retain position unless score drops below 60th pct
    
    # Earnings blackout policy
    earnings_entry_blackout_days: int = 3 # No new entry <= 3 days prior to release
    earnings_trim_hours_prior: int = 48   # 48h prior: trim 50% or close
    earnings_trim_ratio: float = 0.50     # 50% trim

    # Execution friction
    large_cap_slippage_bps: float = 8.0   # 8 basis points
    mid_cap_slippage_bps: float = 15.0    # 15 basis points
    annual_short_borrow_bps: float = 100.0 # 100 bps / year for short positions
    market_cap_mid_threshold: float = 1e10 # $10B threshold for large vs mid cap


@dataclass
class SystemConfig:
    """Master configuration encompassing all subsystems."""
    target: TargetConfig = field(default_factory=TargetConfig)
    feature: FeatureConfig = field(default_factory=FeatureConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    gating: GatingConfig = field(default_factory=GatingConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
