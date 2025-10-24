//#region prediction
// ==========================================================================
// Spot price prediction chart initialization and data handling
// ==========================================================================

var nfpChart = echarts.init(document.getElementById('predictionChart'));

// Calculate dates for API requests
var startDate = addDays(new Date(), -0).toISOString();
var endDate = addDays(new Date(), 2).toISOString();

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

// URLs for the datasets
var npfUrl = `${baseUrl}/prediction.json`;
var scaledPriceUrl = `${baseUrl}/prediction_scaled.json`; // Add URL for scaled prices
var sahkotinUrl = 'https://sahkotin.fi/prices.csv';
var sahkotinParams = new URLSearchParams({
    fix: 'true',
    vat: 'true',
    start: startDate,
    end: endDate,
});

// ==========================================================================
// Fetching and processing prediction data
// ==========================================================================

Promise.all([
    fetch(npfUrl).then(r => r.json()),
    fetch(scaledPriceUrl)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error ${response.status}`);
            }
            return response.text();
        })
        .then(text => {
            try {
                return text ? JSON.parse(text) : [];
            } catch (e) {
                console.warn('Failed to parse scaled price data JSON:', e);
                return [];
            }
        })
        .catch(e => { 
            console.warn('Failed to fetch or parse scaled price data:', e); 
            return []; 
        }),
    fetch(`${sahkotinUrl}?${sahkotinParams}`).then(r => r.text())
])
    .then(([npfData, scaledPriceData, sahkotinCsv]) => {
        // Process Sähkötin data
        var sahkotinSeriesData = sahkotinCsv.split('\n').slice(1).map(line => {
            var [timestamp, price] = line.split(',');
            var parsedTime = new Date(timestamp).getTime();
            var localTime = new Date(parsedTime).toString();
            console.log(`Sähkötin timestamp: ${localTime}, Price: ${parseFloat(price)} ¢/kWh`);
            return [parsedTime, parseFloat(price)];
        });

        // Find the last timestamp in Sähkötin data
        var lastSahkotinTimestamp = Math.max(...sahkotinSeriesData.map(item => item[0]));
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

        // Create chart options
        const chartOptions = createBaseChartOptions({
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
                            color: 'skyblue'
                        }
                    }, 
                    {
                        name: getLocalizedText('scaled_price'),
                        // Specify the desired icon shape
                        icon: 'circle', 
                        // Specify the desired color for the legend item
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
                    show: false,
                    seriesIndex: [3],
                    top: 50,
                    right: 10,
                    pieces: [
                        { lte: 5, color: 'lime', opacity: 1.0 },
                        { gt: 5, lte: 10, color: 'limegreen', opacity: 1.0 },
                        { gt: 10, lte: 15, color: 'gold', opacity: 1.0 },
                        { gt: 15, lte: 20, color: 'darkorange', opacity: 1.0 },
                        { gt: 20, lte: 30, color: 'red', opacity: 1.0 },
                        { gt: 30, color: 'darkred', opacity: 1.0 }
                    ],
                    outOfRange: { color: '#999', opacity: 1.0 }
                },
                {
                    // For predicted price
                    show: false,
                    seriesIndex: [1],
                    top: 50,
                    right: 10,
                    pieces: [
                        { lte: 5, color: 'skyblue', opacity: 1.0 },
                        { gt: 5, lte: 10, color: 'deepskyblue', opacity: 1.0 },
                        { gt: 10, lte: 15, color: 'dodgerblue', opacity: 1.0 },
                        { gt: 15, lte: 20, color: 'blue', opacity: 1.0 },
                        { gt: 20, lte: 30, color: 'darkblue', opacity: 1.0 },
                        { gt: 30, color: 'midnightblue', opacity: 1.0 }
                    ],
                    outOfRange: { color: '#999', opacity: 1.0 }
                }
            ],
            series: [
                {
                    // Background bar for prediction data
                    name: 'Ennuste BG',
                    type: 'bar',
                    data: npfSeriesData,
                    barWidth: '40%',
                    itemStyle: {
                        color: 'deepskyblue',
                        opacity: 0.10
                    },
                    silent: true,
                    z: 1,
                    tooltip: {
                        show: false
                    }
                },
                {
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
                    // Background bar for realized price data
                    name: 'Nordpool BG',
                    type: 'bar',
                    data: sahkotinSeriesData,
                    barWidth: '40%',
                    itemStyle: {
                        color: 'lime',
                        opacity: 0.10
                    },
                    silent: true,
                    z: 1,
                    tooltip: {
                        show: false
                    }
                },
                {
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
                    name: getLocalizedText('scaled_price'),
                    type: 'line',
                    data: scaledPriceSeriesData.map(item => [item[0], null]),
                    markPoint: {
                        symbol: 'triangle',  // Options: 'circle', 'rect', 'triangle', 'diamond', 'pin', 'arrow'
                        symbolSize: [4, 4],
                        symbolRotate: 0,
                        itemStyle: {
                            color: 'crimson'
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
                    markLine: createCurrentTimeMarkLine(),
                    z: 4
                }
            ]
        });

        nfpChart.setOption(chartOptions);

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
    })
    .catch(error => {
        console.error('Error fetching or processing data:', error);
    });

// Setup interval for marker updates
setInterval(() => updateMarkerPosition(nfpChart), 10000);

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
