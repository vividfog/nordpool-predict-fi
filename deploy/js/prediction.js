//#region prediction
// ==========================================================================
// Spot price prediction chart initialization and data handling
// ==========================================================================

var nfpChart = echarts.init(document.getElementById('predictionChart'));
let predictionPalette = typeof getChartPalette === 'function'
    ? getChartPalette('prediction')
    : null;
let hasPredictionChartOptions = false;

const DEFAULT_FORECAST_LEGEND_COLOR = 'skyblue';
const DEFAULT_FORECAST_BACKGROUND_COLOR = 'deepskyblue';
const DEFAULT_FORECAST_VISUAL_PIECES = [
    { lte: 5, color: 'skyblue', opacity: 1.0 },
    { gt: 5, lte: 10, color: 'deepskyblue', opacity: 1.0 },
    { gt: 10, lte: 15, color: 'dodgerblue', opacity: 1.0 },
    { gt: 15, lte: 20, color: 'blue', opacity: 1.0 },
    { gt: 20, lte: 30, color: 'darkblue', opacity: 1.0 },
    { gt: 30, color: 'midnightblue', opacity: 1.0 }
];

function refreshPredictionTheme() {
    if (!nfpChart || typeof nfpChart.setOption !== 'function') {
        return;
    }
    if (!hasPredictionChartOptions) {
        return;
    }
    const palette = predictionPalette || {};
    if (typeof applyChartTheme === 'function') {
        applyChartTheme(nfpChart, palette);
    }
    const bgStyle = {};
    if (palette.sahkotinBar) {
        bgStyle.color = palette.sahkotinBar;
    }
    if (typeof palette.sahkotinBarOpacity === 'number') {
        bgStyle.opacity = palette.sahkotinBarOpacity;
    }
    const spikeStyle = {};
    if (palette.spikeMarker) {
        spikeStyle.color = palette.spikeMarker;
    }
    const forecastBgStyle = {};
    const forecastBgColor = palette.forecastBackgroundBar || DEFAULT_FORECAST_BACKGROUND_COLOR;
    if (forecastBgColor) {
        forecastBgStyle.color = forecastBgColor;
    }
    forecastBgStyle.opacity = 0.10;
    const scaledVisualPieces = Array.isArray(palette.forecastVisualPieces) && palette.forecastVisualPieces.length
        ? palette.forecastVisualPieces
        : DEFAULT_FORECAST_VISUAL_PIECES;
    nfpChart.setOption({
        series: [
            {
                id: 'sahkotin-bg',
                itemStyle: bgStyle
            },
            {
                id: 'scaled-price-markers',
                markPoint: {
                    itemStyle: spikeStyle
                }
            },
            {
                id: 'prediction-markline',
                markLine: createCurrentTimeMarkLine(palette)
            },
            {
                id: 'forecast-bg',
                itemStyle: forecastBgStyle
            }
        ],
        visualMap: [
            {
                id: 'scaled-visual-map',
                pieces: scaledVisualPieces
            }
        ]
    }, false, true);
}

if (typeof watchThemePalette === 'function') {
    watchThemePalette('prediction', palette => {
        predictionPalette = palette || predictionPalette;
        refreshPredictionTheme();
    });
}

const HOUR_MS = 60 * 60 * 1000;
const CHEAPEST_WINDOW_DURATIONS = [3, 6, 12];
const MAX_LOOKAHEAD_HOURS = 168;
const DEFAULT_LOOKAHEAD_DAYS = 4;
const MIN_LOOKAHEAD_DAYS = 1;
const MAX_LOOKAHEAD_DAYS = 7;
const MIN_DAY_HOUR = 0;
const MAX_DAY_HOUR = 23;
const DEFAULT_WINDOW_START_HOUR = 0;
const DEFAULT_WINDOW_END_HOUR = 23;
const HELSINKI_TIMEZONE = 'Europe/Helsinki';
const MAX_DATA_STALENESS_MS = 6 * 60 * 60 * 1000;
const REFRESH_CHECK_INTERVAL_MS = 15 * 60 * 1000;

