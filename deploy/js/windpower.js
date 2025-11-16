//#region windpower
// ==========================================================================
// Wind power generation chart and data handling
// ==========================================================================

//#region setup

var windPowerChart = echarts.init(document.getElementById('windPowerChart'));
const resolveWindPalette = typeof window.resolveChartPalette === 'function'
    ? window.resolveChartPalette
    : () => null;
const subscribeWindPalette = typeof window.subscribeThemePalette === 'function'
    ? window.subscribeThemePalette
    : () => () => {};
const WIND_THEME_UNSUB_KEY = '__np_windpower_theme_unsub__';
let windpowerPalette = resolveWindPalette('windpower');
let hasWindpowerOptions = false;
const windpowerEndpoints = window.DATA_ENDPOINTS || {};
const windPowerUrl = windpowerEndpoints.windpower || `${baseUrl}/windpower.json`;
const windpowerSahkotinUrl = window.SAHKOTIN_CSV_URL || 'https://sahkotin.fi/prices.csv';
const windpowerPredictionUrl = windpowerEndpoints.prediction || `${baseUrl}/prediction.json`;
let windPowerPending = null;
let lastWindPowerToken = 0;
const DEFAULT_WIND_LEGEND_COLOR = 'dodgerblue';
const DEFAULT_WIND_BAR_COLOR = '#AEB6BF';
const DEFAULT_WIND_VISUAL_PIECES = [
    { lte: 1, color: 'red' },
    { gt: 1, lte: 2, color: 'skyblue' },
    { gt: 2, lte: 3, color: 'deepskyblue' },
    { gt: 3, lte: 4, color: 'dodgerblue' },
    { gt: 4, lte: 5, color: 'blue' },
    { gt: 5, lte: 6, color: 'mediumblue' },
    { gt: 6, lte: 7, color: 'darkblue' },
    { gt: 7, color: 'midnightblue' }
];
const DEFAULT_WIND_BAR_OPACITY = 0.3;

function clonePieces(pieces) {
    return pieces.map(piece => ({ ...piece }));
}

function getWindLegendColor() {
    return windpowerPalette?.windLegend || DEFAULT_WIND_LEGEND_COLOR;
}

function getWindVisualPieces() {
    const pieces = windpowerPalette?.windVisualPieces;
    if (Array.isArray(pieces) && pieces.length) {
        return clonePieces(pieces);
    }
    return clonePieces(DEFAULT_WIND_VISUAL_PIECES);
}

function getWindBarColor() {
    return windpowerPalette?.barColor || DEFAULT_WIND_BAR_COLOR;
}

function refreshWindpowerTheme() {
    if (!windPowerChart || typeof windPowerChart.setOption !== 'function') {
        return;
    }
    if (!hasWindpowerOptions) {
        return;
    }
    if (typeof applyChartTheme === 'function' && windpowerPalette) {
        applyChartTheme(windPowerChart, windpowerPalette);
    }
    const barColor = getWindBarColor();
    const barOpacity = typeof windpowerPalette?.barOpacity === 'number'
        ? windpowerPalette.barOpacity
        : DEFAULT_WIND_BAR_OPACITY;
    const areaFill = windpowerPalette?.areaFill;
    const markLine = createCurrentTimeMarkLine(windpowerPalette);
    const windVisualPieces = getWindVisualPieces();
    windPowerChart.setOption({
        series: [
            {
                id: 'windpower-price-actual',
                itemStyle: barColor ? { color: barColor, opacity: barOpacity } : undefined
            },
            {
                id: 'windpower-price-forecast',
                itemStyle: barColor ? { color: barColor, opacity: barOpacity } : undefined
            },
            {
                id: 'windpower-series',
                areaStyle: areaFill ? { color: areaFill } : undefined,
                markLine
            }
        ],
        visualMap: [
            {
                id: 'windpower-visual-map',
                pieces: windVisualPieces,
                outOfRange: { color: windpowerPalette?.outOfRange, opacity: 1.0 }
            },
            {
                id: 'windpower-price-actual-map',
                pieces: [
                    { gt: 0, color: barColor }
                ],
                outOfRange: { color: windpowerPalette?.outOfRange, opacity: 1.0 }
            },
            {
                id: 'windpower-price-forecast-map',
                pieces: [
                    { gt: 0, color: barColor }
                ],
                outOfRange: { color: windpowerPalette?.outOfRange, opacity: 1.0 }
            }
        ]
    }, false, true);
}

