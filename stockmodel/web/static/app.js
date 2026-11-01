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
        this.currentStockSymbol = 'AMZN';
        this.singleStockLoaded = false;
        this.chartSingleStock = null;
        this.initTooltipSystem();
        this.initEventListeners();
    }

    initTooltipSystem() {
        let tooltipEl = document.getElementById('global-tooltip');
        if (!tooltipEl) {
            tooltipEl = document.createElement('div');
            tooltipEl.id = 'global-tooltip';
            tooltipEl.className = 'global-tooltip hidden';
            document.body.appendChild(tooltipEl);
        }

        let activeTrigger = null;
        let hideTimeout = null;

        const showTooltip = (triggerEl) => {
            clearTimeout(hideTimeout);
            activeTrigger = triggerEl;

            const title = triggerEl.getAttribute('data-tip-title') || 'Metric Explanation';
            const cat = triggerEl.getAttribute('data-tip-cat') || 'ANALYTICS';
            const what = triggerEl.getAttribute('data-tip-what') || '';
            const how = triggerEl.getAttribute('data-tip-how') || '';
            const rule = triggerEl.getAttribute('data-tip-rule') || '';

            tooltipEl.innerHTML = `
                <div class="tooltip-header">
                    <span class="tooltip-cat">${cat}</span>
                    <h4 class="tooltip-title">${title}</h4>
                </div>
                <div class="tooltip-body">
                    ${what ? `
                    <div class="tooltip-section">
                        <span class="tooltip-section-label">What it means</span>
                        <p class="tooltip-desc">${what}</p>
                    </div>` : ''}
                    ${how ? `
                    <div class="tooltip-section">
                        <span class="tooltip-section-label">Calculation / Formula</span>
                        <p class="tooltip-desc mono">${how}</p>
                    </div>` : ''}
                    ${rule ? `
                    <div class="tooltip-section tooltip-rule-box">
                        <span class="tooltip-section-label">💡 Quantitative Rule / Decision Threshold</span>
                        <p class="tooltip-rule-text">${rule}</p>
                    </div>` : ''}
                </div>
            `;

            tooltipEl.classList.remove('hidden');

            // Position tooltip dynamically relative to trigger element
            const rect = triggerEl.getBoundingClientRect();
            const tipRect = tooltipEl.getBoundingClientRect();

            let top = rect.top - tipRect.height - 12;
            let left = rect.left + (rect.width / 2) - (tipRect.width / 2);

            // If not enough room above viewport, flip below trigger
            if (top < 15) {
                top = rect.bottom + 12;
                tooltipEl.setAttribute('data-placement', 'bottom');
            } else {
                tooltipEl.setAttribute('data-placement', 'top');
            }

            // Clamping inside horizontal viewport bounds
            if (left < 14) left = 14;
            if (left + tipRect.width > window.innerWidth - 14) {
                left = window.innerWidth - tipRect.width - 14;
            }

            tooltipEl.style.top = `${Math.round(top + window.scrollY)}px`;
            tooltipEl.style.left = `${Math.round(left + window.scrollX)}px`;
            tooltipEl.classList.add('visible');
        };

        const hideTooltip = () => {
            hideTimeout = setTimeout(() => {
                tooltipEl.classList.remove('visible');
                setTimeout(() => {
                    if (!tooltipEl.classList.contains('visible')) {
                        tooltipEl.classList.add('hidden');
                    }
                }, 180);
                activeTrigger = null;
            }, 120);
        };

        // Delegated events for hovering over badges, chips, or metric cards
        document.body.addEventListener('pointerenter', (e) => {
            const trigger = e.target.closest('.tip-badge, .has-tip, [data-tip-title]');
            if (trigger) showTooltip(trigger);
        }, true);

        document.body.addEventListener('pointerleave', (e) => {
            const trigger = e.target.closest('.tip-badge, .has-tip, [data-tip-title]');
            if (trigger) hideTooltip();
        }, true);

        // Click support (especially useful on mobile or touch screens)
        document.body.addEventListener('click', (e) => {
            const trigger = e.target.closest('.tip-badge, .has-tip, [data-tip-title]');
            if (trigger) {
                if (activeTrigger === trigger && tooltipEl.classList.contains('visible')) {
                    hideTooltip();
                } else {
                    showTooltip(trigger);
                }
            } else if (!e.target.closest('#global-tooltip')) {
                hideTooltip();
            }
        });

        window.addEventListener('scroll', () => {
            if (tooltipEl.classList.contains('visible')) {
                hideTooltip();
            }
        }, { passive: true });
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
        if (panelId === 'panel-single-stock' && !this.singleStockLoaded) {
            this.loadSingleStock(this.currentStockSymbol || 'AMZN');
        } else if (panelId === 'panel-rank' && (!this.currentAllocations || !this.currentAllocations.length)) {
            this.loadRank();
        } else if (panelId === 'panel-backtest' && !this.currentBacktest) {
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
            await this.loadSingleStock(this.currentStockSymbol || 'AMZN');
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
                    <td class="ticker-cell clickable-ticker" onclick="app.inspectStock('${a.symbol}')" title="Deep Research ${a.symbol}">${a.symbol}<span class="inspect-icon">🔍</span></td>
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

    // =========================================================================
    // 0. Single Stock Deep Research Tab
    // =========================================================================

    setQuickStock(symbol) {
        document.querySelectorAll('.chip-pill').forEach(btn => {
            btn.classList.toggle('active', btn.textContent.trim() === symbol);
        });
        const input = document.getElementById('single-stock-input');
        if (input) input.value = symbol;
        this.loadSingleStock(symbol);
    }

    analyzeCustomStock() {
        const input = document.getElementById('single-stock-input');
        const symbol = (input?.value || 'AMZN').trim().toUpperCase();
        if (!symbol) return;
        document.querySelectorAll('.chip-pill').forEach(btn => {
            btn.classList.toggle('active', btn.textContent.trim() === symbol);
        });
        this.loadSingleStock(symbol);
    }

    inspectStock(symbol) {
        this.switchTab('panel-single-stock');
        this.setQuickStock(symbol);
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    async loadSingleStock(symbol = 'AMZN') {
        this.currentStockSymbol = symbol;
        const dossierEl = document.getElementById('stock-dossier');
        const btnText = document.getElementById('analyze-btn-text');
        const btn = document.getElementById('btn-analyze-stock');
        if (btn) btn.classList.add('loading');
        if (btnText) btnText.textContent = `Analyzing ${symbol}...`;

        if (dossierEl) {
            dossierEl.innerHTML = `
                <div class="loading-state-card card">
                    <div class="spinner"></div>
                    <p>Generating Institutional Alpha Dossier for <strong>${symbol}</strong>...</p>
                </div>
            `;
        }

        try {
            const days = parseInt(document.getElementById('global-days-select')?.value || 252);
            const source = document.getElementById('global-source-select')?.value || 'moomoo';
            const res = await fetch(`${API_BASE}/api/stock/${encodeURIComponent(symbol)}?days=${days}&source=${source}`);
            
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `Stock research failed (${res.status})`);
            }
            const data = await res.json();
            this.singleStockLoaded = true;
            this.renderStockDossier(data);
        } catch (err) {
            console.error('Single stock error:', err);
            this.showToast(`Error analyzing ${symbol}: ${err.message}`);
            if (dossierEl) {
                dossierEl.innerHTML = `
                    <div class="error-card card">
                        <div class="error-icon" style="font-size: 2rem; margin-bottom: 8px;">⚠️</div>
                        <h3 style="color: var(--rose-500); margin-bottom: 6px;">Could not analyze ${symbol}</h3>
                        <p style="color: var(--text-secondary); margin-bottom: 8px;">${err.message}</p>
                        <span style="font-size: 0.75rem; color: var(--text-muted);">Verify ticker spelling or confirm Moomoo OpenD is connected to stockserver.</span>
                    </div>
                `;
            }
        } finally {
            if (btn) btn.classList.remove('loading');
            if (btnText) btnText.textContent = 'Analyze Stock';
        }
    }

    renderStockDossier(data) {
        const dossierEl = document.getElementById('stock-dossier');
        if (!dossierEl) return;

        const q = data.quote;
        const v = data.verdict;
        const e = data.earnings;
        const d = data.derivatives;

        // Update as-of badge
        const asOfEl = document.getElementById('stock-as-of');
        if (asOfEl) asOfEl.textContent = `As of: ${data.as_of_date} (${data.source.toUpperCase()})`;

        // Color coding for signals
        let signalClass = 'signal-neutral';
        if (v.signal.includes('LONG')) signalClass = 'signal-long';
        else if (v.signal.includes('SHORT')) signalClass = 'signal-short';
        else if (v.signal.includes('BLACKOUT')) signalClass = 'signal-blackout';

        const changeClass = q.change_1d >= 0 ? 'positive' : 'negative';
        const changeSign = q.change_1d >= 0 ? '+' : '';

        dossierEl.innerHTML = `
            <!-- Top Asset Profile & Big Signal Card -->
            <div class="dossier-header-card card">
                <div class="dossier-identity">
                    <div class="symbol-badge-row">
                        <h2 class="dossier-symbol">${data.symbol}</h2>
                        <span class="dossier-sector-pill">${data.sector}</span>
                        <span class="dossier-source-pill">${data.source === 'moomoo' ? '🟢 Moomoo OpenD' : '🟡 Simulation'}</span>
                        <span class="tip-badge" 
                            data-tip-title="Asset Identity & Market Feed" 
                            data-tip-cat="MARKET DATA FEED" 
                            data-tip-what="Identifies the company, GICS sector, and whether market metrics were ingested live via Moomoo OpenD from stockserver or generated through cross-sectional simulation." 
                            data-tip-rule="Live OpenD feed evaluates real-time market data across 50+ liquid US equities and on-demand ad-hoc tickers.">?</span>
                    </div>
                    <div class="dossier-price-row">
                        <span class="dossier-price">$${q.close.toFixed(2)}</span>
                        <span class="dossier-change ${changeClass}">${changeSign}$${q.change_1d.toFixed(2)} (${changeSign}${q.change_1d_pct.toFixed(2)}%)</span>
                    </div>
                    <div class="dossier-stats-chips">
                        <span class="stat-chip has-tip"
                            data-tip-title="Market Capitalization"
                            data-tip-cat="COMPANY SCALE"
                            data-tip-what="Total dollar market value of the company's outstanding equity shares ($P × Shares Outstanding)."
                            data-tip-rule="Mega-caps (>$200B) have deep liquidity and low execution slippage (~8 bps); mid-caps incur slightly wider spreads (~15 bps).">
                            <strong>Market Cap:</strong> ${q.market_cap_fmt} <span class="chip-q">?</span>
                        </span>
                        <span class="stat-chip has-tip"
                            data-tip-title="52-Week Price Range"
                            data-tip-cat="TECHNICAL EXTREMES"
                            data-tip-what="The lowest and highest daily closing prices recorded over the preceding 52 weeks (252 trading days)."
                            data-tip-rule="Stocks breaking out to fresh 52-week highs with positive momentum show strong institutional sponsorship; stocks near 52-week lows carry squeeze volatility.">
                            <strong>52W Range:</strong> $${q.low_52w.toFixed(2)} - $${q.high_52w.toFixed(2)} <span class="chip-q">?</span>
                        </span>
                        <span class="stat-chip has-tip"
                            data-tip-title="20-Day Rolling Institutional VWAP"
                            data-tip-cat="VOLUME BENCHMARK"
                            data-tip-what="Volume-Weighted Average Price across the last 20 trading days: ∑(Price × Volume) / ∑Volume."
                            data-tip-rule="Represents the average price paid by institutional investors over the past month. Spot price trading above 20d VWAP indicates buyers are in aggressive control.">
                            <strong>20d VWAP:</strong> $${q.vwap_20 ? q.vwap_20.toFixed(2) : '--'} <span class="chip-q">?</span>
                        </span>
                        <span class="stat-chip has-tip"
                            data-tip-title="50-Day Simple Moving Average"
                            data-tip-cat="INTERMEDIATE TREND"
                            data-tip-what="Average closing price over the past 50 trading days (~10 calendar weeks)."
                            data-tip-rule="Primary institutional benchmark for medium-term structural trend. When spot price & 20d VWAP are both above 50d SMA, the stock is in a confirmed structural uptrend.">
                            <strong>50d SMA:</strong> $${q.sma_50 ? q.sma_50.toFixed(2) : '--'} <span class="chip-q">?</span>
                        </span>
                    </div>
                </div>

                <div class="dossier-verdict-box ${signalClass}">
                    <div class="verdict-header-row" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                        <span class="verdict-pretitle">QUANTITATIVE MODEL SIGNAL</span>
                        <span class="tip-badge tip-badge-light"
                            data-tip-title="Quantitative Model Signal & Verdict"
                            data-tip-cat="GBDT ALPHA ENGINE"
                            data-tip-what="The consolidated trade verdict generated by our LightGBM gradient boosted decision tree (GBDT) model after cross-sectional ranking and earnings risk gating."
                            data-tip-rule="• TOP DECILE STRONG LONG: Top 10% expected return; high-conviction swing candidate.<br>• DEC 2 OVERPERFORM LONG: Top 20% candidate.<br>• NEUTRAL / HOLD: Deciles 3–8; average market performance.<br>• UNDERPERFORM SHORT: Deciles 9–10; underperforming relative to universe.<br>• EARNINGS BLACKOUT: Scheduled earnings in ≤ 3 days; entry forbidden to prevent binary gap risk.">?</span>
                    </div>
                    <h3 class="verdict-title">${v.signal_label}</h3>
                    <div class="verdict-meta">
                        <span class="verdict-score has-tip"
                            data-tip-title="Predicted Alpha Score"
                            data-tip-cat="LIGHTGBM FORECAST"
                            data-tip-what="Out-of-sample forecast of 10-20 trading day forward return relative to the universe median, trained on purged & embargoed walk-forward splits."
                            data-tip-how="Standardized normalized score between -1.0 and +1.0."
                            data-tip-rule="Scores > +0.02 indicate significant expected outperformance (Long candidate); scores < -0.02 indicate underperformance (Short candidate).">
                            Score: <strong>${v.pred_score > 0 ? '+' : ''}${v.pred_score}</strong> <span class="chip-q">?</span>
                        </span>
                        <span class="verdict-percentile has-tip"
                            data-tip-title="Cross-Sectional Percentile & Decile Rank"
                            data-tip-cat="UNIVERSE RANKING"
                            data-tip-what="Where this stock ranks compared to all other liquid equities in the universe. Decile 10 (90th–100th percentile) represents the top 10% highest expected returns."
                            data-tip-rule="Long positions are strictly selected from the top decile; short positions target the bottom decile.">
                            Rank: <strong>${v.percentile}th %ile (Decile ${v.decile})</strong> <span class="chip-q">?</span>
                        </span>
                    </div>
                    <div class="verdict-sizing">
                        <span class="has-tip"
                            data-tip-title="Inverse-ATR Risk Parity Sizing"
                            data-tip-cat="POSITION SIZING"
                            data-tip-what="Target portfolio weight scaled inversely by 14-day volatility: w_i ∝ 1 / ATR_14(i)."
                            data-tip-rule="Higher volatility stocks receive smaller position sizes so every asset contributes equal dollar risk to the portfolio, preventing volatile names from dominating portfolio P&L.">
                            Inverse-ATR Sizing: <strong>${v.suggested_weight_pct}%</strong> <span class="chip-q">?</span>
                        </span>
                        <span class="has-tip"
                            data-tip-title="14-Day Average True Range (ATR)"
                            data-tip-cat="VOLATILITY RISK"
                            data-tip-what="Average daily high-to-low trading range over the past 14 trading days, including overnight price gaps."
                            data-tip-how="Expressed in dollars ($${q.atr_14.toFixed(2)}) and percentage of share price (${q.atr_14_pct}%)."
                            data-tip-rule="Used to set dynamic volatility stop-losses (e.g. 2 × ATR) and calibrate position sizing.">
                            ATR(14): <strong>$${q.atr_14.toFixed(2)} (${q.atr_14_pct}%)</strong> <span class="chip-q">?</span>
                        </span>
                    </div>
                </div>
            </div>

            <!-- 4 Quick Telemetry Cards -->
            <div class="metric-grid-4">
                <div class="metric-card has-tip"
                    data-tip-title="Predicted 2-4W Alpha Score"
                    data-tip-cat="GBDT ALPHA ENGINE"
                    data-tip-what="The model's out-of-sample forecast for 10-20 trading days forward return relative to the cross-sectional universe median."
                    data-tip-how="Calculated using LightGBM trained on 7 orthogonal quantitative features with purged & embargoed cross-validation."
                    data-tip-rule="Decile 10 assets (top 10%) have historically delivered statistically significant positive Information Coefficients (IC ≥ 0.035).">
                    <div class="card-label-row">
                        <span class="card-label">Predicted 2-4W Alpha</span>
                        <span class="tip-badge">?</span>
                    </div>
                    <div class="card-value-group">
                        <span class="card-value ${v.pred_score >= 0 ? 'highlight-cyan' : 'highlight-rose'}">${v.pred_score > 0 ? '+' : ''}${v.pred_score}</span>
                    </div>
                    <span class="card-hint">${v.percentile}th percentile relative to peers</span>
                </div>

                <div class="metric-card has-tip"
                    data-tip-title="Earnings Lifecycle & Blackout Policy"
                    data-tip-cat="EVENT RISK POLICY"
                    data-tip-what="Point-in-time calculation of trading days until the next scheduled earnings report, or trading days elapsed since the prior announcement."
                    data-tip-how="Cross-referenced against corporate earnings calendars with rate-limited OpenD synchronization."
                    data-tip-rule="• ≤ 3 Trading Days: BLACKOUT WINDOW — New entry strictly forbidden to eliminate binary overnight gap risk.<br>• 1–10 Days Post-Earnings: PEAD WINDOW — Exploit Post-Earnings Announcement Drift if momentum is positive.<br>• > 10 Days: NORMAL TRADING — Standard swing holding period.">
                    <div class="card-label-row">
                        <span class="card-label">Earnings Lifecycle</span>
                        <span class="tip-badge">?</span>
                    </div>
                    <div class="card-value-group">
                        <span class="card-value ${e.in_blackout ? 'highlight-amber' : (e.is_post_earnings ? 'highlight-purple' : 'highlight-cyan')}">${e.days_to_earnings}d</span>
                    </div>
                    <span class="card-hint">${e.status_text}</span>
                </div>

                <div class="metric-card has-tip"
                    data-tip-title="Net Dealer Gamma Exposure (Net GEX)"
                    data-tip-cat="OPTIONS MICROSTRUCTURE"
                    data-tip-what="Dollar gamma sensitivity of near-the-money Call options minus near-the-money Put options held by market makers (ATM Call GEX - ATM Put GEX)."
                    data-tip-how="Dealers dynamically hedge options inventory by buying/selling the underlying shares."
                    data-tip-rule="• POSITIVE GEX (Call Gamma > Put Gamma): Market makers buy dips and sell rips, dampening volatility and supporting mean-reversion.<br>• NEGATIVE GEX (Put Gamma > Call Gamma): Market makers must sell when price drops and buy when price rallies, accelerating volatility and fueling momentum breakouts.">
                    <div class="card-label-row">
                        <span class="card-label">Net Gamma Exposure</span>
                        <span class="tip-badge">?</span>
                    </div>
                    <div class="card-value-group">
                        <span class="card-value ${d.net_gex >= 0 ? 'highlight-cyan' : 'highlight-rose'}">$${(d.net_gex / 1000).toFixed(0)}k</span>
                    </div>
                    <span class="card-hint">${d.gex_regime}</span>
                </div>

                <div class="metric-card has-tip"
                    data-tip-title="Short Squeeze Risk & Days to Cover"
                    data-tip-cat="MARKET STRUCTURE"
                    data-tip-what="Total shares held short divided by the 20-day Average Daily Volume (ADV20): Short Interest / ADV20."
                    data-tip-how="Represents the estimated number of full trading days required for short sellers to buy back all borrowed shares."
                    data-tip-rule="Days to cover > 4-5 days combined with positive price momentum creates high risk of an explosive short squeeze as bears are forced to cover.">
                    <div class="card-label-row">
                        <span class="card-label">Short Squeeze Risk</span>
                        <span class="tip-badge">?</span>
                    </div>
                    <div class="card-value-group">
                        <span class="card-value highlight-cyan">${d.days_to_cover}d</span>
                    </div>
                    <span class="card-hint">Short Int: ${(d.short_interest / 1e6).toFixed(1)}M shares</span>
                </div>
            </div>

            <!-- Chart & Technical Diagnostics Grid -->
            <div class="chart-grid-two">
                <div class="card chart-card">
                    <div class="chart-header">
                        <div>
                            <div class="title-with-tip" style="display: flex; align-items: center; gap: 8px;">
                                <h3 class="chart-title">Price Action & Institutional VWAP (90 Trading Days)</h3>
                                <span class="tip-badge"
                                    data-tip-title="Price Action, 20d VWAP & 50d SMA Chart"
                                    data-tip-cat="CHART DIAGNOSTICS"
                                    data-tip-what="Interactive 90-trading-day time-series displaying daily spot closing prices against two critical institutional benchmarks."
                                    data-tip-how="• Blue Line: Daily Close Price.<br>• Emerald Dashed Line: 20-Day Rolling Institutional VWAP.<br>• Purple Dashed Line: 50-Day Trend SMA."
                                    data-tip-rule="When price pulls back and bounces off the 20d VWAP or 50d SMA during an established uptrend, it indicates institutional re-accumulation and strong swing support.">?</span>
                            </div>
                            <p class="chart-subtitle">Close price with 20-day rolling institutional VWAP and 50-day trend SMA.</p>
                        </div>
                    </div>
                    <div class="chart-container" style="height: 320px;">
                        <canvas id="chart-single-stock"></canvas>
                    </div>
                </div>

                <div class="card diagnosis-card">
                    <div class="title-with-tip" style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                        <h3 class="chart-title" style="margin: 0;">Quantitative Diagnostic Rationale</h3>
                        <span class="tip-badge"
                            data-tip-title="Algorithmic Synthesis Rationale"
                            data-tip-cat="NARRATIVE SYNTHESIS"
                            data-tip-what="Multi-factor natural language diagnostic synthesized by the alpha engine, detailing the primary feature driver, volatility state, and event risk factors."
                            data-tip-rule="Explains exactly why this asset was placed in its decile rank and what primary driver is propelling its alpha forecast.">?</span>
                    </div>
                    <div class="narrative-content">
                        <p class="narrative-text">${v.summary_narrative}</p>
                    </div>

                    <div class="event-risk-block">
                        <div class="title-with-tip" style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                            <h4 class="event-risk-title" style="margin: 0;">Event & Earnings Risk Review</h4>
                            <span class="tip-badge"
                                data-tip-title="Event & Earnings Risk Policy"
                                data-tip-cat="RISK MANAGEMENT"
                                data-tip-what="Enforces strict risk policy regarding corporate earnings announcements to protect against binary overnight gap losses."
                                data-tip-rule="Positions are automatically flagged for liquidation or entry prohibition if scheduled within ≤ 3 trading days of earnings.">?</span>
                        </div>
                        <div class="event-risk-item">
                            <span class="risk-label">Next Scheduled Print:</span>
                            <span class="risk-val">${e.next_earnings_date || 'Unscheduled (~91d Cycle)'} (${e.days_to_earnings} trading days)</span>
                        </div>
                        <div class="event-risk-item">
                            <span class="risk-label">Last Historical Print:</span>
                            <span class="risk-val">${e.last_earnings_date ? `${e.last_earnings_date} (${e.days_since_earnings}d ago)` : 'None in window'}</span>
                        </div>
                        <div class="event-risk-item">
                            <span class="risk-label">Blackout Policy Status:</span>
                            <span class="risk-badge ${e.in_blackout ? 'badge-blackout' : (e.is_post_earnings ? 'badge-post' : 'badge-safe')}">
                                ${e.in_blackout ? '⚠️ ENTRY BLOCKED (≤ 3d to print)' : (e.is_post_earnings ? '🎉 POST-EARNINGS (PEAD Active)' : '✅ SAFE TO HOLD')}
                            </span>
                        </div>
                    </div>

                    <div class="derivatives-block">
                        <div class="title-with-tip" style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                            <h4 class="event-risk-title" style="margin: 0;">Options Positioning Profile</h4>
                            <span class="tip-badge"
                                data-tip-title="Options Market Positioning Profile"
                                data-tip-cat="DERIVATIVES ORDER FLOW"
                                data-tip-what="Breakdown of near-the-money options volume, Put/Call volume ratio, and dealer gamma positioning."
                                data-tip-rule="PCR < 0.70 reflects bullish speculative demand; PCR > 1.00 reflects defensive hedging or bearish sentiment. ATM Call vs Put GEX indicates whether dealers will support or accelerate price moves.">?</span>
                        </div>
                        <div class="event-risk-item">
                            <span class="risk-label">Call / Put Volume Ratio (PCR):</span>
                            <span class="risk-val">${d.pcr_ratio} (${(d.call_volume / 1000).toFixed(0)}k calls / ${(d.put_volume / 1000).toFixed(0)}k puts)</span>
                        </div>
                        <div class="event-risk-item">
                            <span class="risk-label">ATM Call Gamma Exposure:</span>
                            <span class="risk-val">$${(d.call_gex / 1000).toFixed(0)}k</span>
                        </div>
                        <div class="event-risk-item">
                            <span class="risk-label">ATM Put Gamma Exposure:</span>
                            <span class="risk-val">$${(d.put_gex / 1000).toFixed(0)}k</span>
                        </div>
                    </div>
                </div>
            </div>

            <!-- 7 Core Alpha Features Deep-Dive Cards -->
            <div class="features-dossier-section">
                <div class="title-with-tip" style="display: flex; align-items: center; gap: 8px; margin-bottom: 16px;">
                    <h3 class="section-title" style="margin: 0;">The 7 Core Alpha Features Breakdown</h3>
                    <span class="tip-badge"
                        data-tip-title="The 7 Core Alpha Features Engine"
                        data-tip-cat="FEATURE ARCHITECTURE"
                        data-tip-what="All 7 normalized features used by the LightGBM model to forecast cross-sectional alpha. Each feature is z-scored and mapped into a bounded [-1.0, +1.0] domain."
                        data-tip-rule="Features are evaluated against the cross-sectional universe distribution. Percentiles > 60% indicate bullish alignment; percentiles < 40% indicate bearish alignment.">?</span>
                </div>
                <div class="feature-cards-grid">
                    ${data.features.map(f => {
                        const sentClass = f.sentiment === 'BULLISH' ? 'sentiment-bullish' : (f.sentiment === 'BEARISH' ? 'sentiment-bearish' : 'sentiment-neutral');
                        const barWidth = Math.min(100, Math.max(5, (f.score + 1.0) * 50));
                        const featureTooltips = {
                            "feat_short_squeeze_pressure": {
                                "cat": "MARKET STRUCTURE",
                                "formula": "(Short Interest / ADV20) × ((Close - SMA50) / ATR14)",
                                "rule": "Values > +0.30 indicate short sellers are trapped above the 50d SMA, creating asymmetric upside squeeze potential."
                            },
                            "feat_net_gex": {
                                "cat": "DERIVATIVES MICROSTRUCTURE",
                                "formula": "ATM Call Gamma - ATM Put Gamma",
                                "rule": "Positive GEX dampens realized volatility; Negative GEX fuels momentum breakout runs."
                            },
                            "feat_pcr_momentum": {
                                "cat": "OPTIONS SENTIMENT",
                                "formula": "(PCR_10d / PCR_50d) - 1.0",
                                "rule": "Decreasing PCR (< 0) indicates institutional speculation moving aggressively into calls."
                            },
                            "feat_sector_relative_momentum": {
                                "cat": "TREND / MOMENTUM",
                                "formula": "Return_20d(Asset) - Return_20d(Sector Benchmark)",
                                "rule": "Positive excess returns identify true industry leaders outperforming their peer group."
                            },
                            "feat_vwap_divergence": {
                                "cat": "VOLUME DISTRIBUTION",
                                "formula": "(Close - Rolling_20d_VWAP) / ATR14",
                                "rule": "Measures pullbacks to institutional support. Pullbacks to 0 indicate optimal swing entry."
                            },
                            "feat_vix_slope": {
                                "cat": "MACRO REGIME",
                                "formula": "VIX Spot / VIX 3-Month",
                                "rule": "Values < 1.0 (Contango) favor equity carry and trend; values > 1.0 (Backwardation) signal macro panic."
                            },
                            "feat_sue_score": {
                                "cat": "FUNDAMENTAL PEAD DRIFT",
                                "formula": "Standardized Unexpected Earnings × exp(-λ × t)",
                                "rule": "Exploits the well-documented Post-Earnings Announcement Drift over 10-30 trading days."
                            }
                        };
                        const tipMeta = featureTooltips[f.id] || { cat: f.category, formula: f.explanation, rule: "Standardized alpha feature." };
                        return `
                            <div class="feature-detail-card card has-tip"
                                data-tip-title="${f.name}"
                                data-tip-cat="${tipMeta.cat}"
                                data-tip-what="${f.explanation}"
                                data-tip-how="${tipMeta.formula}"
                                data-tip-rule="${tipMeta.rule}">
                                <div class="f-card-header">
                                    <span class="f-category">${f.category}</span>
                                    <div style="display: flex; align-items: center; gap: 6px;">
                                        <span class="f-sentiment ${sentClass}">${f.sentiment}</span>
                                        <span class="tip-badge">?</span>
                                    </div>
                                </div>
                                <h4 class="f-name">${f.name}</h4>
                                <div class="f-score-row">
                                    <span class="f-score">${f.score > 0 ? '+' : ''}${f.score}</span>
                                    <span class="f-percentile">${f.percentile}th %ile</span>
                                </div>
                                <div class="f-meter-bg">
                                    <div class="f-meter-fill ${sentClass}" style="width: ${barWidth}%;"></div>
                                </div>
                                <p class="f-explanation">${f.explanation}</p>
                            </div>
                        `;
                    }).join('')}
                </div>
            </div>
        `;

        // Render the interactive price & VWAP chart
        this.renderSingleStockChart(data.history);
    }

    renderSingleStockChart(history) {
        const canvas = document.getElementById('chart-single-stock');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        if (this.chartSingleStock) {
            this.chartSingleStock.destroy();
        }

        const labels = history.map(h => h.date);
        const closes = history.map(h => h.close);
        const vwaps = history.map(h => h.vwap);
        const sma50s = history.map(h => h.sma_50);

        this.chartSingleStock = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Close Price ($)',
                        data: closes,
                        borderColor: '#06b6d4',
                        backgroundColor: 'rgba(6, 182, 212, 0.08)',
                        borderWidth: 2,
                        pointRadius: 0,
                        pointHoverRadius: 4,
                        fill: true,
                        tension: 0.1,
                    },
                    {
                        label: '20-Day Rolling VWAP',
                        data: vwaps,
                        borderColor: '#f59e0b',
                        borderWidth: 1.8,
                        borderDash: [5, 4],
                        pointRadius: 0,
                        fill: false,
                    },
                    {
                        label: '50-Day SMA Trend',
                        data: sma50s,
                        borderColor: '#c084fc',
                        borderWidth: 1.5,
                        borderDash: [3, 3],
                        pointRadius: 0,
                        fill: false,
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: {
                        display: true,
                        position: 'top',
                        labels: { color: '#94a3b8', font: { family: 'JetBrains Mono', size: 11 }, boxWidth: 12 }
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => ` ${context.dataset.label}: $${context.parsed.y.toFixed(2)}`
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: '#94a3b8', maxTicksLimit: 8, font: { family: 'JetBrains Mono', size: 10 } }
                    },
                    y: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: {
                            color: '#94a3b8',
                            font: { family: 'JetBrains Mono', size: 10 },
                            callback: (v) => `$${v.toFixed(0)}`
                        }
                    }
                }
            }
        });
    }
}

// Global instance
const app = new StockModelApp();
window.addEventListener('DOMContentLoaded', () => app.init());