// URLs for the datasets
const endpoints = window.DATA_ENDPOINTS || {};
const npfUrl = endpoints.prediction || `${baseUrl}/prediction.json`;
const scaledPriceUrl = endpoints.predictionScaled || `${baseUrl}/prediction_scaled.json`; // Add URL for scaled prices
const sahkotinUrl = window.SAHKOTIN_CSV_URL || 'https://sahkotin.fi/prices.csv';

const predictionStorage = window.appStorage && window.appStorage.enabled ? window.appStorage : null;
const PREDICTION_FETCH_KEY = 'np_prediction_last_fetch';
let lastFetchTimestamp = 0;
let pendingFetchPromise = null;
let hasInitialPayload = false;

// Persist last refresh across reloads so we keep the six-hour guardrails even after closing the tab.
const storedFetchTimestamp = predictionStorage ? predictionStorage.get(PREDICTION_FETCH_KEY) : null;
if (typeof storedFetchTimestamp === 'number' && Number.isFinite(storedFetchTimestamp)) {
    lastFetchTimestamp = storedFetchTimestamp;
}

// Keep cache-busting logic in sync with config.js so every module behaves identically.
const cacheBustUrl = typeof window.applyCacheToken === 'function'
    ? window.applyCacheToken
    : createCacheBustedUrl;

// ==========================================================================
// Fetching and processing prediction data
// ==========================================================================

// Calculate dates for API requests inside a helper so each refresh uses a fresh today-to-tomorrow window.
// Create a two-day Sähkötin window (today + tomorrow) to capture realized prices.
// Wrap it in a helper so the parameters stay aligned with the other charts.
function buildSahkotinParams() {
    const startIso = addDays(new Date(), 0).toISOString();
    const endIso = addDays(new Date(), 2).toISOString();
    if (typeof window.createSahkotinParams === 'function') {
        return window.createSahkotinParams(startIso, endIso);
    }
    return new URLSearchParams({
        fix: 'true',
        vat: 'true',
        start: startIso,
        end: endIso
    });
}

/**
 * Fetches prediction, scaled price, and Sähkötin data, with optional cache-busting.
 * Guards against concurrent requests by reusing an in-flight promise.
 * @param {{force?: boolean}} [options] When true, bypasses cached timestamps and forces fresh fetches.
 * @returns {Promise<void>} Resolves when data has been processed into chart state; rejects on fetch/parsing errors.
 */
