(() => {
    const root = document.documentElement;
    const themeKey = 'stockroom-theme';

    const applyTheme = (theme) => {
        root.dataset.theme = theme;
        localStorage.setItem(themeKey, theme);
        document.dispatchEvent(new CustomEvent('stockroom:themechange'));
    };

    document.querySelectorAll('[data-theme-toggle]').forEach((button) => {
        button.addEventListener('click', () => {
            applyTheme(root.dataset.theme === 'dark' ? 'light' : 'dark');
        });
    });

    const sidebar = document.getElementById('app-sidebar');
    const sidebarToggle = document.querySelector('[data-sidebar-toggle]');
    const sidebarScrim = document.querySelector('[data-sidebar-scrim]');
    const closeSidebar = () => {
        sidebar?.classList.remove('is-open');
        sidebarToggle?.setAttribute('aria-expanded', 'false');
        sidebarToggle?.setAttribute('aria-label', 'Open navigation');
        sidebarScrim?.setAttribute('hidden', '');
    };

    sidebarToggle?.addEventListener('click', () => {
        const isOpen = sidebar?.classList.toggle('is-open') ?? false;
        sidebarToggle.setAttribute('aria-expanded', String(isOpen));
        sidebarToggle.setAttribute('aria-label', isOpen ? 'Close navigation' : 'Open navigation');
        if (isOpen) sidebarScrim?.removeAttribute('hidden');
        else sidebarScrim?.setAttribute('hidden', '');
    });
    sidebarScrim?.addEventListener('click', closeSidebar);
    sidebar?.querySelectorAll('a.sidebar-link').forEach((link) => {
        link.addEventListener('click', closeSidebar);
    });

    const notificationsToggle = document.querySelector('[data-notifications-toggle]');
    const notificationsPanel = document.querySelector('[data-notifications-panel]');
    notificationsToggle?.addEventListener('click', () => {
        const isOpen = notificationsPanel?.hasAttribute('hidden') ?? false;
        if (isOpen) notificationsPanel?.removeAttribute('hidden');
        else notificationsPanel?.setAttribute('hidden', '');
        notificationsToggle.setAttribute('aria-expanded', String(isOpen));
    });

    document.querySelectorAll('[data-toast-close]').forEach((button) => {
        button.addEventListener('click', () => button.closest('.toast-message')?.remove());
    });

    document.querySelectorAll('[data-image-preview]').forEach((preview) => {
        const field = preview.closest('.form-field');
        const input = field?.querySelector('input[type="file"]');
        const image = preview.querySelector('[data-image-preview-img]');
        const label = preview.querySelector('[data-image-preview-label]');
        if (!input || !image || !label) return;

        input.addEventListener('change', () => {
            const file = input.files?.[0];
            input.setCustomValidity('');
            if (!file) return;
            if (!file.type.startsWith('image/')) {
                input.setCustomValidity('Choose an image file.');
                input.reportValidity();
                return;
            }

            const reader = new FileReader();
            reader.addEventListener('load', () => {
                if (typeof reader.result !== 'string') return;
                image.src = reader.result;
                image.alt = `Preview of ${file.name}`;
                image.hidden = false;
                label.textContent = `Preview: ${file.name}`;
            });
            reader.readAsDataURL(file);
        });
    });

    const stockProductSelect = document.querySelector('[data-stock-product]');
    const stockProductFilter = document.querySelector('[data-product-filter]');
    const currentStockDisplay = document.querySelector('[data-current-stock-display]');
    const movementQuantity = document.querySelector('[data-movement-quantity]');
    if (stockProductSelect && currentStockDisplay) {
        const updateCurrentStock = () => {
            const selectedOption = stockProductSelect.selectedOptions[0];
            if (!selectedOption?.value) {
                currentStockDisplay.textContent = 'Select a product to see its current stock.';
                return;
            }
            currentStockDisplay.textContent = `Current stock: ${selectedOption.dataset.currentStock ?? '0'} ${selectedOption.dataset.currentUnit ?? 'units'}`;
        };
        stockProductSelect.addEventListener('change', updateCurrentStock);
        updateCurrentStock();

        stockProductFilter?.addEventListener('input', () => {
            const query = stockProductFilter.value.trim().toLowerCase();
            stockProductSelect.querySelectorAll('option').forEach((option) => {
                option.hidden = Boolean(
                    query
                    && !option.selected
                    && !option.textContent.toLowerCase().includes(query),
                );
            });
        });

        if (movementQuantity) {
            const isAdjustment = window.location.pathname.endsWith('/adjust/');
            movementQuantity.min = isAdjustment ? '0' : '1';
        }
    }

    document.addEventListener('click', (event) => {
        if (notificationsPanel && !notificationsPanel.contains(event.target) && !notificationsToggle?.contains(event.target)) {
            notificationsPanel.setAttribute('hidden', '');
            notificationsToggle?.setAttribute('aria-expanded', 'false');
        }
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            closeSidebar();
            notificationsPanel?.setAttribute('hidden', '');
            notificationsToggle?.setAttribute('aria-expanded', 'false');
        }
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
            const search = document.querySelector('.topbar-search input');
            if (search) {
                event.preventDefault();
                search.focus();
            }
        }
    });

    const cssValue = (name) => getComputedStyle(root).getPropertyValue(name).trim();
    const updateChartTheme = () => {
        window.stockroomCharts?.forEach((chart) => {
            const labelColor = cssValue('--text-faint');
            const gridColor = cssValue('--border');
            if (chart.options.plugins.legend?.labels) chart.options.plugins.legend.labels.color = labelColor;
            if (chart.options.scales?.x) {
                chart.options.scales.x.ticks.color = labelColor;
                chart.options.scales.x.grid.color = gridColor;
            }
            if (chart.options.scales?.y) {
                chart.options.scales.y.ticks.color = labelColor;
                chart.options.scales.y.grid.color = gridColor;
            }
            chart.update();
        });
    };

    const initializeCharts = () => {
        const categoryCanvas = document.getElementById('category-stock-chart');
        const valueCanvas = document.getElementById('stock-value-chart');
        const valuationCanvas = document.getElementById('valuation-category-chart');
        const movementCanvas = document.getElementById('movement-daily-chart');
        if (!categoryCanvas && !valueCanvas && !valuationCanvas && !movementCanvas) return;

        if (!window.Chart) {
            document.querySelectorAll('.chart-canvas-wrap, .report-chart-wrap').forEach((container) => {
                const fallback = document.createElement('p');
                fallback.className = 'chart-fallback';
                fallback.textContent = 'Charts could not load. Check your connection and refresh the page.';
                container.replaceChildren(fallback);
            });
            return;
        }

        const labelColor = cssValue('--text-faint');
        const gridColor = cssValue('--border');
        const chartColors = [cssValue('--brand'), cssValue('--teal'), '#e7aa56', '#e7798d'];
        const charts = [];

        if (categoryCanvas) {
            const categoryDataElement = document.getElementById('stock-by-category-data');
            const categoryData = JSON.parse(categoryDataElement.textContent);
            charts.push(new Chart(categoryCanvas, {
                type: 'doughnut',
                data: {
                    labels: categoryData.map((item) => item.label),
                    datasets: [{
                        data: categoryData.map((item) => item.quantity),
                        backgroundColor: categoryData.map((_, index) => chartColors[index % chartColors.length]),
                        borderWidth: 0,
                        hoverOffset: 5,
                    }],
                },
                options: {
                    maintainAspectRatio: false,
                    cutout: '72%',
                    plugins: {
                        legend: { position: 'bottom', labels: { color: labelColor, usePointStyle: true, pointStyle: 'circle', boxWidth: 7, boxHeight: 7, padding: 14, font: { family: 'DM Sans', size: 10 } } },
                        tooltip: { callbacks: { label: (context) => ` ${context.label}: ${context.parsed.toLocaleString()} units` } },
                    },
                },
            }));
        }

        if (valueCanvas) {
            const gradient = valueCanvas.getContext('2d').createLinearGradient(0, 0, 0, 210);
            gradient.addColorStop(0, 'rgba(105, 72, 232, .20)');
            gradient.addColorStop(1, 'rgba(105, 72, 232, 0)');
            charts.push(new Chart(valueCanvas, {
                type: 'line',
                data: {
                    labels: ['May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct'],
                    datasets: [{
                        label: 'Stock value',
                        data: [28400, 31200, 29800, 36700, 35200, 41900],
                        borderColor: cssValue('--brand'),
                        backgroundColor: gradient,
                        fill: true,
                        tension: .38,
                        borderWidth: 2.5,
                        pointRadius: 3,
                        pointHoverRadius: 5,
                        pointBackgroundColor: cssValue('--surface'),
                        pointBorderColor: cssValue('--brand'),
                    }],
                },
                options: {
                    maintainAspectRatio: false,
                    interaction: { intersect: false, mode: 'index' },
                    plugins: {
                        legend: { display: false },
                        tooltip: { callbacks: { label: (context) => ` Rs ${context.parsed.y.toLocaleString()}` } },
                    },
                    scales: {
                        x: { border: { display: false }, grid: { display: false }, ticks: { color: labelColor, font: { family: 'DM Sans', size: 9 } } },
                        y: { border: { display: false }, grid: { color: gridColor }, ticks: { color: labelColor, font: { family: 'DM Sans', size: 9 }, callback: (value) => `Rs ${Number(value) / 1000}k` } },
                    },
                },
            }));
        }

        if (valuationCanvas) {
            const data = JSON.parse(
                document.getElementById('valuation-category-data').textContent,
            );
            charts.push(new Chart(valuationCanvas, {
                type: 'bar',
                data: {
                    labels: data.map((item) => item.label),
                    datasets: [{
                        label: 'Cost value',
                        data: data.map((item) => Number(item.value)),
                        backgroundColor: cssValue('--brand'),
                        borderRadius: 7,
                        maxBarThickness: 44,
                    }],
                },
                options: {
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (context) => ` Rs ${context.parsed.y.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
                            },
                        },
                    },
                    scales: {
                        x: { border: { display: false }, grid: { display: false }, ticks: { color: labelColor } },
                        y: { border: { display: false }, grid: { color: gridColor }, ticks: { color: labelColor } },
                    },
                },
            }));
        }

        if (movementCanvas) {
            const data = JSON.parse(
                document.getElementById('movement-daily-data').textContent,
            );
            charts.push(new Chart(movementCanvas, {
                type: 'line',
                data: {
                    labels: data.map((item) => item.label),
                    datasets: [
                        {
                            label: 'IN',
                            data: data.map((item) => item.in),
                            borderColor: cssValue('--teal'),
                            backgroundColor: cssValue('--teal-soft'),
                            tension: .25,
                        },
                        {
                            label: 'OUT',
                            data: data.map((item) => item.out),
                            borderColor: cssValue('--rose'),
                            backgroundColor: cssValue('--rose-soft'),
                            tension: .25,
                        },
                    ],
                },
                options: {
                    maintainAspectRatio: false,
                    interaction: { intersect: false, mode: 'index' },
                    plugins: {
                        legend: { position: 'bottom', labels: { color: labelColor } },
                    },
                    scales: {
                        x: { border: { display: false }, grid: { display: false }, ticks: { color: labelColor, maxTicksLimit: 15 } },
                        y: { beginAtZero: true, border: { display: false }, grid: { color: gridColor }, ticks: { color: labelColor } },
                    },
                },
            }));
        }

        window.stockroomCharts = charts;
        document.addEventListener('stockroom:themechange', updateChartTheme);
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeCharts);
    } else {
        initializeCharts();
    }

    document.querySelectorAll('.clickable-report-row').forEach((row) => {
        row.addEventListener('click', (event) => {
            if (!event.target.closest('a, button')) {
                window.location.assign(row.dataset.href);
            }
        });
    });
})();
