if (window.location.hostname === "nordpool-predict-fi.web.app") {
    window.location.href = "https://sahkovatkain.web.app" + window.location.pathname + window.location.search;
}

//#region conf
// ==========================================================================
// Base configuration and environment detection
// ==========================================================================

// Determine base URL based on hosting environment
var baseUrl = window.location.origin;

//#region endpoints
// ==========================================================================
// Shared data source endpoints and helpers
// ==========================================================================

const DATA_ENDPOINTS = Object.freeze({
    prediction: `${baseUrl}/prediction.json`,
    predictionScaled: `${baseUrl}/prediction_scaled.json`,
    windpower: `${baseUrl}/windpower.json`
});

const SAHKOTIN_CSV_URL = 'https://sahkotin.fi/prices.csv';

function createSahkotinParams(startIso, endIso) {
    return new URLSearchParams({
        fix: 'true',
        vat: 'true',
        start: startIso,
        end: endIso
    });
}

window.DATA_ENDPOINTS = DATA_ENDPOINTS;
window.SAHKOTIN_CSV_URL = SAHKOTIN_CSV_URL;
window.createSahkotinParams = createSahkotinParams;

// Lightweight localStorage adapter with graceful fallback
const LOCAL_STORAGE_ENABLED = (() => {
    try {
        const probe = '__np_storage_probe__';
        window.localStorage.setItem(probe, probe);
        window.localStorage.removeItem(probe);
        return true;
    } catch (error) {
        return false;
    }
})();

const appStorage = {
    enabled: LOCAL_STORAGE_ENABLED,
    get(key, fallback = null) {
        if (!LOCAL_STORAGE_ENABLED) {
            return fallback;
        }
        try {
            const raw = window.localStorage.getItem(key);
            return raw === null ? fallback : JSON.parse(raw);
        } catch (error) {
            console.warn('appStorage.get failed', error);
            return fallback;
        }
    },
    set(key, value) {
        if (!LOCAL_STORAGE_ENABLED) {
            return;
        }
        try {
            window.localStorage.setItem(key, JSON.stringify(value));
        } catch (error) {
            console.warn('appStorage.set failed', error);
        }
    },
    remove(key) {
        if (!LOCAL_STORAGE_ENABLED) {
            return;
        }
        try {
            window.localStorage.removeItem(key);
        } catch (error) {
            console.warn('appStorage.remove failed', error);
        }
    }
};

window.appStorage = appStorage;

/**
 * Appends a cache-busting query parameter to a URL.
 * When token is undefined, uses the current timestamp; returns the original URL if falsy.
 * @param {string} url The base URL to augment.
 * @param {number} [token] Optional cache key; defaults to Date.now().
 * @returns {string} URL with cache-busting query parameter applied.
 */
function createCacheBustedUrl(url, token) {
    if (!url) {
        return url;
    }
    const suffix = typeof token === 'undefined' ? Date.now() : token;
    const separator = url.includes('?') ? '&' : '?';
    return `${url}${separator}cb=${suffix}`;
}

window.createCacheBustedUrl = createCacheBustedUrl;

function applyCacheToken(url, token) {
    if (!Number.isFinite(token)) {
        return url;
    }
    return createCacheBustedUrl(url, token);
}

window.applyCacheToken = applyCacheToken;

const CHART_GRID_INSETS = Object.freeze({
    left: 24,
    right: 24,
    top: 32,
    bottom: 72
});

window.CHART_GRID_INSETS = CHART_GRID_INSETS;

function buildChartGrid(overrides) {
    const base = Object.assign({ containLabel: true }, CHART_GRID_INSETS);
    if (!overrides) {
        return base;
    }
    return Object.assign({}, base, overrides);
}

window.buildChartGrid = buildChartGrid;

//#region utils
// ==========================================================================
// Date and time handling utilities
// ==========================================================================

function addDays(date, days) {
    var result = new Date(date);
    result.setHours(0, 0, 0, 0);
    result.setDate(result.getDate() + days);
    return result;
}

function getPastDateStrings(count) {
    const dates = [];
    for (let i = 0; i < count; i++) {
        const d = new Date();
        d.setDate(d.getDate() - i);
        dates.push(d.toISOString().split('T')[0]); // Format YYYY-MM-DD
    }
    return dates;
}

