if (window.location.hostname === "nordpool-predict-fi.web.app") {
    window.location.href = "https://sahkovatkain.web.app" + window.location.pathname + window.location.search;
}

//#region conf
// ==========================================================================
// Base configuration and environment detection
// ==========================================================================

// Determine base URL based on hosting environment
var baseUrl = window.location.origin;

const THEME_SERVICE_READY_EVENT = 'np-theme-service-ready';

function getThemeService() {
    return window.themeService || window.__NP_THEME__ || null;
}

function onThemeServiceReady(callback) {
    if (typeof callback !== 'function') {
        return;
    }
    const existing = getThemeService();
    if (existing) {
        callback(existing);
        return;
    }
    if (typeof window === 'undefined' || typeof window.addEventListener !== 'function') {
        return;
    }
    const handler = () => {
        window.removeEventListener(THEME_SERVICE_READY_EVENT, handler);
        callback(getThemeService());
    };
    window.addEventListener(THEME_SERVICE_READY_EVENT, handler);
}

function resolveChartPalette(scope) {
    const service = getThemeService();
    if (service && typeof service.getPalette === 'function') {
        return service.getPalette(scope);
    }
    return null;
}

function subscribeThemePalette(scope, handler) {
    if (typeof handler !== 'function') {
        return () => {};
    }
    const service = getThemeService();
    if (!service) {
        return () => {};
    }
    if (typeof service.watchThemePalette === 'function') {
        return service.watchThemePalette(scope, handler);
    }
    if (typeof service.subscribe === 'function') {
        const invoke = () => handler(resolveChartPalette(scope));
        let initialEmitted = false;
        const unsubscribe = service.subscribe(() => {
            initialEmitted = true;
            invoke();
        });
        if (!initialEmitted) {
            invoke();
        }
        return () => {
            if (typeof unsubscribe === 'function') {
                unsubscribe();
            }
        };
    }
    return () => {};
}

window.resolveChartPalette = resolveChartPalette;
window.subscribeThemePalette = subscribeThemePalette;

function updateGithubLogo(effectiveMode) {
    const logo = document.getElementById('github-logo');
    if (!logo) {
        return;
    }
    const lightSrc = logo.dataset.lightSrc || logo.getAttribute('src');
    const darkSrc = logo.dataset.darkSrc || lightSrc;
    const targetSrc = effectiveMode === 'dark' ? darkSrc : lightSrc;
    if (!targetSrc || logo.dataset.activeSrc === targetSrc) {
        return;
    }
    logo.setAttribute('src', targetSrc);
    logo.dataset.activeSrc = targetSrc;
}

let githubLogoWatcherInitialized = false;

function initGithubLogoWatcher() {
    if (githubLogoWatcherInitialized) {
        return;
    }
    const service = getThemeService();
    if (!service) {
        updateGithubLogo(null);
        onThemeServiceReady(() => initGithubLogoWatcher());
        return;
    }
    githubLogoWatcherInitialized = true;
    const initialMode = typeof service.getEffectiveMode === 'function'
        ? service.getEffectiveMode()
        : null;
    updateGithubLogo(initialMode);
    if (typeof service.subscribe === 'function') {
        service.subscribe(payload => {
            if (payload && typeof payload.effectiveMode !== 'undefined') {
                updateGithubLogo(payload.effectiveMode);
            }
        });
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initGithubLogoWatcher, { once: true });
} else {
    initGithubLogoWatcher();
}

const DEFAULT_CHART_PALETTE = Object.freeze({
    axis: '#666666',
    grid: 'silver',
    tooltipBg: '#ffffff',
    tooltipText: 'rgba(51, 51, 51, 0.9)',
    tooltipBorder: 'rgba(31, 35, 40, 0.12)',
    legendText: '#666666',
    markLineLabel: 'Black',
    markLineLine: 'rgba(51, 51, 51, 0.9)',
    chartBackground: 'transparent'
});

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
const HELSINKI_TIMEZONE = 'Europe/Helsinki';
const HELSINKI_DATE_FORMATTER = new Intl.DateTimeFormat('en-CA', {
    timeZone: HELSINKI_TIMEZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
});
const HELSINKI_OFFSET_FORMATTER = new Intl.DateTimeFormat('en-US', {
    timeZone: HELSINKI_TIMEZONE,
    timeZoneName: 'shortOffset'
});
const MS_PER_MINUTE = 60 * 1000;

