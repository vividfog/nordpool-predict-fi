//#region history
// ==========================================================================
// Historical price chart initialization
// ==========================================================================

var historyChart = echarts.init(document.getElementById('historyChart'));
const resolveHistoryPalette = typeof window.resolveChartPalette === 'function'
    ? window.resolveChartPalette
    : () => null;
const subscribeHistoryPalette = typeof window.subscribeThemePalette === 'function'
    ? window.subscribeThemePalette
    : () => () => {};
const HISTORY_THEME_UNSUB_KEY = '__np_history_theme_unsub__';
let historyPalette = resolveHistoryPalette('history');
let hasHistoryChartOptions = false;

function refreshHistoryTheme() {
    if (!historyChart || typeof historyChart.setOption !== 'function') {
        return;
    }
    if (!hasHistoryChartOptions) {
        return;
    }
    if (typeof applyChartTheme === 'function' && historyPalette) {
        applyChartTheme(historyChart, historyPalette);
    }
    const swarmLineColor = historyPalette?.swarmLine || 'dodgerblue';
    const currentSeries = historyChart.getOption()?.series || [];
    const swarmSeriesUpdates = currentSeries
        .filter(series => series && series.id && series.id.startsWith('history-series-'))
        .map(series => ({
            id: series.id,
            color: swarmLineColor,
            lineStyle: Object.assign({}, series.lineStyle, { color: swarmLineColor })
        }));
    historyChart.setOption({
        series: swarmSeriesUpdates.concat([
            {
                id: 'history-markline',
                markLine: createCurrentTimeMarkLine(historyPalette)
            }
        ]),
        dataZoom: [
            {
                id: 'history-zoom-slider',
                backgroundColor: historyPalette?.zoomBackground,
                borderColor: historyPalette?.zoomBorder
            },
            {
                id: 'history-zoom-inside'
            }
        ]
    }, false, true);
}

if (window[HISTORY_THEME_UNSUB_KEY]) {
    try {
        window[HISTORY_THEME_UNSUB_KEY]();
    } catch (error) {
        console.warn('Failed to cleanup history palette subscription', error);
    }
}
window[HISTORY_THEME_UNSUB_KEY] = subscribeHistoryPalette('history', palette => {
    historyPalette = palette || historyPalette;
    refreshHistoryTheme();
});

// Construct URLs for fetching historical data
const dateStrings = getPastDateStrings(35); // 30 days plus 5 days of prediction data
const historicalUrls = dateStrings.map(date => `${baseUrl}/prediction_snapshot_${date}.json`);

// Variables to store original chart data
let originalData = [];
let currentAveragePeriod = 3;
let currentPruneOption = '120'; // Default to 5-day lookahead
let sahkotinOriginalData = [];
const historyStorage = window.appStorage && window.appStorage.enabled ? window.appStorage : null;
const HISTORY_STORAGE_KEY = 'np_history_preferences';
let historyRefreshPending = null;
let lastHistoryToken = 0;
const historyDataClient = window.dataClient || null;
const historyFetchUtils = window.fetchUtils || null;

function buildHistoryRequestInit(overrides) {
    if (historyDataClient && typeof historyDataClient.applyRequestInit === 'function') {
        return historyDataClient.applyRequestInit(overrides);
    }
    if (historyFetchUtils && typeof historyFetchUtils.applyRequestInit === 'function') {
        return historyFetchUtils.applyRequestInit(overrides);
    }
    if (!overrides) {
        return { cache: 'no-cache' };
    }
    return Object.assign({ cache: 'no-cache' }, overrides);
}

const historyFetchJson = historyDataClient && typeof historyDataClient.fetchJson === 'function'
    ? (url, init) => historyDataClient.fetchJson(url, init)
    : (url, init) => fetch(url, init).then(response => {
        if (!response.ok) {
            throw new Error(`Failed to fetch JSON from ${url}: ${response.status}`);
        }
        return response.json();
    });

const historyFetchText = historyDataClient && typeof historyDataClient.fetchText === 'function'
    ? (url, init) => historyDataClient.fetchText(url, init)
    : (url, init) => fetch(url, init).then(response => {
        if (!response.ok) {
            throw new Error(`Failed to fetch text from ${url}: ${response.status}`);
        }
        return response.text();
    });

// Align cache-busting with the global helper so history refreshes behave like other modules.
const historyCacheBustUrl = typeof window.applyCacheToken === 'function'
    ? window.applyCacheToken
    : createCacheBustedUrl;