function formatCurrentTimeLabel() {
    // Use the new utility function
    const prefix = getTimePrefix();

    const now = new Date();
    const day = now.getDate();
    const month = now.getMonth() + 1;
    let hours = now.getHours();
    let minutes = now.getMinutes();

    hours = hours < 10 ? '0' + hours : hours;
    minutes = minutes < 10 ? '0' + minutes : minutes;

    return `${day}.${month}. ${prefix} ${hours}:${minutes}`;
}

// Calculate moving average of a time series
function calculateMovingAverage(data, hours) {
    if (!data || !data.length || hours <= 0) return data;
    
    const result = [];
    const windowSize = hours * 1; // Assuming 1 data point per hour
    
    // Return original data if moving average period is 0 or undefined
    if (hours === 0) return data;
    
    for (let i = 0; i < data.length; i++) {
        let sum = 0;
        let count = 0;
        
        // Look back for previous values
        for (let j = 0; j < windowSize; j++) {
            if (i - j >= 0) {
                sum += data[i - j][1];
                count++;
            }
        }
        
        // Calculate the average
        const avg = count > 0 ? sum / count : data[i][1];
        result.push([data[i][0], avg]);
    }
    
    return result;
}

// Group time series data into time bins (1h, 6h, 12h) 
function calculateTimeBins(data, binSizeHours) {
    if (!data || !data.length || binSizeHours <= 0) return data;
    
    // Return original data if bin size is 1 hour or less
    if (binSizeHours <= 1) return data;
    
    const result = [];
    const bins = {};
    
    // Group data points into bins
    data.forEach(([timestamp, value]) => {
        // Create bin key by flooring to the nearest bin boundary
        const date = new Date(timestamp);
        const hours = date.getHours();
        // Calculate which bin this timestamp belongs to
        const binHour = Math.floor(hours / binSizeHours) * binSizeHours;
        
        // Create a new date with the bin boundary hour
        const binDate = new Date(date);
        binDate.setHours(binHour, 0, 0, 0);
        const binKey = binDate.getTime();
        
        // Add to bin
        if (!bins[binKey]) {
            bins[binKey] = { sum: 0, count: 0, timestamp: binKey };
        }
        bins[binKey].sum += value;
        bins[binKey].count += 1;
    });
    
    // Calculate average for each bin
    Object.values(bins).forEach(bin => {
        const avg = bin.count > 0 ? bin.sum / bin.count : 0;
        result.push([bin.timestamp, avg]);
    });
    
    // Sort by timestamp
    result.sort((a, b) => a[0] - b[0]);
    
    return result;
}

// ==========================================================================
// Chart construction and formatting utilities
// ==========================================================================

// Get language-specific time prefix based on current pathname
function getTimePrefix() {
    return window.location.pathname.includes('index_en') ? 'at' : 'klo';
}