if (window[WIND_THEME_UNSUB_KEY]) {
    try {
        window[WIND_THEME_UNSUB_KEY]();
    } catch (error) {
        console.warn('Failed to cleanup windpower palette subscription', error);
    }
}
window[WIND_THEME_UNSUB_KEY] = subscribeWindPalette('windpower', palette => {
    windpowerPalette = palette || windpowerPalette;
    refreshWindpowerTheme();
});

//#region request_helpers

// Use the same cache-busting helper as the rest of the app to avoid diverging logic.
const windpowerCacheBustUrl = typeof window.applyCacheToken === 'function'
    ? window.applyCacheToken
    : createCacheBustedUrl;
const windpowerDataClient = window.dataClient || null;
const windpowerFetchUtils = window.fetchUtils || null;

const applyWindpowerRequestInit = windpowerDataClient && typeof windpowerDataClient.applyRequestInit === 'function'
    ? windpowerDataClient.applyRequestInit
    : (windpowerFetchUtils && typeof windpowerFetchUtils.applyRequestInit === 'function'
        ? windpowerFetchUtils.applyRequestInit
        : (overrides) => {
            if (!overrides) {
                return { cache: 'no-cache' };
            }
            return Object.assign({ cache: 'no-cache' }, overrides);
        });

const windpowerFetchJson = windpowerDataClient && typeof windpowerDataClient.fetchJson === 'function'
    ? (url, init) => windpowerDataClient.fetchJson(url, init)
    : (url, init) => fetch(url, applyWindpowerRequestInit(init)).then(response => {
        if (!response.ok) {
            throw new Error(`Request failed (${response.status}) for ${url}`);
        }
        return response.json();
    });

const windpowerFetchText = windpowerDataClient && typeof windpowerDataClient.fetchText === 'function'
    ? (url, init) => windpowerDataClient.fetchText(url, init)
    : (url, init) => fetch(url, applyWindpowerRequestInit(init)).then(response => {
        if (!response.ok) {
            throw new Error(`Request failed (${response.status}) for ${url}`);
        }
        return response.text();
    });