(function restoreHistoryPreferences() {
    if (!historyStorage) {
        return;
    }
    const saved = historyStorage.get(HISTORY_STORAGE_KEY);
    if (!saved) {
        return;
    }
    const savedAverage = Number(saved.averagePeriod);
    if (Number.isFinite(savedAverage) && (savedAverage === 0 || savedAverage === 3 || savedAverage === 6)) {
        currentAveragePeriod = savedAverage;
    }
    if (typeof saved.pruneOption === 'string' && saved.pruneOption.trim() !== '') {
        currentPruneOption = saved.pruneOption;
    }
})();

// ==========================================================================
// Toggle button event handlers
// ==========================================================================

document.addEventListener('DOMContentLoaded', function() {
    applyTranslations();

    const toggleButtons = document.querySelectorAll('.history-toggle button');
    const pruneDropdown = document.getElementById('pruneDropdown');
    if (pruneDropdown) {
        const candidate = Array.from(pruneDropdown.options || []).some(option => option.value === currentPruneOption)
            ? currentPruneOption
            : pruneDropdown.value;
        pruneDropdown.value = candidate;
        currentPruneOption = pruneDropdown.value;
    }

    function persistHistorySettings() {
        if (!historyStorage) {
            return;
        }
        historyStorage.set(HISTORY_STORAGE_KEY, {
            averagePeriod: currentAveragePeriod,
            pruneOption: currentPruneOption
        });
    }

    function activateAverageButton(period) {
        let matched = false;
        toggleButtons.forEach(btn => {
            const buttonPeriod = Number(btn.getAttribute('data-period'));
            if (buttonPeriod === period) {
                btn.classList.add('active');
                matched = true;
            } else {
                btn.classList.remove('active');
            }
        });
        if (!matched && toggleButtons.length) {
            toggleButtons[0].classList.add('active');
            const fallbackPeriod = Number(toggleButtons[0].getAttribute('data-period'));
            if (Number.isFinite(fallbackPeriod)) {
                currentAveragePeriod = fallbackPeriod;
            }
        }
    }

    activateAverageButton(currentAveragePeriod);
    
    toggleButtons.forEach(button => {
        button.addEventListener('click', function() {
            const nextPeriod = Number(this.getAttribute('data-period'));
            if (!Number.isFinite(nextPeriod) || nextPeriod === currentAveragePeriod) {
                return;
            }
            currentAveragePeriod = nextPeriod;
            activateAverageButton(currentAveragePeriod);
            persistHistorySettings();
            applyPruningAndAveragingToChart();
        });
    });

    if (pruneDropdown) {
        pruneDropdown.addEventListener('change', function() {
            currentPruneOption = this.value;
            persistHistorySettings();
            applyPruningAndAveragingToChart();
        });
    }

    persistHistorySettings();
});

// Apply pruning and then moving average to the chart
function applyPruningAndAveragingToChart() {
    if (!originalData.length) return;

    const option = historyChart.getOption();
    
    // Apply pruning first
    const prunedData = originalData.map(series => {
        return pruneData(series, currentPruneOption);
    });

    // Then apply moving average to the pruned data
    for (let i = 0; i < prunedData.length; i++) {
        const averagedData = calculateTimeBins(prunedData[i], currentAveragePeriod);
        if (option.series[i]) {
            option.series[i].data = averagedData;
        }
    }

    // Nordpool data is not pruned, but it is averaged
    const seriesIndex = option.series.findIndex(s => s.name === 'Nordpool');
    if (seriesIndex >= 0) {
        const averagedNordpoolData = calculateTimeBins(sahkotinOriginalData, currentAveragePeriod);
        option.series[seriesIndex].data = averagedNordpoolData;
    }

    historyChart.setOption(option, false, false);
}

// ==========================================================================
// Historical data fetching and processing
// ==========================================================================

function pruneData(data, option) {
    if (option === 'max' || !data || data.length === 0) {
        return data;
    }

    const hours = parseInt(option);
    if (isNaN(hours)) {
        return data;
    }

    const startTime = data[0][0];
    const cutoffTime = startTime + hours * 60 * 60 * 1000;
    
    return data.filter(item => item[0] < cutoffTime);
}

