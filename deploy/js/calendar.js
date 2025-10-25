// #region calendar
// ==========================================================================
// Hourly price calendar heatmap
// ==========================================================================

(function() {
    const HOUR_MS = 60 * 60 * 1000;
    const HOURS_PER_DAY = 24;
    const DAYS_VISIBLE = 7;
    const HELSINKI_TZ = 'Europe/Helsinki';

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

    function zonedTimeToUtc(components, timeZone) {
        const { year, month, day, hour = 0, minute = 0, second = 0 } = components;
        if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) {
            return NaN;
        }
        const guess = new Date(Date.UTC(year, month - 1, day, hour, minute, second));
        const local = getLocalDateParts(guess.getTime(), timeZone);
        const adjusted = Date.UTC(
            Number.isFinite(local.year) ? local.year : year,
            Number.isFinite(local.month) ? local.month - 1 : month - 1,
            Number.isFinite(local.day) ? local.day : day,
            Number.isFinite(local.hour) ? local.hour : hour,
            Number.isFinite(local.minute) ? local.minute : minute,
            Number.isFinite(local.second) ? local.second : second
        );
        const offset = adjusted - guess.getTime();
        return guess.getTime() - offset;
    }

    function padHour(hour) {
        const numeric = Number(hour);
        if (!Number.isFinite(numeric)) {
            return '';
        }
        return numeric < 10 ? `0${numeric}` : String(numeric);
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

    function formatDayLabel(timestamp, locale) {
        const formatter = new Intl.DateTimeFormat(locale, {
            weekday: 'short',
            month: 'short',
            day: 'numeric',
            timeZone: HELSINKI_TZ
        });
        return formatter.format(new Date(timestamp));
    }

    function formatTooltip(timestamp, price, locale) {
        const formatter = new Intl.DateTimeFormat(locale, {
            weekday: 'long',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
            timeZone: HELSINKI_TZ
        });
        const stamp = formatter.format(new Date(timestamp));
        const rounded = Number(price).toFixed(1);
        return `${stamp}<br/>${rounded} ¢/kWh`;
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
        const hourLabels = Array.from({ length: HOURS_PER_DAY }, (_, hour) => padHour(hour));
        const data = [];
        const dayLabels = [];

        const baseDate = new Date(Date.UTC(anchorParts.year, anchorParts.month - 1, anchorParts.day));

        for (let dayOffset = 0; dayOffset < DAYS_VISIBLE; dayOffset++) {
            const dayCandidate = new Date(baseDate);
            dayCandidate.setUTCDate(baseDate.getUTCDate() + dayOffset);

            const year = dayCandidate.getUTCFullYear();
            const month = dayCandidate.getUTCMonth() + 1;
            const day = dayCandidate.getUTCDate();

            const dayStart = zonedTimeToUtc({ year, month, day, hour: 0 }, HELSINKI_TZ);
            dayLabels.push(formatDayLabel(dayStart, locale));

            for (let hour = 0; hour < HOURS_PER_DAY; hour++) {
                const slotTs = zonedTimeToUtc({ year, month, day, hour }, HELSINKI_TZ);
                const aligned = Math.floor(slotTs / HOUR_MS) * HOUR_MS;
                const isPastHour = aligned < anchorMs;
                const price = !isPastHour ? selectPrice(aligned, sources) : null;
                const normalized = Number.isFinite(price) ? Number(price) : null;
                data.push([hour, dayOffset, normalized, aligned]);
            }
        }

        return {
            locale,
            hourLabels,
            dayLabels,
            data
        };
    }

    function buildChartOption(matrix) {
        const fallbackColor = 'rgba(31, 35, 40, 0.12)';
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
                    if (!Number.isFinite(price) || !Number.isFinite(ts)) {
                        return '';
                    }
                    return formatTooltip(ts, price, matrix.locale);
                }
            },
            xAxis: {
                type: 'category',
                data: matrix.hourLabels,
                boundaryGap: false,
                axisLine: {
                    lineStyle: {
                        color: 'rgba(31, 35, 40, 0.18)'
                    }
                },
                axisTick: { show: false },
                axisLabel: {
                    interval: 1,
                    color: 'rgba(31, 35, 40, 0.72)'
                }
            },
            yAxis: {
                type: 'category',
                data: matrix.dayLabels,
                inverse: true,
                axisLine: { show: false },
                axisTick: { show: false },
                axisLabel: {
                    color: 'rgba(31, 35, 40, 0.72)',
                    margin: 22
                },
                splitLine: {
                    show: true,
                    lineStyle: {
                        color: 'rgba(31, 35, 40, 0.08)'
                    }
                }
            },
            series: [
                {
                    type: 'heatmap',
                    data: matrix.data,
                    itemStyle: {
                        borderColor: 'rgba(255, 255, 255, 0.65)',
                        borderWidth: 1,
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
                            borderColor: 'rgba(31, 35, 40, 0.66)',
                            borderWidth: 1.4
                        }
                    }
                }
            ]
        };
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