// Create a two-day Sähkötin window (today + tomorrow) for the realized price bars.
// Keep it aligned with the prediction chart by sharing the same helper signature.
function buildWindpowerSahkotinParams() {
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

function cacheTokenUrl(url, token) {
    return Number.isFinite(token) ? windpowerCacheBustUrl(url, token) : url;
}

//#region fetch_flow

// ==========================================================================
// Fetching and processing wind power data
// ==========================================================================

/**
 * Fetches wind power, price, and prediction data while preventing duplicate requests.
 * Applies cache-busting when a finite token is provided and updates the chart on completion.
 * @param {number} [token] Optional cache-busting token (typically a timestamp).
 * @returns {Promise<void>} Resolves once the chart has been refreshed.
 */
function loadWindPowerData(token) {
    if (windPowerPending) {
        return windPowerPending;
    }

    const effectiveToken = Number.isFinite(token) ? token : Date.now();
    const sahkotinParams = buildWindpowerSahkotinParams();
    const sahkotinBaseUrl = `${windpowerSahkotinUrl}?${sahkotinParams.toString()}`;

    windPowerPending = Promise.all([
        windpowerFetchJson(cacheTokenUrl(windPowerUrl, effectiveToken)),
        windpowerFetchText(cacheTokenUrl(sahkotinBaseUrl, effectiveToken))
            .then(text => {
                const sahkotinData = text
                    .split('\n')
                    .slice(1)
                    .map(line => {
                        const [timestamp, price] = line.split(',');
                        const parsedTime = new Date(timestamp).getTime();
                        const numericPrice = parseFloat(price);
                        if (!Number.isFinite(parsedTime) || !Number.isFinite(numericPrice)) {
                            return null;
                        }
                        return [parsedTime, numericPrice];
                    })
                    .filter(item => Array.isArray(item));
                if (!sahkotinData.length) {
                    console.warn('No valid Sähkötin rows parsed for wind power chart; using empty price series.');
                }
                return sahkotinData;
            }),
        // Add prediction data so the price bars continue past the realized window.
        windpowerFetchJson(cacheTokenUrl(windpowerPredictionUrl, effectiveToken))
    ])
        .then(([windPowerData, sahkotinData, npfData]) => {
            console.log("Wind Power Data:", windPowerData);

            // Normalize to the start of today so we only render the current window.
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            const todayTimestamp = today.getTime();

            // Convert Fingrid data from MW to GW for display.
            const windPowerSeriesData = windPowerData
                .filter(item => item[0] >= todayTimestamp)
                .map(item => [item[0], item[1] / 1000]);

            console.log("Processed Wind Power Series Data:", windPowerSeriesData);

            // Align price data so the bar/line switch happens right after realized prices end.
            const lastSahkotinTimestamp = sahkotinData.length
                ? Math.max(...sahkotinData.map(item => item[0]))
                : Date.now();
            if (!sahkotinData.length) {
                console.warn('Wind power chart falling back to current time for overlap due to empty Sähkötin data.');
            }
            console.log("Wind Power Chart: End of Sähkötin data; next showing prediction data from:",
                new Date(lastSahkotinTimestamp).toString());

            // Overlap disabled for wind power chart: all prices are bars, line continuity not needed
            const overlapThreshold = lastSahkotinTimestamp;

            const sahkotinPriceData = sahkotinData.filter(item => item[0] >= todayTimestamp);
            const npfSeriesData = npfData
                .map(item => [item[0], item[1]])
                .filter(item => item[0] > overlapThreshold);

            const localizedPrice = getLocalizedText('price') + ' (¢/kWh)';
            const localizedWindPower = getLocalizedText('windPower');

            const barColor = getWindBarColor();
            const windLegendColor = getWindLegendColor();
            const windVisualPieces = getWindVisualPieces();

            const sahkotinPriceSeries = {
                id: 'windpower-price-actual',
                name: localizedPrice,
                type: 'bar',
                barWidth: '40%',
                data: sahkotinPriceData,
                yAxisIndex: 1,
                z: 1,
                itemStyle: {
                    color: barColor,
                    opacity: 0.3
                }
            };

            const npfPriceSeries = {
                id: 'windpower-price-forecast',
                name: localizedPrice,
                type: 'bar',
                barWidth: '40%',
                data: npfSeriesData,
                yAxisIndex: 1,
                z: 1,
                itemStyle: {
                    color: barColor,
                    opacity: 0.3
                }
            };

            const gridOverrides = {};
            const gridConfig = typeof window.buildChartGrid === 'function'
                ? window.buildChartGrid(gridOverrides)
                : Object.assign({ containLabel: true }, window.CHART_GRID_INSETS || {}, gridOverrides);

            // Create custom options for wind power chart, merging them without resetting user interactions.
            windPowerChart.setOption({
                title: { text: ' ' },
                grid: gridConfig,
                legend: {
                    data: [
                        {
                            name: localizedWindPower,
                            icon: 'circle',
                            itemStyle: {
                                color: windLegendColor
                            }
                        },
                        {
                            name: localizedPrice,
                            icon: 'circle',
                            itemStyle: {
                                color: windpowerPalette?.barColor || '#AEB6BF'
                            }
                        }
                    ],
                    right: 16,
                    selected: {
                        [localizedWindPower]: true,
                        [localizedPrice]: true
                    }
                },
                tooltip: {
                    trigger: 'axis',
                    formatter: function(params) {
                        const weekdays = getLocalizedText('weekdays');
                        const date = new Date(params[0].axisValue);

                        const weekday = weekdays[date.getDay()];
                        const day = date.getDate();
                        const month = date.getMonth() + 1;
                        const hours = ("0" + date.getHours()).slice(-2);
                        const minutes = ("0" + date.getMinutes()).slice(-2);

                        const timePrefix = getTimePrefix();
                        const formattedDateString = `${weekday} ${day}.${month}. ${timePrefix} ${hours}:${minutes}`;
                        let result = formattedDateString + '<br/>';

                        params.sort((a, b) => {
                            if (a.seriesName === localizedWindPower) return -1;
                            if (b.seriesName === localizedWindPower) return 1;
                            return 0;
                        });

                        params.forEach(function(item) {
                            if (item.seriesType !== 'line' && item.seriesType !== 'bar') return;

                            const valueRounded = item.value[1] !== undefined ? item.value[1].toFixed(1) : '';
                            result += item.marker + " " + item.seriesName + ': ' + valueRounded + '<br/>';
                        });

                        return result;
                    }
                },
                xAxis: {
                    type: 'time',
                    boundaryGap: false,
                    axisLabel: {
                        interval: 0,
                        formatter: function(value) {
                            const date = new Date(value);
                            const weekdays = getLocalizedText('weekdays');
                            return weekdays[date.getDay()];
                        }
                    },
                    axisTick: {
                        alignWithLabel: true,
                        interval: 0
                    },
                    splitLine: {
                        show: true,
                        lineStyle: {
                            color: 'silver',
                            width: 0.5,
                            type: 'dashed',
                            opacity: 0.40
                        },
                        interval: function(index, value) {
                            const date = new Date(value);
                            return date.getHours() === 0 && date.getMinutes() === 0;
                        }
                    }
                },
                yAxis: [
                    {
                        type: 'value',
                        name: 'GW',
                        nameLocation: 'end',
                        nameGap: 20,
                        max: 8,
                        min: 0,
                        nameTextStyle: {
                            fontWeight: 'regular'
                        },
                        axisLabel: {
                            formatter: function(value) {
                                return value.toFixed(0);
                            }
                        }
                    },
                    {
                        type: 'value',
                        name: localizedPrice,
                        nameLocation: 'end',
                        nameGap: 20,
                        min: 0,
                        splitLine: { show: false },
                        nameTextStyle: {
                            fontWeight: 'regular'
                        },
                        axisLabel: {
                            formatter: function(value) {
                                return value.toFixed(0);
                            }
                        }
                    }
                ],
                visualMap: [
                    {
                        id: 'windpower-visual-map',
                        show: false,
                        seriesIndex: 2,
                        pieces: windVisualPieces,
                        outOfRange: {
                            color: windpowerPalette?.outOfRange || '#999'
                        }
                    },
                    {
                        id: 'windpower-price-actual-map',
                        show: false,
                        seriesIndex: 0,
                        pieces: [
                            { gt: 0, color: barColor }
                        ],
                        outOfRange: {
                            color: windpowerPalette?.outOfRange || '#999'
                        }
                    },
                    {
                        id: 'windpower-price-forecast-map',
                        show: false,
                        seriesIndex: 1,
                        pieces: [
                            { gt: 0, color: barColor }
                        ],
                        outOfRange: {
                            color: windpowerPalette?.outOfRange || '#999'
                        }
                    }
                ],
                series: [
                    sahkotinPriceSeries,
                    npfPriceSeries,
                    {
                        id: 'windpower-series',
                        name: localizedWindPower,
                        type: 'line',
                        data: windPowerSeriesData,
                        symbol: 'none',
                        lineStyle: {
                            type: 'solid',
                            width: 1.5
                        },
                        step: 'middle',
                        areaStyle: {
                            color: windpowerPalette?.areaFill || 'rgba(135, 206, 250, 0.2)'
                        },
                        opacity: 0.9,
                        z: 2,
                        markLine: createCurrentTimeMarkLine(windpowerPalette)
                    }
                ]
            });
            hasWindpowerOptions = true;
            refreshWindpowerTheme();

            console.log("Wind Power chart ready.");
        })
        .then(() => {
            lastWindPowerToken = effectiveToken;
        })
        .catch(error => {
            console.error('Error fetching wind power data:', error);
        })
        .finally(() => {
            windPowerPending = null;
        });

    return windPowerPending;
}

//#region refresh

loadWindPowerData();

const windpowerPredictionStore = window.predictionStore || null;
if (windpowerPredictionStore && typeof windpowerPredictionStore.subscribe === 'function') {
    windpowerPredictionStore.subscribe(payload => {
        if (windPowerPending) {
            return;
        }
        const generatedAt = Number(payload?.generatedAt);
        if (!Number.isFinite(generatedAt) || generatedAt <= lastWindPowerToken) {
            return;
        }
        loadWindPowerData(generatedAt);
    });
} else {
    console.warn('predictionStore unavailable; windpower refresh events disabled');
}

// Setup interval for marker updates
setInterval(() => updateMarkerPosition(windPowerChart), 10000);

//#endregion windpower