function fetchHistoricalData(urls, options = {}) {
    const cacheToken = Number.isFinite(options.cacheToken) ? options.cacheToken : null;
    return Promise.all(urls.map(url => {
        console.log(`[fetchHistoricalData] Fetching URL: ${url}`);

        const requestUrl = Number.isFinite(cacheToken) ? historyCacheBustUrl(url, cacheToken) : url;

        return historyFetchJson(requestUrl, buildHistoryRequestInit())
            .then(jsonData => {
                if (!jsonData) {
                    console.warn(`[fetchHistoricalData] No data returned for: ${requestUrl}`);
                    return null;
                }

                console.log(`[fetchHistoricalData] Raw JSON length for ${requestUrl}: ${jsonData.length}`);

                const match = requestUrl.match(/(\d{4}-\d{2}-\d{2})/);
                if (match) {
                    const snapshotDateString = match[1];
                    const snapshotDateTime = new Date(`${snapshotDateString}T00:00:00Z`).getTime();
                    console.log(`[fetchHistoricalData] Snapshot date: ${snapshotDateString}, which is ${snapshotDateTime} in ms UTC`);

                    const skipDays = 2; 
                    const cutoffMs = snapshotDateTime + skipDays * 24 * 60 * 60 * 1000;

                    const originalCount = jsonData.length;
                    // Only filter out data older than the day after the snapshot
                    jsonData = jsonData.filter(item => item[0] >= cutoffMs);

                    console.log(
                        `[fetchHistoricalData] Filtered out ${originalCount - jsonData.length} of ${originalCount} entries for ${url}, 
                         cutoffMs: ${cutoffMs}`
                    );
                } else {
                    console.warn(`[fetchHistoricalData] No date found in filename: ${requestUrl}`);
                }

                console.log(`[fetchHistoricalData] Final JSON length for ${requestUrl}: ${jsonData.length}`);
                return jsonData;
            })
            .catch(error => {
                console.error(`[fetchHistoricalData] Error fetching or parsing ${requestUrl}:`, error);
                return null;
            });
    }));
}

function processSahkotinCsv(csvData) {
    const lines = csvData.split('\n').slice(1); // Skip header
    return lines.map(line => {
        const [timestamp, price] = line.split(',');
        return [new Date(timestamp).getTime(), parseFloat(price)];
    });
}

//#region histchart
// ==========================================================================
// Historical chart presentation setup
// ==========================================================================

function setupHistoryChart(data, pruneOption) {
    const cleanedData = data.filter(item => item !== null).slice(1);
    console.log("setupHistoryChart found these snapshots: ", cleanedData);
    const swarmLineColor = historyPalette?.swarmLine || 'dodgerblue';

    const series = cleanedData.map((seriesData, index) => {
        // Prune data before rendering
        const prunedData = pruneData(seriesData, pruneOption);

        // Calculate opacity for older series
        // const opacityValue = index === 0 ? 0.9 : Math.max(0.5, 0.95 - (index * 0.1));
        const opacityValue = index === 0 ? 0.4 : 0.4;
        
        return {
            id: `history-series-${index}`,
            name: index === 0 ? getLocalizedText('latest') : `${index} ${getLocalizedText('daysAgo')}`,
            type: 'line',
            data: prunedData.map(item => [item[0], item[1]]),
            symbol: 'none',
            step: 'middle',
            lineStyle: {
                width: index === 0 ? 1.5 : 1.5,
                type: index === 0 ? 'dotted' : 'dotted',
                opacity: opacityValue,
                color: swarmLineColor
            },
            color: swarmLineColor
        };
    });

    // Add a separate series item for the markLine
    series.push({
        id: 'history-markline',
        type: 'line',
        data: [],
        markLine: createCurrentTimeMarkLine(historyPalette)
    });

    // Create history chart options
    const historyChartOptions = createBaseChartOptions({
        tooltipFormatter: createTooltipFormatter(),
        xAxisFormatter: createXAxisFormatter(true),
        series: series,
        isHistoryChart: true, // Flag to use weekly grid lines
        palette: historyPalette
    });

    const baseGrid = typeof window.buildChartGrid === 'function'
        ? window.buildChartGrid(historyChartOptions.grid)
        : Object.assign({ containLabel: true }, window.CHART_GRID_INSETS || {}, historyChartOptions.grid || {});
    historyChartOptions.grid = Object.assign({}, baseGrid, { bottom: 96 });
    
    // Add zoom controls to the history chart
    historyChartOptions.dataZoom = [
        {
            id: 'history-zoom-slider',
            type: 'slider',
            xAxisIndex: 0,
            start: 33,
            end: 100,
            bottom: 18,
            height: 30,
            backgroundColor: historyPalette?.zoomBackground,
            borderColor: historyPalette?.zoomBorder
        },
        {
            id: 'history-zoom-inside',
            type: 'inside',
            xAxisIndex: 0,
            start: 33,
            end: 100
        }
    ];

    historyChart.setOption(historyChartOptions);
    hasHistoryChartOptions = true;
    refreshHistoryTheme();
    console.log("setupHistoryChart found", series.length, "snapshots");
    originalData = cleanedData.map(seriesData => seriesData.map(item => [item[0], item[1]]));
    return series.length;
}