// Get localized text based on current pathname
function getLocalizedText(key) {
    const isEnglish = window.location.pathname.includes('index_en');

    const translations = {
        'forecast': isEnglish ? 'Forecast' : 'Ennuste',
        'price': isEnglish ? 'Price' : 'Hinta',
        'windPower': isEnglish ? 'Wind Power (GW)' : 'Tuulivoima (GW)',
        'latest': isEnglish ? 'Latest' : 'Viimeisin',
        'daysAgo': isEnglish ? 'd ago' : 'pv sitten',
        'all_data': isEnglish ? 'All predictions' : 'Kaikki ennusteet',
        '1_day': isEnglish ? '1 day advance' : '1 vrk ennakko',
        '2_days': isEnglish ? '2 day advance' : '2 vrk ennakko',
        '3_days': isEnglish ? '3 day advance' : '3 vrk ennakko',
        '4_days': isEnglish ? '4 day advance' : '4 vrk ennakko',
        '5_days': isEnglish ? '5 day advance' : '5 vrk ennakko',
        '1h_avg': isEnglish ? '1 h' : '1 h',
        '3h_avg': isEnglish ? 'average 3 h' : 'keskiarvo 3 h',
        '6h_avg': isEnglish ? 'average 6 h' : 'keskiarvo 6 h',
        'scaled_price': isEnglish ? 'Price spikes' : 'Hintapiikkejä',
        'weekdays': isEnglish ?
            ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] :
            ['su', 'ma', 'ti', 'ke', 'to', 'pe', 'la'],
        'cheapest_column_duration': isEnglish ? 'Length' : 'Pituus',
        'cheapest_column_average': isEnglish ? 'Average ¢/kWh' : 'Keskihinta ¢/kWh',
        'cheapest_column_countdown': isEnglish ? 'Countdown' : 'Alkuun',
        'cheapest_column_start': isEnglish ? 'Starts' : 'Alkaa',
        'cheapest_waiting': isEnglish ? 'Waiting for data' : 'Odottaa tietoja',
        'cheapest_now': isEnglish ? 'Now' : 'Nyt',
        'cheapest_ended': isEnglish ? 'Ended' : 'Päättynyt',
        'cheapest_day_unit': isEnglish ? 'd' : 'pv',
        'cheapest_hour_unit': 'h',
        'cheapest_minute_unit': 'min',
        'cheapest_table_loading': isEnglish ? 'Loading data...' : 'Ladataan tietoja...',
        'cheapest_table_none': isEnglish ? 'No windows available yet' : 'Saatavilla olevia jaksoja ei vielä ole',
        'calendar_loading': isEnglish ? 'Loading hourly prices...' : 'Ladataan tuntihintoja...',
        'calendar_no_data': isEnglish ? 'Waiting for price data' : 'Odottaa hintatietoja...'
    };

    return translations[key] || key;
}

const SAHKOTIN_PRICE_BANDS = [
    { min: -Infinity, max: 5, color: 'lime' },
    { min: 5, max: 10, color: 'limegreen' },
    { min: 10, max: 15, color: 'gold' },
    { min: 15, max: 20, color: 'darkorange' },
    { min: 20, max: 30, color: 'red' },
    { min: 30, max: Infinity, color: 'darkred' }
];

function getSahkotinPriceColor(value, fallback = '#999') {
    if (!Number.isFinite(value)) {
        return fallback;
    }
    for (const band of SAHKOTIN_PRICE_BANDS) {
        const lowerOk = value >= (Number.isFinite(band.min) ? band.min : -Infinity);
        const upperOk = value <= (Number.isFinite(band.max) ? band.max : Infinity);
        if (lowerOk && upperOk) {
            return band.color;
        }
    }
    return fallback;
}

function getSahkotinVisualMapPieces() {
    return SAHKOTIN_PRICE_BANDS.map((band, index) => {
        const piece = { color: band.color, opacity: 1.0 };
        if (index === 0) {
            if (Number.isFinite(band.max)) {
                piece.lte = band.max;
            }
        } else if (index === SAHKOTIN_PRICE_BANDS.length - 1) {
            if (Number.isFinite(band.min)) {
                piece.gt = band.min;
            }
        } else {
            if (Number.isFinite(band.min)) {
                piece.gt = band.min;
            }
            if (Number.isFinite(band.max)) {
                piece.lte = band.max;
            }
        }
        return piece;
    });
}

window.SAHKOTIN_PRICE_BANDS = SAHKOTIN_PRICE_BANDS;
window.getSahkotinPriceColor = getSahkotinPriceColor;
window.getSahkotinVisualMapPieces = getSahkotinVisualMapPieces;

function applyTranslations() {
    document.querySelectorAll('[data-i18n]').forEach(element => {
        const key = element.getAttribute('data-i18n');
        const translation = getLocalizedText(key);
        if (translation) {
            if (element.tagName === 'OPTION') {
                element.textContent = translation;
            }
        }
    });
}

// Create vertical gridlines for day or week boundaries
function createTimeGrids(isWeekOnly = false) {
    return {
        xAxis: {
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
                    if (isWeekOnly) {
                        // For weekly grid (Monday), day of week is 1 for Monday
                        return date.getDay() === 1;
                    } else {
                        // For daily grid, hours and minutes should be 0
                        return date.getHours() === 0 && date.getMinutes() === 0;
                    }
                }
            }
        }
    };
}

