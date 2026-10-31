# StockModel: Quantitative Swing Behavior Model (2–4 Week Horizon)

A systematic quantitative trading and alpha research system designed to predict relative multi-week equity performance using cross-sectional gradient-boosted decision trees (LightGBM) with an ElasticNet linear baseline and strict temporal leakage prevention.

---

## 1. Core Principles

- **Cross-Sectional Over Directional:** Assets are ranked relative to one another at each timestamp $t$ rather than attempting to forecast broad market direction.
- **Volatility-Adjusted Target:** Targets are scaled by realized 20-day annualized asset volatility:
  $$y_{i, t} = \text{Rank}_{t}\left( \frac{\ln(P_{i, t+H} / P_{i, t})}{\sigma_{i, t, 20\text{d}} \cdot \sqrt{H}} \right)$$
  uniformly scaled into the range $[-1.0, 1.0]$.
- **Complexity Gating:** Complex non-linear models (GBDTs) must empirically outperform an ElasticNet linear baseline in out-of-sample Information Coefficient (IC) before deployment, meeting $\text{IC} \ge 0.035$ and $\text{ICIR} \ge 0.75$.
- **Strict Temporal Hygiene:** Historical evaluation employs point-in-time data with purged and embargoed walk-forward cross-validation ($H + 5\text{ days}$ buffer) to eliminate serial correlation and label leakage.

---

## 2. Feature Engineering Pipeline (7 Core Features)

All features are normalized cross-sectionally per timestamp $t$ into uniform quantile scores in $[-1.0, 1.0]$:

| Category | Feature Name | Description / Formula |
| :--- | :--- | :--- |
| **Market Structure** | **Short Squeeze Pressure** | $\frac{\text{Short Interest}_t}{\text{ADV}_{20}} \times \left( \frac{P_t - \text{SMA}_{50, t}}{\text{ATR}_{14, t}} \right)$ |
| **Derivatives Positioning** | **Net Gamma Exposure (GEX)** | $\sum (\text{Call GEX} - \text{Put GEX})$ around current ATM strike |
| **Derivatives Positioning** | **Put/Call Ratio Momentum** | $\frac{\text{PCR}_{10\text{d}}}{\text{PCR}_{50\text{d}}}$ |
| **Trend / Relative Strength** | **Sector-Relative Momentum** | $r_{i, 20\text{d}} - r_{\text{Sector}(i), 20\text{d}}$ |
| **Volume Distribution** | **VWAP Divergence** | $\frac{P_t - \text{VWAP}_{20\text{d}}}{\text{ATR}_{14, t}}$ |
| **Macro / Regime** | **VIX Term Structure Slope** | $\frac{\text{VIX}_{\text{spot}}}{\text{VIX3M}}$ |
| **Fundamental Drift** | **SUE Score** | $\frac{\text{EPS}_{\text{actual}} - \text{EPS}_{\text{consensus}}}{\sigma(\text{EPS}_{\text{estimates}})}$ with PEAD drift decay |

---

## 3. Execution & Risk Management Policy

1. **Portfolio Construction:**
   - **Selection:** Top decile predicted score constitutes the long candidate basket; bottom decile constitutes the short candidate basket (or serves as a cash-exit filter if long-only).
   - **Position Sizing:** Inverse realized 14-day Average True Range (ATR) weighting to equalize volatility contribution per position:
     $$w_i = \frac{1 / \text{ATR}_{14, i}}{\sum_{j=1}^{N} (1 / \text{ATR}_{14, j})}$$
2. **Mandatory Earnings Blackouts:**
   - No new entry allowed $\le 3$ trading days prior to scheduled quarterly earnings release.
   - Open positions are automatically trimmed by 50% or closed 48 hours prior to an earnings print to avoid binary gap risk.
3. **Turnover & Rebalancing Inertia:**
   - Reranking occurs weekly (every 5 trading days).
   - **Inertia Band:** A holding is not liquidated on rebalance unless its cross-sectional score falls below the 60th percentile, suppressing portfolio turnover and friction.
4. **Execution Friction Model:**
   - Slippage model: 8 basis points per trade for large caps ($\ge \$10\text{B}$), 15 basis points for mid caps ($< \$10\text{B}$).
   - Short borrow cost: Subtracted continuously using annualized borrow rates (100 bps / 252 daily).

---

## 4. Installation

```bash
# Clone and enter directory
cd StockModel

# Create virtual environment and install package with dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## 5. CLI Usage

The package exposes the `stockmodel` command-line tool:

### 1. Run Purged Walk-Forward Complexity Gating
Evaluates out-of-sample IC and ICIR across purged walk-forward splits, checking whether LightGBM beats the ElasticNet benchmark:
```bash
stockmodel check-gate --days 756
```

### 2. Run Full Simulation Backtest
Simulates execution under friction, weekly rebalancing, inertia bands, and earnings blackouts, generating a comprehensive tear-sheet:
```bash
stockmodel run-backtest --days 756
```

### 3. Run Systematic Feature Ablation Study
Performs leave-one-feature-out analysis to identify and prune non-informative features:
```bash
stockmodel feature-ablation --days 300
```

### 4. Live Decile Ranking & Position Sizing
Generates current top/bottom decile long and short allocations with inverse-ATR weighting:
```bash
stockmodel rank
```

---

## 6. Project Architecture

```
StockModel/
├── pyproject.toml                     # Package specification & entry points
├── requirements.txt                   # Production dependencies
├── README.md                          # Documentation & usage guide
├── stockmodel/
│   ├── config.py                      # Hyperparameters & execution settings
│   ├── data/
│   │   ├── schema.py                  # Point-in-time market data schema
│   │   ├── loader.py                  # Parquet & CSV data ingestion
│   │   └── synthetic.py               # Point-in-time synthetic market panel generator
│   ├── targets/
│   │   └── volatility_adjusted.py     # Volatility-adjusted target ranking [-1, 1]
│   ├── features/
│   │   ├── normalizer.py              # Rolling z-scores & cross-sectional ranks
│   │   └── pipeline.py                # Polars feature pipeline engine
│   ├── validation/
│   │   ├── purged_walk_forward.py     # Purged & embargoed walk-forward splitter
│   │   └── metrics.py                 # Spearman rank IC, ICIR & acceptance gates
│   ├── models/
│   │   ├── base.py                    # Base ranker interface
│   │   ├── elastic_net.py             # ElasticNet linear baseline model
│   │   ├── lightgbm_ranker.py         # Regularized LightGBM ranker
│   │   ├── gating.py                  # Complexity Gating benchmark engine
│   │   └── ablation.py                # Systematic feature ablation study
│   ├── execution/
│   │   ├── portfolio.py               # Decile selection & inverse-ATR weighting
│   │   ├── blackouts.py               # Earnings blackout risk filters
│   │   ├── rebalance.py               # Weekly rebalancing with inertia bands
│   │   └── friction.py                # Slippage & short borrow drag calculation
│   ├── backtest/
│   │   ├── engine.py                  # Walk-forward portfolio simulation engine
│   │   └── reporting.py               # Tear-sheet performance metrics
│   └── cli.py                         # CLI entry points
└── tests/                             # Comprehensive unit & integration tests
    ├── test_targets.py
    ├── test_features.py
    ├── test_validation.py
    ├── test_models.py
    ├── test_execution.py
    └── test_end_to_end.py
```

---

## 7. Running Tests

```bash
pytest -v
```