function getHelsinkiDateParts(referenceDate = new Date()) {
    const parts = HELSINKI_DATE_FORMATTER.formatToParts(referenceDate);
    const map = {};
    parts.forEach(part => {
        if (part.type === 'year' || part.type === 'month' || part.type === 'day') {
            map[part.type] = Number(part.value);
        }
    });
    const year = Number.isFinite(map.year) ? map.year : referenceDate.getUTCFullYear();
    const month = Number.isFinite(map.month) ? map.month : (referenceDate.getUTCMonth() + 1);
    const day = Number.isFinite(map.day) ? map.day : referenceDate.getUTCDate();
    return { year, month, day };
}

function getHelsinkiOffsetMs(timestamp) {
    try {
        const parts = HELSINKI_OFFSET_FORMATTER.formatToParts(new Date(timestamp));
        const zonePart = parts.find(part => part.type === 'timeZoneName');
        if (!zonePart) {
            return 0;
        }
        const match = zonePart.value.match(/(GMT|UTC)([+-])(\d{1,2})(?::(\d{2}))?/i);
        if (!match) {
            return 0;
        }
        const sign = match[2] === '-' ? -1 : 1;
        const hours = Number(match[3]) || 0;
        const minutes = Number(match[4] || '0');
        const totalMinutes = (hours * 60) + minutes;
        return sign * totalMinutes * MS_PER_MINUTE;
    } catch (error) {
        console.warn('Failed to compute Helsinki offset', error);
        return 0;
    }
}

function getHelsinkiMidnightDate(daysOffset = 0, referenceDate = new Date()) {
    const offset = Number.isFinite(daysOffset) ? daysOffset : 0;
    const { year, month, day } = getHelsinkiDateParts(referenceDate);
    const naiveUtc = Date.UTC(year, month - 1, day + offset);
    const timezoneShift = getHelsinkiOffsetMs(naiveUtc);
    return new Date(naiveUtc - timezoneShift);
}

function getHelsinkiMidnightISOString(daysOffset = 0, referenceDate = new Date()) {
    return getHelsinkiMidnightDate(daysOffset, referenceDate).toISOString();
}

function getHelsinkiMidnightTimestamp(daysOffset = 0, referenceDate = new Date()) {
    return getHelsinkiMidnightDate(daysOffset, referenceDate).getTime();
}

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
window.HELSINKI_TIMEZONE = HELSINKI_TIMEZONE;
window.getHelsinkiMidnightISOString = getHelsinkiMidnightISOString;
window.getHelsinkiMidnightTimestamp = getHelsinkiMidnightTimestamp;
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

let themeSwitchInitialized = false;

function initializeThemeSwitch() {
    if (themeSwitchInitialized) {
        return;
    }
    const service = getThemeService();
    if (!service) {
        onThemeServiceReady(() => initializeThemeSwitch());
        return;
    }
    themeSwitchInitialized = true;
    const buttons = document.querySelectorAll('[data-theme-option]');
    if (!buttons.length) {
        return;
    }

    function syncButtons(mode, effectiveMode = 'light') {
        const activeMode = mode === 'auto'
            ? (effectiveMode === 'dark' ? 'dark' : 'light')
            : mode;
        buttons.forEach(button => {
            const option = button.getAttribute('data-theme-option');
            const isActive = option === activeMode;
            button.setAttribute('aria-pressed', String(isActive));
            button.classList.toggle('is-active', isActive);
        });
    }

    const currentMode = typeof service.getMode === 'function'
        ? service.getMode()
        : 'auto';
    const currentEffective = typeof service.getEffectiveMode === 'function'
        ? service.getEffectiveMode()
        : 'light';
    syncButtons(currentMode, currentEffective);

    function activateOption(option) {
        if (!option || typeof service.setMode !== 'function') {
            return;
        }
        service.setMode(option);
    }

    buttons.forEach(button => {
        button.addEventListener('click', () => {
            const option = button.getAttribute('data-theme-option');
            activateOption(option);
        });

        button.addEventListener('keydown', event => {
            if (event.key !== 'Enter' && event.key !== ' ') {
                return;
            }
            event.preventDefault();
            const option = button.getAttribute('data-theme-option');
            activateOption(option);
        });
    });

    if (typeof service.subscribe === 'function') {
        service.subscribe(payload => {
            syncButtons(payload.mode, payload.effectiveMode);
        });
    }
}

