# StockModel: Quantitative Swing Behavior Model (2–4 Week Horizon)

A systematic quantitative trading and alpha research system designed to predict relative multi-week equity performance using cross-sectional gradient-boosted decision trees (LightGBM) with an ElasticNet linear baseline and strict temporal leakage prevention.

> 📖 **Comprehensive User Guide & Operator Manual:** See [USER_GUIDE.md](file:///home/shawn/git/StockModel/USER_GUIDE.md) for step-by-step instructions on daily portfolio workflows, web UI features, live Moomoo OpenD ingestion, REST API reference, and deployment procedures.

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

### 5. Ingest Live Market Data from Moomoo OpenD
Connects to the Moomoo OpenD gateway on `stockserver` (`192.168.1.20:11111`) to ingest daily bars (OHLCV + VWAP), market capitalization, ATM options chains (Net GEX and Put/Call volume), bimonthly short interest, and official earnings calendars into point-in-time Parquet panels:
```bash
# Ingest 252 days across default 50 liquid stocks
stockmodel fetch-moomoo --host 192.168.1.20 --days 252 --output data/moomoo_panel.parquet

# Custom universe
stockmodel fetch-moomoo --host 192.168.1.20 --days 120 --tickers "AAPL,NVDA,MSFT,AMZN,GOOGL"
```

### 6. Live Decile Ranking & Position Sizing
Generates current top/bottom decile long and short allocations with inverse-ATR weighting (using synthetic data or live Moomoo panels):
```bash
# Using live Moomoo market data
stockmodel rank --data data/moomoo_panel.parquet

# Using synthetic simulation
stockmodel rank --days 252
```

### 7. Launch Web Dashboard & API Server
Starts the FastAPI interactive quantitative research dashboard:
```bash
stockmodel serve --host 0.0.0.0 --port 8000
```

---

## 6. Web Dashboard UI

The interactive dashboard is available at `http://<host>:8000/`:
- **Dual Data Feeds:** Instant toggle between Synthetic Simulation and Live Moomoo OpenD feed (`stockserver:11111`).
- **Live Moomoo Gateway Modal:** Real-time OpenD gateway telemetry, cached panel metrics, and 1-click on-demand ingestion.
- **Live Allocations:** Cross-sectional decile long/short allocations with inverse-ATR risk weighting and earnings blackout alerts.
- **Simulation Tearsheet:** Interactive cumulative NAV equity curve and drawdown profile with full risk metrics (Sharpe, Sortino, Calmar, Turnover, Friction).
- **Complexity Gating:** Real-time empirical gatekeeper validating GBDT vs Linear baseline out-of-sample IC across walk-forward splits.
- **Feature Ablation:** Marginal predictive contribution analysis across the 7 core features with automated `KEEP` / `PRUNE` recommendations.
- **System Telemetry:** Live node resource utilization (CPU, memory, platform, uptime).

---

## 7. Project Architecture

```
StockModel/
├── deploy.sh                          # Automated production deployment script
├── pyproject.toml                     # Package specification & entry points
├── requirements.txt                   # Production dependencies
├── README.md                          # Documentation & usage guide
├── data/                              # Parquet market panels (e.g. moomoo_panel.parquet)
├── stockmodel/
│   ├── config.py                      # Hyperparameters & execution settings
│   ├── cli.py                         # CLI entry points (check-gate, run-backtest, rank, fetch-moomoo, serve)
│   ├── web/                           # Professional Web UI & FastAPI service
│   │   ├── app.py                     # API backend & JSON endpoints
│   │   └── static/                    # Responsive SPA dashboard (HTML/CSS/JS)
│   │       ├── index.html             # Single-page dashboard markup
│   │       ├── style.css              # Custom dark-theme glassmorphism CSS
│   │       └── app.js                 # Chart.js analytics & state manager
│   ├── data/                          # Data ingestion & schema definitions
│   │   ├── schema.py                  # Standardized Point-in-Time market schema
│   │   ├── loader.py                  # CSV/Parquet dataset loader
│   │   ├── synthetic.py               # Synthetic market generator (GBM + Jump-diffusion)
│   │   └── moomoo_loader.py           # Moomoo OpenD live market data ingestion engine
│   ├── targets/                       # Volatility-adjusted target ranking [-1, 1]
│   ├── features/                      # Polars 7-feature pipeline engine
│   ├── validation/                    # Purged & embargoed walk-forward splitter & IC metrics
│   ├── models/                        # LightGBM ranker, ElasticNet baseline, gating & ablation
│   ├── execution/                     # Portfolio allocation, blackouts, rebalance & friction
│   └── backtest/                      # Simulation engine & performance tear-sheets
└── tests/                             # Comprehensive test suite (27 unit & integration tests)
    ├── test_moomoo.py                 # Moomoo OpenD gateway & schema compliance tests
    ├── test_web.py                    # Web UI endpoints & live data source tests
    ├── test_targets.py
    ├── test_features.py
    ├── test_validation.py
    ├── test_models.py
    ├── test_execution.py
    ├── test_end_to_end.py
    └── test_web.py
```

---

## 8. Running Tests

```bash
pytest -v
```

---

## 9. Automated Remote Deployment

Use the built-in deployment script to deploy the codebase and start the systemd service on `modelserver`:

```bash
# Deploy to default host (modelserver)
./deploy.sh

# Deploy to custom host / user / port
./deploy.sh --host 192.168.1.36 --user shawn --port 8000

# Fast deployment without re-running tests
./deploy.sh --skip-tests
```