function fetchPredictionData(options = {}) {
    if (pendingFetchPromise) {
        return pendingFetchPromise;
    }

    const forceReload = options.force === true;
    const cacheToken = Date.now();
    const shouldBust = forceReload || !hasInitialPayload;
    const requestInit = { cache: 'no-cache' };

    const predictionRequest = shouldBust ? cacheBustUrl(npfUrl, cacheToken) : npfUrl;
    const scaledPriceRequest = shouldBust ? cacheBustUrl(scaledPriceUrl, cacheToken) : scaledPriceUrl;
    const params = buildSahkotinParams();
    const sahkotinRequestBase = `${sahkotinUrl}?${params.toString()}`;
    const sahkotinRequest = shouldBust ? cacheBustUrl(sahkotinRequestBase, cacheToken) : sahkotinRequestBase;

    pendingFetchPromise = Promise.all([
        fetch(predictionRequest, requestInit).then(response => {
            if (!response.ok) {
                throw new Error(`Prediction fetch failed: ${response.status}`);
            }
            return response.json();
        }),
        fetch(scaledPriceRequest, requestInit)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Scaled price fetch failed: ${response.status}`);
                }
                return response.text();
            })
            .then(text => {
                try {
                    return text ? JSON.parse(text) : [];
                } catch (error) {
                    console.warn('Failed to parse scaled price data JSON:', error);
                    return [];
                }
            })
            .catch(error => {
                console.warn('Failed to fetch or parse scaled price data:', error);
                return [];
            }),
        fetch(sahkotinRequest, requestInit).then(response => {
            if (!response.ok) {
                throw new Error(`Sähkötin fetch failed: ${response.status}`);
            }
            return response.text();
        })
    ])
        .then(([npfData, scaledPriceData, sahkotinCsv]) => {
            hasInitialPayload = true;
            lastFetchTimestamp = Date.now();
            if (predictionStorage) {
                predictionStorage.set(PREDICTION_FETCH_KEY, lastFetchTimestamp);
            }
            processPredictionPayload(npfData, scaledPriceData, sahkotinCsv);
        })
        .catch(error => {
            console.error('Error fetching or processing prediction data:', error);
        })
        .finally(() => {
            pendingFetchPromise = null;
        });

    return pendingFetchPromise;
}

function processPredictionPayload(npfData, scaledPriceData, sahkotinCsv) {
    // Process Sähkötin data
    var sahkotinSeriesData = sahkotinCsv
        .split('\n')
        .slice(1)
        .map(line => {
            var [timestamp, price] = line.split(',');
            var parsedTime = new Date(timestamp).getTime();
            var numericPrice = parseFloat(price);
            if (!Number.isFinite(parsedTime) || !Number.isFinite(numericPrice)) {
                return null;
            }
            var localTime = new Date(parsedTime).toString();
            console.log(`Sähkötin timestamp: ${localTime}, Price: ${numericPrice} ¢/kWh`);
            return [parsedTime, numericPrice];
        })
        .filter(item => Array.isArray(item));

    // Find the last timestamp in Sähkötin data
    var lastSahkotinTimestamp = sahkotinSeriesData.length
        ? Math.max(...sahkotinSeriesData.map(item => item[0]))
        : Date.now();
    if (!sahkotinSeriesData.length) {
        console.warn('No valid Sähkötin rows parsed; falling back to current time for overlap.');
    }
    console.log("End of Sähkötin data for today; displaying the Nordpool prediction data from:",
        new Date(lastSahkotinTimestamp).toString());

    // Include one hour from the prediction data that overlaps with the last hour of Sähkötin data
    // to ensure continuity in the chart
    const oneHourInMilliseconds = 60 * 60 * 1000;
    const overlapThreshold = lastSahkotinTimestamp - oneHourInMilliseconds;

    // Prepare NPF series data
    var npfSeriesData = npfData
        .map(item => [item[0], item[1]])
        .filter(item => item[0] > overlapThreshold); // Include one overlapping hour

    // Debug logs
    npfSeriesData.forEach(item => {
        var localTime = new Date(item[0]).toString();
        console.log(`Prediction timestamp: ${localTime}, Price: ${item[1]} ¢/kWh`);
    });

    // Create a map of timestamps to predicted prices for later reference
    const priceByTimestamp = {};
    npfSeriesData.forEach(item => {
        priceByTimestamp[item[0]] = item[1];
    });

    // Prepare scaled price series data
    var scaledPriceSeriesData = scaledPriceData
        // Spike hours get a small red bar on the timeline
        .map(item => [item[0], item[1] !== null ? -0.25 : null])
        .filter(item => item[0] > overlapThreshold); // Use same threshold as regular predictions, keep nulls for gaps

    console.log("Scaled Price Data loaded:", scaledPriceSeriesData.length, "data points");

    const sahkotinVisualPieces = typeof getSahkotinVisualMapPieces === 'function'
        ? getSahkotinVisualMapPieces()
        : [
            { lte: 5, color: 'lime', opacity: 1.0 },
            { gt: 5, lte: 10, color: 'limegreen', opacity: 1.0 },
            { gt: 10, lte: 15, color: 'gold', opacity: 1.0 },
            { gt: 15, lte: 20, color: 'darkorange', opacity: 1.0 },
            { gt: 20, lte: 30, color: 'red', opacity: 1.0 },
            { gt: 30, color: 'darkred', opacity: 1.0 }
        ];

    // Create chart options
    const forecastLegendColor = predictionPalette?.forecastLegend || DEFAULT_FORECAST_LEGEND_COLOR;
    const forecastVisualPieces = Array.isArray(predictionPalette?.forecastVisualPieces) && predictionPalette.forecastVisualPieces.length
        ? predictionPalette.forecastVisualPieces
        : DEFAULT_FORECAST_VISUAL_PIECES;
    const forecastBackgroundColor = predictionPalette?.forecastBackgroundBar || DEFAULT_FORECAST_BACKGROUND_COLOR;

    const chartOptions = (typeof window.createBaseChartOptions === 'function'
        ? window.createBaseChartOptions
        : createBaseChartOptions)({
        palette: predictionPalette,
        legend: {
            data: [
                {
                    name: 'Nordpool',
                    icon: 'circle',
                    itemStyle: {
                        color: 'lime'
                    }
                },
                {
                    name: getLocalizedText('forecast'),
                    icon: 'circle',
                    itemStyle: {
                        color: forecastLegendColor
                    }
                },
                {
                    name: getLocalizedText('scaled_price'),
                    icon: 'circle',
                    itemStyle: {
                        color: 'crimson'
                    },
                }
            ],
            right: 16,
            selected: {
                'Nordpool': true,
                [getLocalizedText('forecast')]: true,
                [getLocalizedText('scaled_price')]: true
            }
        },
        tooltipFormatter: createTooltipFormatter(),
        visualMap: [
            {
                // For realized price
                id: 'sahkotin-visual-map',
                show: false,
                seriesIndex: [3],
                top: 50,
                right: 10,
                pieces: sahkotinVisualPieces,
                outOfRange: { color: predictionPalette?.outOfRange || '#999', opacity: 1.0 }
            },
            {
                // For predicted price
                id: 'scaled-visual-map',
                show: false,
                seriesIndex: [1],
                top: 50,
                right: 10,
                pieces: forecastVisualPieces,
                outOfRange: { color: predictionPalette?.outOfRange || '#999', opacity: 1.0 }
            }
        ],
        series: [
            {
                // Background bar for prediction data
                id: 'forecast-bg',
                name: 'Ennuste BG',
                type: 'bar',
                data: npfSeriesData,
                barWidth: '40%',
                itemStyle: {
                    color: forecastBackgroundColor,
                    opacity: 0.10
                },
                silent: true,
                z: 1,
                tooltip: {
                    show: false
                }
            },
            {
                id: 'forecast-line',
                name: getLocalizedText('forecast'),
                type: 'line',
                data: npfSeriesData,
                symbol: 'none',
                step: 'middle',
                lineStyle: {
                    width: 1.5,
                    type: 'solid'
                },
                opacity: 1.0,
                z: 3
            },
            {
                id: 'sahkotin-bg',
                name: 'Nordpool BG',
                type: 'bar',
                data: sahkotinSeriesData,
                barWidth: '40%',
                itemStyle: {
                    color: predictionPalette?.sahkotinBar || 'lime',
                    opacity: typeof predictionPalette?.sahkotinBarOpacity === 'number'
                        ? predictionPalette.sahkotinBarOpacity
                        : 0.10
                },
                silent: true,
                z: 1,
                tooltip: {
                    show: false
                }
            },
            {
                id: 'sahkotin-line',
                name: 'Nordpool',
                type: 'line',
                data: sahkotinSeriesData,
                symbol: 'none',
                step: 'middle',
                lineStyle: {
                    width: 1.5,
                    type: 'solid'
                },
                opacity: 1.0,
                z: 3
            },
            {
                id: 'scaled-price-markers',
                name: getLocalizedText('scaled_price'),
                type: 'line',
                data: scaledPriceSeriesData.map(item => [item[0], null]),
                markPoint: {
                    symbol: 'triangle',  // Options: 'circle', 'rect', 'triangle', 'diamond', 'pin', 'arrow'
                    symbolSize: [4, 4],
                    symbolRotate: 0,
                    itemStyle: {
                        color: predictionPalette?.spikeMarker || 'crimson'
                    },
                    data: scaledPriceSeriesData
                        .filter(item => {
                            // Only show triangles for hours with both a spike risk AND a price > 5 cents
                            return item[1] !== null && priceByTimestamp[item[0]] > 8;
                        })
                        .map(item => ({
                            coord: [item[0], 0.1],
                            value: ''
                        }))
                },
                tooltip: {
                    show: false
                },
                z: 5
            },
            {
                type: 'line',
                id: 'prediction-markline',
                markLine: createCurrentTimeMarkLine(predictionPalette),
                z: 4
            }
        ]
    });

    // Push the merged options without wiping user zoom/legend state.
    nfpChart.setOption(chartOptions);
    hasPredictionChartOptions = true;
    refreshPredictionTheme();

    const mergedSeries = mergePriceSeries(sahkotinSeriesData, npfSeriesData);
    const cheapestPayload = buildCheapestWindowPayload(mergedSeries, Date.now());
    window.latestPredictionData = {
        mergedSeries,
        sahkotinSeries: sahkotinSeriesData,
        forecastSeries: npfSeriesData,
        scaledPriceSeries: scaledPriceSeriesData,
        generatedAt: cheapestPayload.generatedAt,
        windows: cheapestPayload.windows,
        meta: cheapestPayload.meta
    };
    window.dispatchEvent(new CustomEvent('prediction-data-ready', { detail: window.latestPredictionData }));
}

// Prime the chart with the most recent data on initial load.
fetchPredictionData({ force: true });

function getLatestDataTimestamp() {
    if (window.latestPredictionData && Number.isFinite(window.latestPredictionData.generatedAt)) {
        return window.latestPredictionData.generatedAt;
    }
    return lastFetchTimestamp;
}

function maybeRefreshPredictionData() {
    const now = Date.now();
    const latestTimestamp = getLatestDataTimestamp();
    if (pendingFetchPromise) {
        return;
    }
    if (!Number.isFinite(latestTimestamp) || Math.abs(now - latestTimestamp) >= MAX_DATA_STALENESS_MS) {
        fetchPredictionData({ force: true });
    }
}

setInterval(maybeRefreshPredictionData, REFRESH_CHECK_INTERVAL_MS);
if (typeof window !== 'undefined') {
    window.addEventListener('focus', () => {
        maybeRefreshPredictionData();
    });
}
document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
        maybeRefreshPredictionData();
    }
});

// Setup interval for marker updates
setInterval(() => updateMarkerPosition(nfpChart), 10000);

//#endregion prediction

function mergePriceSeries(actualSeries, forecastSeries) {
    const merged = new Map();

    if (Array.isArray(forecastSeries)) {
        forecastSeries.forEach(item => {
            if (!Array.isArray(item) || item.length < 2) return;
            const timestamp = Number(item[0]);
            const value = Number(item[1]);
            if (Number.isFinite(timestamp) && Number.isFinite(value)) {
                merged.set(timestamp, value);
            }
        });
    }

    if (Array.isArray(actualSeries)) {
        actualSeries.forEach(item => {
            if (!Array.isArray(item) || item.length < 2) return;
            const timestamp = Number(item[0]);
            const value = Number(item[1]);
            if (Number.isFinite(timestamp) && Number.isFinite(value)) {
                merged.set(timestamp, value);
            }
        });
    }

    return Array.from(merged.entries())
        .map(([timestamp, value]) => [Number(timestamp), Number(value)])
        .sort((a, b) => a[0] - b[0]);
}

function clampLookaheadDays(days) {
    if (!Number.isFinite(days)) {
        return DEFAULT_LOOKAHEAD_DAYS;
    }
    const rounded = Math.round(days);
    if (rounded < MIN_LOOKAHEAD_DAYS) {
        return MIN_LOOKAHEAD_DAYS;
    }
    if (rounded > MAX_LOOKAHEAD_DAYS) {
        return MAX_LOOKAHEAD_DAYS;
    }
    return rounded;
}

function computeLookaheadHours(nowMs, lookaheadDays) {
    const timestamp = Number.isFinite(nowMs) ? nowMs : Date.now();
    const days = clampLookaheadDays(lookaheadDays);
    const currentHour = getHelsinkiHour(timestamp);
    const remainderHours = Math.max(24 - (currentHour + 1), 0);
    const total = remainderHours + days * 24;
    const bounded = Math.min(Math.max(total, 1), MAX_LOOKAHEAD_HOURS);
    return bounded;
}

function buildCheapestWindowPayload(series, nowMs, options = {}) {
    const finiteSeries = Array.isArray(series)
        ? series.filter(item => Array.isArray(item) && Number.isFinite(item[0]) && Number.isFinite(item[1]))
        : [];

    const generatedAt = Number.isFinite(nowMs) ? nowMs : Date.now();
    const lookaheadDays = clampLookaheadDays(options.lookaheadDays ?? DEFAULT_LOOKAHEAD_DAYS);
    const startHour = clampHour(options.startHour ?? DEFAULT_WINDOW_START_HOUR);
    const endHour = clampHour(options.endHour ?? DEFAULT_WINDOW_END_HOUR);
    const lookaheadHours = computeLookaheadHours(generatedAt, lookaheadDays);
    const anchor = Math.floor(generatedAt / HOUR_MS) * HOUR_MS;
    const lookaheadLimit = anchor + lookaheadHours * HOUR_MS;
    const mask = buildStartHourMask(startHour, endHour);

    const windows = CHEAPEST_WINDOW_DURATIONS.map(duration => {
        const windowResult = computeCheapestWindow(finiteSeries, duration, {
            nowMs: generatedAt,
            lookaheadLimit,
            mask
        });
        return formatWindowPayload(duration, windowResult);
    });

    return {
        generatedAt,
        windows,
        meta: {
            lookaheadHours,
            lookaheadLimit,
            lookaheadDays,
            startHour,
            endHour
        }
    };
}

function computeCheapestWindow(series, hours, options) {
    if (!Array.isArray(series) || series.length === 0 || !Number.isFinite(hours) || hours <= 0) {
        return null;
    }

    const nowMs = options?.nowMs ?? Date.now();
    const lookaheadLimit = options?.lookaheadLimit;
    const startHour = clampHour(options?.startHour ?? MIN_DAY_HOUR);
    const endHour = clampHour(options?.endHour ?? MAX_DAY_HOUR);
    const mask = options?.mask ?? buildStartHourMask(startHour, endHour);

    const anchor = Math.floor(nowMs / HOUR_MS) * HOUR_MS;
    const earliestStartCandidate = anchor - (hours - 1) * HOUR_MS;
    const firstStart = series[0][0];
    const earliestStart = Number.isFinite(firstStart)
        ? Math.max(firstStart, earliestStartCandidate)
        : earliestStartCandidate;

    const firstPass = findCheapestWindow(series, hours, {
        earliestStart,
        minEnd: nowMs,
        maxEnd: lookaheadLimit,
        mask
    });

    if (firstPass) {
        return firstPass;
    }

    return findCheapestWindow(series, hours, {
        earliestStart,
        maxEnd: lookaheadLimit,
        mask
    });
}

function findCheapestWindow(series, hours, constraints) {
    if (!Array.isArray(series) || series.length < hours) {
        return null;
    }

    const earliestStart = constraints?.earliestStart;
    const minEnd = constraints?.minEnd;
    const maxEnd = constraints?.maxEnd;
    const mask = constraints?.mask;

    let bestWindow = null;

    for (let index = 0; index <= series.length - hours; index++) {
        const slice = series.slice(index, index + hours);
        if (!isHourlySequence(slice)) {
            continue;
        }

        const startTime = slice[0][0];
        const endTime = slice[slice.length - 1][0] + HOUR_MS;

        if (Number.isFinite(earliestStart) && startTime < earliestStart) {
            continue;
        }
        if (Number.isFinite(minEnd) && endTime < minEnd) {
            continue;
        }
        if (Number.isFinite(maxEnd) && endTime > maxEnd) {
            continue;
        }
        if (mask && !mask.has(getHelsinkiHour(startTime))) {
            continue;
        }

        const average = slice.reduce((sum, item) => sum + item[1], 0) / hours;

        if (!bestWindow || average < bestWindow.average) {
            bestWindow = {
                start: startTime,
                end: endTime,
                average,
                points: slice
            };
        }
    }

    return bestWindow;
}

function isHourlySequence(windowPoints) {
    if (!Array.isArray(windowPoints) || windowPoints.length <= 1) {
        return true;
    }

    for (let idx = 1; idx < windowPoints.length; idx++) {
        const prev = windowPoints[idx - 1][0];
        const current = windowPoints[idx][0];
        if (!Number.isFinite(prev) || !Number.isFinite(current)) {
            return false;
        }
        if (Math.abs((current - prev) - HOUR_MS) > 1000) {
            return false;
        }
    }

    return windowPoints.every(point => Number.isFinite(point[1]));
}

function buildStartHourMask(startHour, endHour) {
    const normalizedStart = clampHour(startHour);
    const normalizedEnd = clampHour(endHour);

    if (normalizedStart === 0 && normalizedEnd === 23) {
        return null;
    }

    const mask = new Set();
    let hour = normalizedStart;
    while (true) {
        mask.add(hour);
        if (hour === normalizedEnd) {
            break;
        }
        hour = (hour + 1) % 24;
    }
    return mask;
}

function clampHour(hour) {
    if (!Number.isFinite(hour)) {
        return MIN_DAY_HOUR;
    }
    if (hour < MIN_DAY_HOUR) {
        return MIN_DAY_HOUR;
    }
    if (hour > MAX_DAY_HOUR) {
        return MAX_DAY_HOUR;
    }
    return Math.floor(hour);
}

function getHelsinkiHour(timestampMs) {
    const date = new Date(timestampMs);
    const formatter = new Intl.DateTimeFormat('en-US', {
        hour: 'numeric',
        hour12: false,
        timeZone: HELSINKI_TIMEZONE
    });
    const parts = formatter.formatToParts(date);
    const hourPart = parts.find(part => part.type === 'hour');
    return hourPart ? Number(hourPart.value) : date.getUTCHours();
}

function formatWindowPayload(duration, windowResult) {
    if (!windowResult) {
        return {
            duration,
            average: null,
            start: null,
            end: null
        };
    }

    return {
        duration,
        average: windowResult.average,
        start: windowResult.start,
        end: windowResult.end
    };
}

window.buildCheapestWindowPayload = buildCheapestWindowPayload;
window.CHEAPEST_WINDOW_DEFAULTS = {
    lookaheadDays: DEFAULT_LOOKAHEAD_DAYS,
    minLookaheadDays: MIN_LOOKAHEAD_DAYS,
    maxLookaheadDays: MAX_LOOKAHEAD_DAYS,
    startHour: DEFAULT_WINDOW_START_HOUR,
    endHour: DEFAULT_WINDOW_END_HOUR,
    minHour: MIN_DAY_HOUR,
    maxHour: MAX_DAY_HOUR
};
window.computeCheapestLookaheadHours = computeLookaheadHours;