document.addEventListener('DOMContentLoaded', initializeThemeSwitch);

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

function createCurrentTimeMarkLine(palette) {
    const labelColor = palette?.markLineLabel || 'Black';
    const lineColor = palette?.markLineLine || 'rgba(51, 51, 51, 0.9)';
    return {
        symbol: 'none',
        label: {
            formatter: formatCurrentTimeLabel,
            position: 'end',
            color: labelColor,
            fontSize: 11
        },
        lineStyle: {
            type: 'dotted',
            color: lineColor,
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
    const palette = Object.assign({}, DEFAULT_CHART_PALETTE, config.palette || {});
    const baseOptions = {
        title: { text: ' ' },
        legend: config.legend || { show: false },
        tooltip: {
            trigger: 'axis',
            formatter: config.tooltipFormatter || createTooltipFormatter(),
            backgroundColor: palette.tooltipBg,
            borderColor: palette.tooltipBorder,
            textStyle: {
                color: palette.tooltipText
            }
        },
        grid,
        backgroundColor: palette.chartBackground,
        xAxis: {
            type: 'time',
            boundaryGap: false,
            axisLabel: {
                interval: 0,
                formatter: config.xAxisFormatter || createXAxisFormatter(),
                color: palette.axis
            },
            axisLine: {
                lineStyle: {
                    color: palette.axis
                }
            },
            axisTick: {
                alignWithLabel: true,
                interval: 0
            },
            splitLine: {
                show: !config.isHistoryChart, // Show day boundaries for regular charts
                lineStyle: {
                    color: palette.grid,
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
                },
                color: palette.axis
            },
            axisLine: {
                lineStyle: {
                    color: palette.axis
                }
            },
            splitLine: {
                lineStyle: {
                    color: palette.grid
                }
            }
        },
        visualMap: config.visualMap || [],
        series: config.series || []
    };

    if (baseOptions.legend) {
        if (Array.isArray(baseOptions.legend)) {
            baseOptions.legend = baseOptions.legend.map(entry => Object.assign({}, entry, {
                textStyle: Object.assign({}, entry.textStyle, { color: palette.legendText })
            }));
        } else {
            baseOptions.legend = Object.assign({}, baseOptions.legend, {
                textStyle: Object.assign({}, baseOptions.legend.textStyle, { color: palette.legendText })
            });
        }
    }

    // History chart gets week-based grid
    if (config.isHistoryChart) {
        baseOptions.xAxis.splitLine = {
            show: true,
            lineStyle: {
                color: palette.grid,
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

function applyChartTheme(chart, palette) {
    if (!chart || typeof chart.getOption !== 'function' || typeof chart.setOption !== 'function') {
        return;
    }
    const option = chart.getOption();
    if (!option || typeof option !== 'object') {
        return;
    }
    const resolved = Object.assign({}, DEFAULT_CHART_PALETTE, palette || {});
    const xAxisCount = Array.isArray(option.xAxis) ? option.xAxis.length : (option.xAxis ? 1 : 0);
    const yAxisCount = Array.isArray(option.yAxis) ? option.yAxis.length : (option.yAxis ? 1 : 0);

    const axisTemplate = () => ({
        axisLabel: { color: resolved.axis },
        axisLine: { lineStyle: { color: resolved.axis } },
        splitLine: { lineStyle: { color: resolved.grid } }
    });

    const buildAxis = (count) => {
        if (count === 0) {
            return undefined;
        }
        if (count === 1) {
            return axisTemplate();
        }
        return Array.from({ length: count }, () => axisTemplate());
    };

    chart.setOption({
        backgroundColor: resolved.chartBackground,
        xAxis: buildAxis(xAxisCount),
        yAxis: buildAxis(yAxisCount),
        tooltip: {
            backgroundColor: resolved.tooltipBg,
            borderColor: resolved.tooltipBorder,
            textStyle: { color: resolved.tooltipText }
        },
        legend: {
            textStyle: { color: resolved.legendText }
        }
    }, false, true);
}

window.applyChartTheme = applyChartTheme;

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