function addSahkotinDataToChart(sahkotinData) {
    // Store original data for rolling average calculations
    const originalSahkotinData = [...sahkotinData];
    
    const sahkotinSeries = {
        name: 'Nordpool',
        type: 'line',
        data: sahkotinData,
        symbol: 'none',
        step: 'middle',
        lineStyle: {
            type: 'solid',
            width: 2,
            opacity: 0.8
        },
        color: 'limegreen',
    };
    
    historyChart.setOption({
        series: historyChart.getOption().series.concat(sahkotinSeries)
    });
    
    // Apply the current average period if one is already selected
    if (currentAveragePeriod > 0) {
        // Find the Nordpool series in the chart options
        const options = historyChart.getOption();
        const seriesIndex = options.series.findIndex(s => s.name === 'Nordpool');
        
        if (seriesIndex >= 0) {
            // Apply time binning only to the Nordpool series
            const binnedData = calculateTimeBins(originalSahkotinData, currentAveragePeriod);
            options.series[seriesIndex].data = binnedData;
            historyChart.setOption(options, false, false);
        }
    }
    
    // Store the original Sähkötin data for future toggle operations
    sahkotinOriginalData = originalSahkotinData;
}

//#region sahkotin
// ==========================================================================
// Sähkötin data fetching and chart integration
// ==========================================================================

function setupSahkotinData(cacheToken) {
    const startDate = getPastDateStrings(30).pop();
    const buildIso = typeof window.getHelsinkiMidnightISOString === 'function'
        ? window.getHelsinkiMidnightISOString
        : (offset) => addDays(new Date(), offset).toISOString();
    const endDate = buildIso(3);

    const sahkotinUrl = window.SAHKOTIN_CSV_URL || 'https://sahkotin.fi/prices.csv';
    const sahkotinParams = new URLSearchParams({
        fix: 'true',
        vat: 'true',
        start: startDate,
        end: endDate,
    });

    const requestUrl = Number.isFinite(cacheToken)
        ? historyCacheBustUrl(`${sahkotinUrl}?${sahkotinParams.toString()}`, cacheToken)
        : `${sahkotinUrl}?${sahkotinParams.toString()}`;

    return historyFetchText(requestUrl, buildHistoryRequestInit())
        .then(csvData => {
            const sahkotinData = processSahkotinCsv(csvData);
            addSahkotinDataToChart(sahkotinData);
            
            // Apply the default binning after adding Sahkotin data
            applyPruningAndAveragingToChart();
        })
        .catch(error => console.error("Error fetching Sähkötin data:", error));
}

//#region init
// ==========================================================================
// Initialize history chart with fetched data
// ==========================================================================

/**
 * Refreshes history snapshots and Sähkötin data, preventing concurrent loads.
 * Applies cache-busting when a finite token is provided.
 * @param {number} [token] Optional cache-busting token (typically a timestamp).
 * @returns {Promise<void>} Resolves after charts are updated; reuses the in-flight promise.
 */
function refreshHistoryData(token) {
    if (historyRefreshPending) {
        return historyRefreshPending;
    }

    const effectiveToken = Number.isFinite(token) ? token : Date.now();

    historyRefreshPending = fetchHistoricalData(historicalUrls, { cacheToken: effectiveToken })
        .then(data => {
            setupHistoryChart(data, currentPruneOption);
            return setupSahkotinData(effectiveToken);
        })
        .then(() => {
            lastHistoryToken = effectiveToken;
        })
        .catch(error => console.error("Error in chart setup:", error))
        .finally(() => {
            historyRefreshPending = null;
        });

    return historyRefreshPending;
}

refreshHistoryData();

const historyPredictionStore = window.predictionStore || null;
if (historyPredictionStore && typeof historyPredictionStore.subscribe === 'function') {
    historyPredictionStore.subscribe(payload => {
        if (historyRefreshPending) {
            return;
        }
        const generatedAt = Number(payload?.generatedAt);
        if (!Number.isFinite(generatedAt) || generatedAt <= lastHistoryToken) {
            return;
        }
        refreshHistoryData(generatedAt);
    });
} else {
    console.warn('predictionStore unavailable; history refresh events disabled');
}

// Setup interval for marker updates
setInterval(() => updateMarkerPosition(historyChart), 10000);
