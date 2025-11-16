// #region calendar
// ==========================================================================
// Hourly price calendar heatmap
// ==========================================================================

(function() {
    const HOUR_MS = 60 * 60 * 1000;
    const DAY_MS = 24 * HOUR_MS;
    const MAX_DAY_SLOTS = 27;
    const HELSINKI_TZ = 'Europe/Helsinki';
    let calendarChartInstance = null;
    let calendarPalette = typeof getChartPalette === 'function'
        ? getChartPalette('calendar')
        : null;

    const dtfCache = new Map();

    function getDateTimeFormatter(timeZone) {
        if (!dtfCache.has(timeZone)) {
            dtfCache.set(timeZone, new Intl.DateTimeFormat('en-US', {
                timeZone,
                hour12: false,
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            }));
        }
        return dtfCache.get(timeZone);
    }

    function getLocalDateParts(timestamp, timeZone) {
        const formatter = getDateTimeFormatter(timeZone);
        const parts = formatter.formatToParts(new Date(timestamp));
        const bucket = {};
        for (const part of parts) {
            if (part.type !== 'literal') {
                bucket[part.type] = part.value;
            }
        }
        return {
            year: Number(bucket.year),
            month: Number(bucket.month),
            day: Number(bucket.day),
            hour: Number(bucket.hour),
            minute: Number(bucket.minute),
            second: Number(bucket.second)
        };
    }

    function matchesLocal(parts, target) {
        return (
            Number.isFinite(parts.year) && parts.year === target.year &&
            Number.isFinite(parts.month) && parts.month === target.month &&
            Number.isFinite(parts.day) && parts.day === target.day &&
            Number.isFinite(parts.hour) && parts.hour === target.hour &&
            Number.isFinite(parts.minute) && parts.minute === target.minute &&
            Number.isFinite(parts.second) && parts.second === target.second
        );
    }

    function zonedTimeToUtc(components, timeZone) {
        const {
            year,
            month,
            day,
            hour = 0,
            minute = 0,
            second = 0
        } = components;

        if (![year, month, day, hour, minute, second].every(Number.isFinite)) {
            return NaN;
        }

        const naiveUtc = Date.UTC(year, month - 1, day, hour, minute, second);
        const localParts = getLocalDateParts(naiveUtc, timeZone);
        const localUtcEstimate = Date.UTC(
            Number.isFinite(localParts.year) ? localParts.year : year,
            Number.isFinite(localParts.month) ? localParts.month - 1 : month - 1,
            Number.isFinite(localParts.day) ? localParts.day : day,
            Number.isFinite(localParts.hour) ? localParts.hour : hour,
            Number.isFinite(localParts.minute) ? localParts.minute : minute,
            Number.isFinite(localParts.second) ? localParts.second : second
        );

        let candidate = naiveUtc + (naiveUtc - localUtcEstimate);
        let resolvedParts = getLocalDateParts(candidate, timeZone);

        if (matchesLocal(resolvedParts, { year, month, day, hour, minute, second })) {
            return candidate;
        }

        const adjustments = [-HOUR_MS, HOUR_MS, -2 * HOUR_MS, 2 * HOUR_MS];
        for (const delta of adjustments) {
            const attempt = candidate + delta;
            resolvedParts = getLocalDateParts(attempt, timeZone);
            if (matchesLocal(resolvedParts, { year, month, day, hour, minute, second })) {
                return attempt;
            }
        }

        return NaN;
    }

    function padHour(hour) {
        const numeric = Number(hour);
        if (!Number.isFinite(numeric)) {
            return '';
        }
        return numeric < 10 ? `0${numeric}` : String(numeric);
    }

    function formatWithColonSeparator(formatter, date) {
        if (!formatter || typeof formatter.formatToParts !== 'function') {
            return typeof formatter?.format === 'function' ? formatter.format(date) : '';
        }
        const parts = formatter.formatToParts(date);
        let result = '';
        let awaitingMinute = false;

        for (let index = 0; index < parts.length; index++) {
            const part = parts[index];
            if (part.type === 'hour') {
                awaitingMinute = true;
                result += part.value;
                continue;
            }
            if (part.type === 'literal' && awaitingMinute) {
                const next = parts[index + 1];
                if (next && next.type === 'minute') {
                    result += ':';
                    continue;
                }
            }
            result += part.value;
            if (part.type === 'minute') {
                awaitingMinute = false;
            }
        }

        return result;
    }

    function buildPriceMap(series) {
        const map = new Map();
        if (!Array.isArray(series)) {
            return map;
        }
        series.forEach(item => {
            if (!Array.isArray(item) || item.length < 2) {
                return;
            }
            const ts = Number(item[0]);
            const value = Number(item[1]);
            if (!Number.isFinite(ts) || !Number.isFinite(value)) {
                return;
            }
            const aligned = Math.floor(ts / HOUR_MS) * HOUR_MS;
            if (!map.has(aligned)) {
                map.set(aligned, value);
            }
        });
        return map;
    }

    function buildPriceSources(payload) {
        return {
            merged: buildPriceMap(payload?.mergedSeries),
            actual: buildPriceMap(payload?.sahkotinSeries),
            forecast: buildPriceMap(payload?.forecastSeries)
        };
    }

    function getLatestTimestamp(sources) {
        if (!sources) {
            return NaN;
        }
        const pools = [sources.merged, sources.actual, sources.forecast];
        let latest = NaN;
        pools.forEach(pool => {
            if (!(pool instanceof Map)) {
                return;
            }
            for (const key of pool.keys()) {
                const numericKey = Number(key);
                if (!Number.isFinite(numericKey)) {
                    continue;
                }
                if (!Number.isFinite(latest) || numericKey > latest) {
                    latest = numericKey;
                }
            }
        });
        return latest;
    }

    function selectPrice(timestamp, sources) {
        if (sources.merged.has(timestamp)) {
            return sources.merged.get(timestamp);
        }
        if (sources.actual.has(timestamp)) {
            return sources.actual.get(timestamp);
        }
        if (sources.forecast.has(timestamp)) {
            return sources.forecast.get(timestamp);
        }
        return null;
    }

    function determineDaysVisible(anchorParts, sources) {
        if (!anchorParts || !Number.isFinite(anchorParts.year)) {
            return 0;
        }

        const baseDayUtc = zonedTimeToUtc({
            year: anchorParts.year,
            month: anchorParts.month,
            day: anchorParts.day,
            hour: 0,
            minute: 0,
            second: 0
        }, HELSINKI_TZ);

        if (!Number.isFinite(baseDayUtc)) {
            return 0;
        }

        const latestTimestamp = getLatestTimestamp(sources);
        if (!Number.isFinite(latestTimestamp)) {
            return 0;
        }

        const alignedLatest = Math.floor(latestTimestamp / HOUR_MS) * HOUR_MS;
        const latestParts = getLocalDateParts(alignedLatest, HELSINKI_TZ);
        if (!Number.isFinite(latestParts?.year)) {
            return 0;
        }

        const lastDayUtc = zonedTimeToUtc({
            year: latestParts.year,
            month: latestParts.month,
            day: latestParts.day,
            hour: 0,
            minute: 0,
            second: 0
        }, HELSINKI_TZ);

        if (!Number.isFinite(lastDayUtc)) {
            return 0;
        }

        if (lastDayUtc < baseDayUtc) {
            return 1;
        }

        const diff = Math.round((lastDayUtc - baseDayUtc) / DAY_MS);
        if (!Number.isFinite(diff)) {
            return 0;
        }

        return diff + 1;
    }

    function formatDayLabel(timestamp, locale) {
        const formatter = new Intl.DateTimeFormat(locale, {
            weekday: 'short',
            month: 'short',
            day: 'numeric',
            timeZone: HELSINKI_TZ
        });
        return formatter.format(new Date(timestamp));
    }

    function formatTooltip(timestamp, price, locale, detail) {
        const formatter = new Intl.DateTimeFormat(locale, {
            weekday: 'long',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
            timeZone: HELSINKI_TZ
        });
        const stamp = formatWithColonSeparator(formatter, new Date(timestamp));
        const rounded = Number(price).toFixed(1);
        let tooltip = `${stamp}<br/>${rounded} ¢/kWh`;

        if (Array.isArray(detail) && detail.length > 1) {
            const tzNameFormatter = new Intl.DateTimeFormat(locale, {
                hour: '2-digit',
                minute: '2-digit',
                hour12: false,
                timeZone: HELSINKI_TZ,
                timeZoneName: 'short'
            });

            detail
                .slice()
                .sort((a, b) => a.timestamp - b.timestamp)
                .forEach(entry => {
                    if (!Number.isFinite(entry.timestamp) || !Number.isFinite(entry.price)) {
                        return;
                    }
                    if (entry.timestamp === timestamp) {
                        return;
                    }
                    const label = formatWithColonSeparator(
                        tzNameFormatter,
                        new Date(entry.timestamp)
                    );
                    tooltip += `<br/>${label}: ${Number(entry.price).toFixed(1)} ¢/kWh`;
                });
        }

        return tooltip;
    }

    function formatLegendLabel(band, locale) {
        if (!band) {
            return '';
        }
        const numberFormatter = new Intl.NumberFormat(locale, {
            minimumFractionDigits: 0,
            maximumFractionDigits: 1
        });
        const minFinite = Number.isFinite(band.min) ? band.min : null;
        const maxFinite = Number.isFinite(band.max) ? band.max : null;
        const unit = '¢/kWh';

        if (minFinite === null && maxFinite === null) {
            return '';
        }

        if (minFinite === null && maxFinite !== null) {
            return `≤ ${numberFormatter.format(maxFinite)} ${unit}`;
        }

        if (minFinite !== null && maxFinite === null) {
            return `> ${numberFormatter.format(minFinite)} ${unit}`;
        }

        return `${numberFormatter.format(minFinite)} – ${numberFormatter.format(maxFinite)} ${unit}`;
    }

    function renderLegend(container, locale) {
        if (!container) {
            return;
        }
        const bands = Array.isArray(window.SAHKOTIN_PRICE_BANDS) ? window.SAHKOTIN_PRICE_BANDS : [];
        if (!bands.length) {
            container.textContent = '';
            container.style.display = 'none';
            return;
        }

        const localeTag = locale === 'fi' ? 'fi-FI' : 'en-GB';
        const fragment = document.createDocumentFragment();
        bands.forEach(band => {
            const label = formatLegendLabel(band, localeTag);
            if (!label) {
                return;
            }
            const item = document.createElement('span');
            item.className = 'price-calendar-legend-item';

            const swatch = document.createElement('span');
            swatch.className = 'price-calendar-legend-swatch';
            swatch.style.backgroundColor = band.color;

            const text = document.createElement('span');
            text.textContent = label;

            item.appendChild(swatch);
            item.appendChild(text);
            fragment.appendChild(item);
        });

        container.textContent = '';
        container.appendChild(fragment);
        container.style.display = 'flex';
    }

    function collectDaySlots(year, month, day, timeZone) {
        const dayStartUtc = zonedTimeToUtc({ year, month, day, hour: 0 }, timeZone);
        if (!Number.isFinite(dayStartUtc)) {
            return { slotsByHour: new Map(), dayStartUtc: NaN };
        }

        const slotsByHour = new Map();
        let cursor = dayStartUtc;

        for (let index = 0; index < MAX_DAY_SLOTS; index++) {
            const parts = getLocalDateParts(cursor, timeZone);
            if (!Number.isFinite(parts.year) || parts.year !== year ||
                !Number.isFinite(parts.month) || parts.month !== month ||
                !Number.isFinite(parts.day) || parts.day !== day) {
                break;
            }

            const hour = parts.hour;
            if (!slotsByHour.has(hour)) {
                slotsByHour.set(hour, []);
            }
            slotsByHour.get(hour).push({
                timestamp: cursor
            });
            cursor += HOUR_MS;
        }

        return { slotsByHour, dayStartUtc };
    }

    function buildCalendarMatrix(payload) {
        if (!payload) {
            return null;
        }

        const sources = buildPriceSources(payload);
        const nowMs = Date.now();
        const anchorMs = Math.floor(nowMs / HOUR_MS) * HOUR_MS;
        const anchorParts = getLocalDateParts(anchorMs, HELSINKI_TZ);
        if (!Number.isFinite(anchorParts?.year)) {
            return null;
        }

        const locale = window.location.pathname.includes('index_en') ? 'en-GB' : 'fi-FI';
        const hourLabels = Array.from({ length: 24 }, (_, hour) => padHour(hour));
        const data = [];
        const dayLabels = [];
        const daysVisible = determineDaysVisible(anchorParts, sources);
        if (daysVisible <= 0) {
            return null;
        }

        const baseDate = new Date(Date.UTC(anchorParts.year, anchorParts.month - 1, anchorParts.day));

        for (let dayOffset = 0; dayOffset < daysVisible; dayOffset++) {
            const dayCandidate = new Date(baseDate);
            dayCandidate.setUTCDate(baseDate.getUTCDate() + dayOffset);

            const year = dayCandidate.getUTCFullYear();
            const month = dayCandidate.getUTCMonth() + 1;
            const day = dayCandidate.getUTCDate();

            const { slotsByHour, dayStartUtc } = collectDaySlots(year, month, day, HELSINKI_TZ);
            const labelTimestamp = Number.isFinite(dayStartUtc)
                ? dayStartUtc
                : Date.UTC(year, month - 1, day);
            dayLabels.push(formatDayLabel(labelTimestamp, locale));

            hourLabels.forEach((label, xIndex) => {
                const hour = Number.parseInt(label, 10);
                const occurrences = Number.isFinite(hour) ? (slotsByHour.get(hour) || []) : [];

                const enriched = occurrences.map(entry => {
                    const aligned = Math.floor(entry.timestamp / HOUR_MS) * HOUR_MS;
                    return {
                        timestamp: entry.timestamp,
                        price: selectPrice(aligned, sources)
                    };
                }).filter(entry => Number.isFinite(entry.price));

                const primary = enriched.length ? enriched[enriched.length - 1] : enriched[0];
                const timestamp = primary ? primary.timestamp : occurrences[0]?.timestamp ?? NaN;
                const aligned = Number.isFinite(timestamp) ? Math.floor(timestamp / HOUR_MS) * HOUR_MS : NaN;
                const isPastHour = Number.isFinite(aligned) && aligned < anchorMs;
                const price = !isPastHour && primary ? primary.price : null;
                const normalized = Number.isFinite(price) ? Number(price) : null;
                const detail = enriched.length > 1 ? enriched : null;

                data.push([
                    xIndex,
                    dayOffset,
                    normalized,
                    Number.isFinite(timestamp) ? timestamp : NaN,
                    detail
                ]);
            });
        }

        return {
            locale,
            hourLabels,
            dayLabels,
            data
        };
    }

    function buildChartOption(matrix) {
        const palette = calendarPalette || {};
        const fallbackColor = palette.fallback || 'rgba(31, 35, 40, 0.12)';
        const axisColor = palette.axis || 'rgba(31, 35, 40, 0.72)';
        const borderColor = palette.border || 'rgba(255, 255, 255, 1)';
        const emphasisColor = palette.emphasis || 'dodgerblue';
        return {
            animation: false,
            grid: {
                top: 12,
                left: 16,
                right: 20,
                bottom: 28,
                containLabel: true
            },
            tooltip: {
                trigger: 'item',
                formatter: function(params) {
                    const payload = params?.data;
                    if (!Array.isArray(payload) || payload.length < 4) {
                        return '';
                    }
                    const price = payload[2];
                    const ts = payload[3];
                    const detail = payload[4];
                    if (!Number.isFinite(price) || !Number.isFinite(ts)) {
                        return '';
                    }
                    return formatTooltip(ts, price, matrix.locale, detail);
                }
            },
            xAxis: {
                type: 'category',
                data: matrix.hourLabels,
                boundaryGap: false,
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: {
                    interval: 1,
                    color: axisColor
                }
            },
            yAxis: {
                type: 'category',
                data: matrix.dayLabels,
                inverse: true,
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: {
                    color: axisColor,
                    margin: 32
                },
                splitLine: {
                    show: false
                }
            },
            series: [
                {
                    id: 'price-calendar-heatmap',
                    type: 'heatmap',
                    data: matrix.data,
                    itemStyle: {
                        borderColor: borderColor,
                        borderWidth: 2,
                        color: function(args) {
                            const payload = args?.data;
                            if (!Array.isArray(payload)) {
                                return 'rgba(0,0,0,0)';
                            }
                            const price = payload[2];
                            if (!Number.isFinite(price)) {
                                return 'rgba(255,255,255,0)';
                            }
                            if (typeof getSahkotinPriceColor === 'function') {
                                return getSahkotinPriceColor(price, fallbackColor);
                            }
                            return fallbackColor;
                        }
                    },
                    emphasis: {
                        itemStyle: {
                            borderColor: emphasisColor,
                            borderWidth: 2.8
                        }
                    }
                }
            ]
        };
    }

    function applyCalendarThemeToChart() {
        if (!calendarChartInstance || !calendarPalette) {
            return;
        }
        calendarChartInstance.setOption({
            xAxis: {
                axisLabel: {
                    color: calendarPalette.axis
                }
            },
            yAxis: {
                axisLabel: {
                    color: calendarPalette.axis
                }
            },
            series: [
                {
                    id: 'price-calendar-heatmap',
                    itemStyle: {
                        borderColor: calendarPalette.border
                    },
                    emphasis: {
                        itemStyle: {
                            borderColor: calendarPalette.emphasis
                        }
                    }
                }
            ]
        }, false, true);
    }

    if (typeof watchThemePalette === 'function') {
        watchThemePalette('calendar', palette => {
            calendarPalette = palette || calendarPalette;
            applyCalendarThemeToChart();
        });
    }

    function hasValues(matrix) {
        if (!matrix?.data) {
            return false;
        }
        return matrix.data.some(cell => Number.isFinite(cell[2]));
    }

    function updateCalendar(chart, statusElement, payload) {
        if (!chart) {
            return;
        }

        const matrix = buildCalendarMatrix(payload);
        if (!matrix) {
            setStatus(statusElement, 'calendar_no_data');
            chart.clear();
            return;
        }

        if (!hasValues(matrix)) {
            setStatus(statusElement, 'calendar_no_data');
            chart.clear();
            return;
        }

        clearStatus(statusElement);
        chart.setOption(buildChartOption(matrix), true);
        applyCalendarThemeToChart();
    }

    function setStatus(element, key) {
        if (!element) {
            return;
        }
        const text = typeof getLocalizedText === 'function' ? getLocalizedText(key) : '';
        element.textContent = text || '';
        element.style.display = text ? 'block' : 'none';
    }

    function clearStatus(element) {
        if (!element) {
            return;
        }
        element.textContent = '';
        element.style.display = 'none';
    }

    document.addEventListener('DOMContentLoaded', function() {
        const container = document.getElementById('priceCalendar');
        if (!container || typeof echarts === 'undefined') {
            return;
        }

        const statusElement = document.getElementById('priceCalendarStatus');
        const chart = echarts.init(container);
        calendarChartInstance = chart;
        window.priceCalendarChart = chart;
        const legendContainer = document.getElementById('priceCalendarLegend');
        const localeKey = window.location.pathname.includes('index_en') ? 'en' : 'fi';

        setStatus(statusElement, 'calendar_loading');
        renderLegend(legendContainer, localeKey);

        function handlePayload(payload) {
            updateCalendar(chart, statusElement, payload);
        }

        if (window.latestPredictionData) {
            handlePayload(window.latestPredictionData);
        }

        window.addEventListener('prediction-data-ready', function(event) {
            handlePayload(event.detail);
        });

        window.addEventListener('resize', function() {
            chart.resize();
        });
    });
})();