function createTooltipFormatter(seriesNameMappings = {}) {
    return function(params) {
        var weekdays = getLocalizedText('weekdays');
        var date = new Date(params[0].axisValue);
        
        var weekday = weekdays[date.getDay()];
        var day = date.getDate();
        var month = date.getMonth() + 1;
        var hours = ("0" + date.getHours()).slice(-2);
        var minutes = ("0" + date.getMinutes()).slice(-2);
        
        // Use dynamic time prefix
        var timePrefix = getTimePrefix();
        var formattedDateString = `${weekday} ${day}.${month}. ${timePrefix} ${hours}:${minutes}`;
        var result = formattedDateString + '<br/>';
        
        // Sort params to show Nordpool data first if it exists
        params.sort((a, b) => {
            if (a.seriesName === 'Nordpool') return -1;
            if (b.seriesName === 'Nordpool') return 1;
            return 0;
        });
        
        params.forEach(function(item) {
            if (item.seriesType !== 'line' && item.seriesType !== 'bar') return;
            
            // Check if item.value[1] is not null or undefined before calling toFixed
            var valueRounded = (item.value[1] !== null && typeof item.value[1] !== 'undefined') 
                               ? item.value[1].toFixed(1) 
                               : '-'; // Display '-' for null/undefined values
            var unitLabel = seriesNameMappings[item.seriesName] || '¢/kWh';
            result += item.marker + " " + item.seriesName + ': ' + valueRounded + ' ' + unitLabel + '<br/>';
        });
        
        return result;
    };
}

function createXAxisFormatter(showFullDate = false) {
    return function(value) {
        var date = new Date(value);
        var weekdays = getLocalizedText('weekdays');
        var weekday = weekdays[date.getDay()];
        
        if (showFullDate) {
            var day = date.getDate();
            var month = date.getMonth() + 1;
            return day + '.' + month + '.';
        }
        return weekday;
    };
}

function createCurrentTimeMarkLine() {
    return {
        symbol: 'none',
        label: {
            formatter: formatCurrentTimeLabel,
            position: 'end',
            color: 'Black',
            fontSize: 11
        },
        lineStyle: {
            type: 'dotted',
            color: 'rgba(51, 51, 51, 0.9)',
            width: 2,
            opacity: 0.5
        },
        data: [{ xAxis: new Date().getTime() }]
    };
}

//#region options
// ==========================================================================
// Chart base configuration builder
// ==========================================================================

function createBaseChartOptions(config) {
    // Create base options
    const grid = buildChartGrid(config.grid);
    const baseOptions = {
        title: { text: ' ' },
        legend: config.legend || { show: false },
        tooltip: {
            trigger: 'axis',
            formatter: config.tooltipFormatter || createTooltipFormatter()
        },
        grid,
        xAxis: {
            type: 'time',
            boundaryGap: false,
            axisLabel: {
                interval: 0,
                formatter: config.xAxisFormatter || createXAxisFormatter()
            },
            axisTick: {
                alignWithLabel: true,
                interval: 0
            },
            splitLine: {
                show: !config.isHistoryChart, // Show day boundaries for regular charts
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
        yAxis: {
            type: 'value',
            name: config.yAxisName || '¢/kWh',
            nameLocation: 'end',
            nameGap: 20,
            max: config.yAxisMax || (value => Math.ceil(value.max / 10) * 10),
            nameTextStyle: {
                fontWeight: 'regular'
            },
            axisLabel: {
                formatter: function(value) {
                    return value.toFixed(0);
                }
            }
        },
        visualMap: config.visualMap || [],
        series: config.series || []
    };

    // History chart gets week-based grid
    if (config.isHistoryChart) {
        baseOptions.xAxis.splitLine = {
            show: true,
            lineStyle: {
                color: 'silver',
                width: 0.5,
                type: 'dashed',
                opacity: 0.40
            },
            interval: function(index, value) {
                const date = new Date(value);
                return date.getDay() === 1; // Monday
            }
        };
    }

    return baseOptions;
}

//#region markers
// ==========================================================================
// Chart update and marker position utilities
// ==========================================================================

function updateMarkerPosition(chart) {
    var currentTime = new Date().getTime();
    var option = chart.getOption();

    if (!option || !option.series) {
        return;
    }
    
    option.series.forEach((series) => {
        if (series.markLine) {
            series.markLine.data = [{ xAxis: currentTime }];
        }
    });
    
    chart.setOption(option, false, false);
}

//#region narration
