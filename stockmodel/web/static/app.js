/**
 * StockModel Quantitative Alpha Dashboard Client Application
 */

const API_BASE = window.location.origin;

class StockModelApp {
    constructor() {
        this.currentAllocations = [];
        this.currentBacktest = null;
        this.charts = {};
        this.activeFilter = 'ALL';
        this.initEventListeners();
    }

    initEventListeners() {
        // Tab switching
        document.querySelectorAll('.nav-tab').forEach(tab => {
            tab.addEventListener('click', (e) => {
                const targetId = tab.getAttribute('data-target');
                this.switchTab(targetId);
            });
        });

        // Global parameter changes
        const daysSelect = document.getElementById('global-days-select');
        const seedInput = document.getElementById('global-seed-input');
        
        if (daysSelect) {
            daysSelect.addEventListener('change', () => this.refreshAll());
        }
        if (seedInput) {
            seedInput.addEventListener('change', () => this.refreshAll());
        }
    }

    switchTab(panelId) {
        document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));

        const targetTab = document.querySelector(`.nav-tab[data-target="${panelId}"]`);
        const targetPanel = document.getElementById(panelId);

        if (targetTab) targetTab.classList.add('active');
        if (targetPanel) targetPanel.classList.add('active');

        // Lazy load tab data if not loaded yet
        if (panelId === 'panel-backtest' && !this.currentBacktest) {
            this.loadBacktest();
        } else if (panelId === 'panel-gating' && !this.gatingLoaded) {
            this.loadGating();
        } else if (panelId === 'panel-ablation' && !this.ablationLoaded) {
            this.loadAblation();
        } else if (panelId === 'panel-telemetry') {
            this.loadTelemetry();
        }
    }

    showToast(message, duration = 3000) {
        const toast = document.getElementById('toast');
        if (!toast) return;
        toast.textContent = message;
        toast.classList.remove('hidden');
        setTimeout(() => toast.classList.add('hidden'), duration);
    }

    getParams() {
        const days = parseInt(document.getElementById('global-days-select')?.value || 252);
        const seed = parseInt(document.getElementById('global-seed-input')?.value || 42);
        const source = document.getElementById('global-source-select')?.value || 'synthetic';
        return { days, seed, source };
    }

    onSourceChange() {
        const { source } = this.getParams();
        this.showToast(`Switched active data feed to: ${source === 'moomoo' ? 'Moomoo OpenD (stockserver)' : 'Synthetic Generator'}`);
        this.refreshAll();
    }

    async init() {
        try {
            await this.loadTelemetry();
            await this.checkMoomooStatus();
            await this.loadRank();
        } catch (err) {
            console.error('Initialization error:', err);
            this.showToast('Error connecting to StockModel backend: ' + err.message);
        }
    }

    async checkMoomooStatus() {
        try {
            const res = await fetch(`${API_BASE}/api/moomoo/status`);
            if (!res.ok) return;
            const data = await res.json();
            const ind = document.getElementById('moomoo-indicator');
            const txt = document.getElementById('moomoo-status-text');

            if (data.connected) {
                if (ind) ind.className = 'status-indicator online';
                if (txt) {
                    if (data.panel?.cached) {
                        txt.textContent = `Online (${data.panel.symbols} assets, ${data.panel.rows} bars)`;
                    } else {
                        txt.textContent = 'Online (Ready to sync)';
                    }
                }
            } else {
                if (ind) ind.className = 'status-indicator offline';
                if (txt) txt.textContent = 'Disconnected';
            }

            // Update modal stats if open
            const mStatus = document.getElementById('modal-moomoo-status');
            const mRecords = document.getElementById('modal-panel-records');
            const mDates = document.getElementById('modal-panel-dates');
            const mMtime = document.getElementById('modal-panel-mtime');

            if (mStatus) mStatus.textContent = data.connected ? 'Online (Connected)' : 'Offline (Check stockserver)';
            if (mRecords) mRecords.textContent = data.panel?.cached ? `${data.panel.rows.toLocaleString()} bars across ${data.panel.symbols} assets` : 'No panel saved yet';
            if (mDates) mDates.textContent = data.panel?.cached && data.panel.start_date ? `${data.panel.start_date} -> ${data.panel.end_date}` : '--';
            if (mMtime) mMtime.textContent = data.panel?.cached && data.panel.last_modified ? data.panel.last_modified : 'Never';
        } catch (e) {
            console.debug('Moomoo status check failed:', e);
        }
    }

    showMoomooModal() {
        const modal = document.getElementById('modal-moomoo');
        if (modal) modal.classList.remove('hidden');
        this.checkMoomooStatus();
    }

    hideMoomooModal() {
        const modal = document.getElementById('modal-moomoo');
        if (modal) modal.classList.add('hidden');
    }

    async syncMoomooFromModal() {
        const btn = document.getElementById('btn-modal-sync');
        const btnText = document.getElementById('modal-sync-btn-text');
        const days = parseInt(document.getElementById('sync-days-input')?.value || 252);
        const tickers = document.getElementById('sync-tickers-input')?.value.trim();

        if (btn) btn.classList.add('loading');
        if (btnText) btnText.textContent = 'Ingesting from OpenD...';
        this.showToast('Fetching live market bars, GEX, and short interest from Moomoo stockserver...');

        try {
            let url = `${API_BASE}/api/moomoo/sync?days=${days}`;
            if (tickers) url += `&symbols=${encodeURIComponent(tickers)}`;
            const res = await fetch(url, { method: 'POST' });
            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.detail || `Sync failed (${res.status})`);
            }
            const data = await res.json();
            this.showToast(data.message || 'Moomoo sync completed successfully!');
            await this.checkMoomooStatus();
            this.hideMoomooModal();
            // Automatically switch to moomoo feed and refresh
            const srcSelect = document.getElementById('global-source-select');
            if (srcSelect) srcSelect.value = 'moomoo';
            await this.refreshAll();
        } catch (err) {
            console.error('Moomoo sync error:', err);
            this.showToast('Error syncing Moomoo data: ' + err.message, 5000);
        } finally {
            if (btn) btn.classList.remove('loading');
            if (btnText) btnText.textContent = 'Sync Live Market Data';
        }
    }

    async refreshAll() {
        const btn = document.getElementById('btn-run-all');
        if (btn) btn.classList.add('loading');
        this.showToast('Executing quantitative engine pipeline...');

        try {
            await this.loadRank();
            if (document.getElementById('panel-backtest').classList.contains('active')) {
                await this.loadBacktest();
            } else {
                this.currentBacktest = null;
            }
            if (document.getElementById('panel-gating').classList.contains('active')) {
                await this.loadGating();
            } else {
                this.gatingLoaded = false;
            }
            if (document.getElementById('panel-ablation').classList.contains('active')) {
                await this.loadAblation();
            } else {
                this.ablationLoaded = false;
            }
            this.showToast('Pipeline execution complete!');
        } catch (err) {
            console.error('Execution error:', err);
            this.showToast('Error executing engine: ' + err.message);
        } finally {
            if (btn) btn.classList.remove('loading');
        }
    }

    // =========================================================================
    // 1. Live Allocations Tab
    // =========================================================================

    async loadRank() {
        const { days, seed, source } = this.getParams();
        const tbody = document.getElementById('table-allocations-body');
        if (tbody) tbody.innerHTML = '<tr><td colspan="9" class="loading-cell">Computing LightGBM decile rankings & volatility weights...</td></tr>';

        const res = await fetch(`${API_BASE}/api/rank?days=${days}&seed=${seed}&source=${source}&allow_short=true`);
        if (!res.ok) throw new Error(`Rank API failed (${res.status})`);
        const data = await res.json();

        this.currentAllocations = data.allocations || [];

        // Update header & metric cards
        document.getElementById('rank-as-of').textContent = `As of: ${data.as_of_date} (${source === 'moomoo' ? 'Live Moomoo' : 'Synthetic'})`;
        document.getElementById('metric-gross-exposure').textContent = `${data.summary.gross_exposure_pct}%`;
        document.getElementById('metric-net-exposure').textContent = `${data.summary.net_exposure_pct > 0 ? '+' : ''}${data.summary.net_exposure_pct}%`;
        document.getElementById('metric-long-count').textContent = `${data.summary.long_positions} Longs`;
        document.getElementById('metric-long-weight').textContent = `(${data.summary.total_long_weight_pct}%)`;
        document.getElementById('metric-short-count').textContent = `${data.summary.short_positions} Shorts`;
        document.getElementById('metric-short-weight').textContent = `(-${data.summary.total_short_weight_pct}%)`;

        this.renderAllocationsChart(this.currentAllocations.filter(a => Math.abs(a.weight) > 0.001));
        this.renderAllocationsTable(this.currentAllocations);
    }

    renderAllocationsChart(activePositions) {
        const ctx = document.getElementById('chart-allocations');
        if (!ctx) return;

        if (this.charts.allocations) {
            this.charts.allocations.destroy();
        }

        const sorted = [...activePositions].sort((a, b) => b.weight - a.weight);
        const labels = sorted.map(p => p.symbol);
        const values = sorted.map(p => p.weight_pct);
        const colors = sorted.map(p => p.weight > 0 ? 'rgba(16, 185, 129, 0.8)' : 'rgba(244, 63, 94, 0.8)');
        const borderColors = sorted.map(p => p.weight > 0 ? '#10b981' : '#f43f5e');

        this.charts.allocations = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Portfolio Weight (%)',
                    data: values,
                    backgroundColor: colors,
                    borderColor: borderColors,
                    borderWidth: 1.5,
                    borderRadius: 4,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (context) => {
                                const idx = context.dataIndex;
                                const pos = sorted[idx];
                                const lines = [
                                    ` Weight: ${pos.weight_pct}% (${pos.type})`,
                                    ` Model Score: ${pos.pred_score}`,
                                    ` ATR(14): $${pos.atr_14}`,
                                    ` Days to Earnings: ${pos.days_to_earnings}d`
                                ];
                                if (pos.is_post_earnings && pos.last_earnings_date) {
                                    lines.push(` Earnings: Passed on ${pos.last_earnings_date}`);
                                } else if (pos.next_earnings_date) {
                                    lines.push(` Earnings: Reports ${pos.next_earnings_date}`);
                                }
                                return lines;
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { color: '#94a3b8', font: { family: 'JetBrains Mono', size: 11 } }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#f8fafc', font: { family: 'JetBrains Mono', weight: 600 } }
                    }
                }
            }
        });
    }

    filterAllocations(type) {
        this.activeFilter = type;
        document.querySelectorAll('.table-filters .filter-btn').forEach(b => {
            b.classList.toggle('active', b.getAttribute('data-filter') === type);
        });

        let filtered = this.currentAllocations;
        if (type === 'LONG') {
            filtered = this.currentAllocations.filter(a => a.type === 'LONG');
        } else if (type === 'SHORT') {
            filtered = this.currentAllocations.filter(a => a.type === 'SHORT');
        }
        this.renderAllocationsTable(filtered);
    }

    renderAllocationsTable(allocations) {
        const tbody = document.getElementById('table-allocations-body');
        if (!tbody) return;

        if (allocations.length === 0) {
            tbody.innerHTML = '<tr><td colspan="9" class="loading-cell">No positions found matching filter.</td></tr>';
            return;
        }

        tbody.innerHTML = allocations.map(a => {
            const weightClass = a.type === 'LONG' ? 'long' : (a.type === 'SHORT' ? 'short' : 'flat');
            
            let statusTag = '';
            if (a.in_blackout) {
                statusTag = `<span class="badge-tag blackout">⚠️ Blackout (${a.days_to_earnings}d)</span>`;
            } else if (a.is_post_earnings) {
                const daysAgo = (a.days_since_earnings !== null && a.days_since_earnings !== undefined && a.days_since_earnings >= 0) ? `${a.days_since_earnings}d ago` : 'Passed';
                statusTag = `<span class="badge-tag post-earnings" title="Passed ${a.last_earnings_date}">🎉 Post-Earnings (${daysAgo})</span>`;
            } else {
                statusTag = '<span class="badge-tag active">Active</span>';
            }

            let dteHtml = '';
            if (a.is_post_earnings && a.last_earnings_date) {
                dteHtml = `
                    <div class="dte-cell">
                        <span class="dte-main">~${a.days_to_earnings}d to next</span>
                        <span class="dte-sub passed">Passed ${a.last_earnings_date}</span>
                    </div>
                `;
            } else if (a.in_blackout) {
                dteHtml = `
                    <div class="dte-cell">
                        <span class="dte-main danger">${a.days_to_earnings}d</span>
                        <span class="dte-sub danger">Reports ${a.next_earnings_date || 'Imminent'}</span>
                    </div>
                `;
            } else if (a.next_earnings_date) {
                dteHtml = `
                    <div class="dte-cell">
                        <span class="dte-main">${a.days_to_earnings}d</span>
                        <span class="dte-sub">Reports ${a.next_earnings_date}</span>
                    </div>
                `;
            } else {
                dteHtml = `<div class="dte-cell"><span class="dte-main">${a.days_to_earnings} days</span></div>`;
            }

            return `
                <tr>
                    <td class="ticker-cell">${a.symbol}</td>
                    <td><span class="weight-pill ${weightClass}">${a.type}</span></td>
                    <td style="font-family: var(--font-mono); font-weight: 600;">${a.weight_pct > 0 ? '+' : ''}${a.weight_pct}%</td>
                    <td style="font-family: var(--font-mono);">${a.pred_score}</td>
                    <td style="font-family: var(--font-mono);">$${a.close.toFixed(2)}</td>
                    <td style="font-family: var(--font-mono);">$${a.atr_14.toFixed(2)}</td>
                    <td>${dteHtml}</td>
                    <td>${statusTag}</td>
                    <td>${a.sector}</td>
                </tr>
            `;
        }).join('');
    }

    exportAllocationsCSV() {
        if (!this.currentAllocations.length) return;
        const headers = ['Symbol', 'Type', 'Weight_Pct', 'Pred_Score', 'Last_Close', 'ATR_14', 'Days_To_Earnings', 'Days_Since_Earnings', 'Last_Earnings_Date', 'Next_Earnings_Date', 'Is_Post_Earnings', 'In_Blackout', 'Sector'];
        const rows = this.currentAllocations.map(a => [
            a.symbol, a.type, a.weight_pct, a.pred_score, a.close, a.atr_14, a.days_to_earnings, a.days_since_earnings ?? '', a.last_earnings_date ?? '', a.next_earnings_date ?? '', a.is_post_earnings ?? false, a.in_blackout, a.sector
        ]);
        const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
        const encodedUri = encodeURI(csvContent);
        const link = document.createElement('a');
        link.setAttribute('href', encodedUri);
        link.setAttribute('download', `stockmodel_allocations_${new Date().toISOString().slice(0, 10)}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    // =========================================================================
    // 2. Backtest Simulation Tab
    // =========================================================================

    async loadBacktest() {
        const { days, seed, source } = this.getParams();
        this.showToast('Simulating walk-forward backtest with friction...');

        const res = await fetch(`${API_BASE}/api/backtest?days=${days}&seed=${seed}&source=${source}`);
        if (!res.ok) throw new Error(`Backtest API failed (${res.status})`);
        const data = await res.json();

        this.currentBacktest = data;
        const m = data.metrics;

        document.getElementById('bt-ann-return').textContent = `${m.annualized_return_pct}%`;
        document.getElementById('bt-total-return').textContent = `Total: ${m.total_return_pct}%`;
        document.getElementById('bt-sharpe').textContent = `${m.sharpe_ratio}`;
        document.getElementById('bt-sortino').textContent = `${m.sortino_ratio}`;
        document.getElementById('bt-max-dd').textContent = `-${m.max_drawdown_pct}%`;
        document.getElementById('bt-calmar').textContent = `Calmar: ${m.calmar_ratio}`;
        document.getElementById('bt-turnover').textContent = `${m.annualized_turnover}x`;
        document.getElementById('bt-friction').textContent = `Drag: ${m.total_friction_bps} bps`;
        document.getElementById('bt-alpha').textContent = `+${m.alpha_pct}%`;
        document.getElementById('bt-benchmark').textContent = `Bmk: ${m.benchmark_return_pct}%`;

        this.renderEquityCharts(data.daily_curve);
    }

    renderEquityCharts(curve) {
        const dates = curve.map(c => c.date.split('T')[0]);
        const strategyNav = curve.map(c => c.nav);
        const benchmarkNav = curve.map(c => c.benchmark_nav);
        const drawdowns = curve.map(c => -Math.abs(c.drawdown_pct));

        // 1. NAV Equity Curve
        const ctxNav = document.getElementById('chart-equity');
        if (ctxNav) {
            if (this.charts.equity) this.charts.equity.destroy();

            this.charts.equity = new Chart(ctxNav, {
                type: 'line',
                data: {
                    labels: dates,
                    datasets: [
                        {
                            label: 'Strategy NAV',
                            data: strategyNav,
                            borderColor: '#10b981',
                            backgroundColor: 'rgba(16, 185, 129, 0.08)',
                            borderWidth: 2.2,
                            fill: true,
                            tension: 0.1,
                            pointRadius: 0,
                            pointHoverRadius: 5,
                        },
                        {
                            label: 'Benchmark',
                            data: benchmarkNav,
                            borderColor: '#64748b',
                            borderWidth: 1.5,
                            borderDash: [4, 4],
                            fill: false,
                            pointRadius: 0,
                            pointHoverRadius: 4,
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: 'index', intersect: false },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (c) => ` ${c.dataset.label}: $${c.raw.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                            }
                        }
                    },
                    scales: {
                        y: {
                            grid: { color: 'rgba(255, 255, 255, 0.05)' },
                            ticks: {
                                color: '#94a3b8',
                                callback: (v) => '$' + (v / 1000).toFixed(0) + 'k',
                                font: { family: 'JetBrains Mono' }
                            }
                        },
                        x: {
                            grid: { display: false },
                            ticks: { color: '#64748b', maxTicksLimit: 12, font: { family: 'JetBrains Mono', size: 10 } }
                        }
                    }
                }
            });
        }

        // 2. Drawdown Curve
        const ctxDd = document.getElementById('chart-drawdown');
        if (ctxDd) {
            if (this.charts.drawdown) this.charts.drawdown.destroy();

            this.charts.drawdown = new Chart(ctxDd, {
                type: 'line',
                data: {
                    labels: dates,
                    datasets: [{
                        label: 'Drawdown (%)',
                        data: drawdowns,
                        borderColor: '#f43f5e',
                        backgroundColor: 'rgba(244, 63, 94, 0.15)',
                        borderWidth: 1.5,
                        fill: true,
                        tension: 0.1,
                        pointRadius: 0,
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (c) => ` Drawdown: ${c.raw.toFixed(2)}%`
                            }
                        }
                    },
                    scales: {
                        y: {
                            grid: { color: 'rgba(255, 255, 255, 0.05)' },
                            ticks: { color: '#94a3b8', font: { family: 'JetBrains Mono' }, callback: v => v + '%' }
                        },
                        x: {
                            grid: { display: false },
                            ticks: { color: '#64748b', maxTicksLimit: 12, font: { family: 'JetBrains Mono', size: 10 } }
                        }
                    }
                }
            });
        }
    }

    exportBacktestCSV() {
        if (!this.currentBacktest?.daily_curve?.length) return;
        const headers = ['Date', 'Strategy_NAV', 'Benchmark_NAV', 'Net_Return', 'Benchmark_Return', 'Drawdown_Pct', 'Turnover', 'Friction_Drag_Bps'];
        const rows = this.currentBacktest.daily_curve.map(r => [
            r.date, r.nav, r.benchmark_nav, r.net_return, r.benchmark_return, r.drawdown_pct, r.turnover, r.friction_drag
        ]);
        const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
        const encodedUri = encodeURI(csvContent);
        const link = document.createElement('a');
        link.setAttribute('href', encodedUri);
        link.setAttribute('download', `stockmodel_backtest_curve_${new Date().toISOString().slice(0, 10)}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    // =========================================================================
    // 3. Complexity Gating Tab
    // =========================================================================

    async loadGating() {
        const { days, seed, source } = this.getParams();
        const tbody = document.getElementById('table-folds-body');
        if (tbody) tbody.innerHTML = '<tr><td colspan="7" class="loading-cell">Evaluating LightGBM vs ElasticNet across purged walk-forward folds...</td></tr>';

        const res = await fetch(`${API_BASE}/api/check-gate?days=${days}&seed=${seed}&source=${source}`);
        if (!res.ok) throw new Error(`Gating API failed (${res.status})`);
        const data = await res.json();
        this.gatingLoaded = true;

        const s = data.summary;
        const badge = document.getElementById('gating-verdict-badge');
        if (badge) {
            badge.className = `verdict-badge ${data.passed ? 'passed' : 'failed'}`;
            badge.textContent = data.passed ? 'GATE PASSED - APPROVED' : 'GATE FAILED - REVIEW REQUIRED';
        }

        // Hurdle Cards
        const cardIc = document.getElementById('hurdle-ic-card');
        const cardIcir = document.getElementById('hurdle-icir-card');
        const cardBase = document.getElementById('hurdle-baseline-card');

        if (cardIc) cardIc.className = `hurdle-card ${s.pass_ic ? 'passed' : 'failed'}`;
        if (cardIcir) cardIcir.className = `hurdle-card ${s.pass_icir ? 'passed' : 'failed'}`;
        if (cardBase) cardBase.className = `hurdle-card ${s.pass_baseline ? 'passed' : 'failed'}`;

        document.getElementById('hurdle-ic-icon').textContent = s.pass_ic ? '✅' : '❌';
        document.getElementById('hurdle-icir-icon').textContent = s.pass_icir ? '✅' : '❌';
        document.getElementById('hurdle-baseline-icon').textContent = s.pass_baseline ? '✅' : '❌';

        document.getElementById('gating-lgb-ic').textContent = `${s.gbdt_mean_ic}`;
        document.getElementById('gating-lgb-icir').textContent = `${s.gbdt_icir}`;
        document.getElementById('gating-ic-delta').textContent = `${s.ic_delta > 0 ? '+' : ''}${s.ic_delta}`;
        document.getElementById('gating-enet-ic').textContent = `ElasticNet Baseline: ${s.elastic_mean_ic}`;

        // Multi-bar Chart
        this.renderGatingChart(data.folds);

        // Folds Table
        if (tbody) {
            tbody.innerHTML = data.folds.map(f => `
                <tr>
                    <td style="font-family: var(--font-mono); font-weight: 600;">Fold ${f.fold_idx}</td>
                    <td style="font-family: var(--font-mono);">${f.train_start.split('T')[0]} &rarr; ${f.train_end.split('T')[0]}</td>
                    <td style="font-family: var(--font-mono);">${f.test_start.split('T')[0]} &rarr; ${f.test_end.split('T')[0]}</td>
                    <td style="font-family: var(--font-mono); color: var(--emerald-500); font-weight: 600;">${f.gbdt_ic}</td>
                    <td style="font-family: var(--font-mono);">${f.elastic_ic}</td>
                    <td style="font-family: var(--font-mono); font-weight: 600; color: ${f.gbdt_ic >= f.elastic_ic ? 'var(--emerald-500)' : 'var(--rose-500)'};">${(f.gbdt_ic - f.elastic_ic).toFixed(4)}</td>
                    <td><span class="badge-tag ${f.gbdt_outperformed ? 'keep' : 'prune'}">${f.gbdt_outperformed ? 'GBDT Outperformed' : 'Linear Ahead'}</span></td>
                </tr>
            `).join('');
        }
    }

    renderGatingChart(folds) {
        const ctx = document.getElementById('chart-gating-folds');
        if (!ctx) return;
        if (this.charts.gating) this.charts.gating.destroy();

        this.charts.gating = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: folds.map(f => `Fold ${f.fold_idx}`),
                datasets: [
                    {
                        label: 'LightGBM Ranker IC',
                        data: folds.map(f => f.gbdt_ic),
                        backgroundColor: 'rgba(16, 185, 129, 0.85)',
                        borderColor: '#10b981',
                        borderWidth: 1.5,
                        borderRadius: 4,
                    },
                    {
                        label: 'ElasticNet Baseline IC',
                        data: folds.map(f => f.elastic_ic),
                        backgroundColor: 'rgba(99, 102, 241, 0.85)',
                        borderColor: '#6366f1',
                        borderWidth: 1.5,
                        borderRadius: 4,
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: '#f8fafc', font: { family: 'Inter' } } }
                },
                scales: {
                    y: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { color: '#94a3b8', font: { family: 'JetBrains Mono' } }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: '#f8fafc', font: { family: 'JetBrains Mono', weight: 600 } }
                    }
                }
            }
        });
    }

    // =========================================================================
    // 4. Feature Ablation Tab
    // =========================================================================

    async loadAblation() {
        const { days, seed, source } = this.getParams();
        const tbody = document.getElementById('table-ablation-body');
        if (tbody) tbody.innerHTML = '<tr><td colspan="6" class="loading-cell">Running systematic leave-one-feature-out IC delta analysis...</td></tr>';

        const res = await fetch(`${API_BASE}/api/ablation?days=${Math.min(days, 300)}&seed=${seed}&source=${source}`);
        if (!res.ok) throw new Error(`Ablation API failed (${res.status})`);
        const data = await res.json();
        this.ablationLoaded = true;

        const features = data.features || [];

        // Render Horizontal Delta Tornado Chart
        const ctx = document.getElementById('chart-ablation');
        if (ctx) {
            if (this.charts.ablation) this.charts.ablation.destroy();

            const labels = features.map(f => f.feature_name);
            const deltas = features.map(f => f.ic_delta);
            const colors = deltas.map(d => d >= 0 ? 'rgba(16, 185, 129, 0.85)' : 'rgba(244, 63, 94, 0.85)');

            this.charts.ablation = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Marginal IC Contribution (Delta)',
                        data: deltas,
                        backgroundColor: colors,
                        borderRadius: 4,
                    }]
                },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: {
                            grid: { color: 'rgba(255, 255, 255, 0.05)' },
                            ticks: { color: '#94a3b8', font: { family: 'JetBrains Mono' } }
                        },
                        y: {
                            grid: { display: false },
                            ticks: { color: '#f8fafc', font: { family: 'Inter', weight: 500 } }
                        }
                    }
                }
            });
        }

        // Table
        if (tbody) {
            tbody.innerHTML = features.map(f => `
                <tr>
                    <td style="font-weight: 600; color: #ffffff;">${f.feature_name}</td>
                    <td><span class="badge-tag active">${f.category}</span></td>
                    <td style="font-family: var(--font-mono);">${f.ic_with_feature}</td>
                    <td style="font-family: var(--font-mono);">${f.ic_without_feature}</td>
                    <td style="font-family: var(--font-mono); font-weight: 600; color: ${f.ic_delta >= 0 ? 'var(--emerald-500)' : 'var(--rose-500)'};">${f.ic_delta > 0 ? '+' : ''}${f.ic_delta}</td>
                    <td><span class="badge-tag ${f.action === 'KEEP' ? 'keep' : 'prune'}">${f.action}</span></td>
                </tr>
            `).join('');
        }
    }

    // =========================================================================
    // 5. System Specs & Telemetry Tab
    // =========================================================================

    async loadTelemetry() {
        const res = await fetch(`${API_BASE}/api/status`);
        if (!res.ok) return;
        const data = await res.json();

        const hostEl = document.getElementById('server-hostname');
        if (hostEl) hostEl.textContent = data.hostname;

        const specHost = document.getElementById('spec-host');
        if (specHost) specHost.textContent = data.hostname;

        const specOs = document.getElementById('spec-os');
        if (specOs) specOs.textContent = data.platform;

        const specPython = document.getElementById('spec-python');
        if (specPython) specPython.textContent = `Python ${data.python_version} (Native)`;

        const specCpu = document.getElementById('spec-cpu');
        if (specCpu) specCpu.textContent = `${data.cpu_count} Logical Cores`;

        const specMem = document.getElementById('spec-mem');
        if (specMem) specMem.textContent = `${data.memory_available} available / ${data.memory_total}`;

        const specUptime = document.getElementById('spec-uptime');
        if (specUptime) {
            const mins = Math.floor(data.uptime_seconds / 60);
            const hrs = Math.floor(mins / 60);
            specUptime.textContent = hrs > 0 ? `${hrs}h ${mins % 60}m` : `${mins}m ${data.uptime_seconds % 60}s`;
        }
    }
}

// Global instance
const app = new StockModelApp();
window.addEventListener('DOMContentLoaded', () => app.init());
