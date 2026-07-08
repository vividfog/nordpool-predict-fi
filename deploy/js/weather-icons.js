//#region weather_icons

(() => {
    const endpoint = window.DATA_ENDPOINTS?.weather || `${window.location.origin}/weather.json`;
    const predictionFullEndpoint = window.DATA_ENDPOINTS?.predictionFull || `${window.location.origin}/prediction_full.json`;
    const rail = document.getElementById('predictionWeather');
    const chart = window.nfpChart;
    const resolveWeatherPalette = typeof window.resolveChartPalette === 'function'
        ? window.resolveChartPalette
        : () => null;
    const subscribeWeatherPalette = typeof window.subscribeThemePalette === 'function'
        ? window.subscribeThemePalette
        : () => () => {};
    const tooltip = document.createElement('div');
    tooltip.id = 'npWeatherTooltip';
    tooltip.className = 'np-weather-tooltip';
    tooltip.setAttribute('role', 'tooltip');
    tooltip.setAttribute('aria-hidden', 'true');
    document.body.append(tooltip);
    const labels = {
        fi: {
            conditions: {
                'clear-day': 'selkeää',
                'partly-cloudy-day': 'puolipilvistä',
                'overcast-day': 'pilvistä',
                rain: 'sadetta',
                snow: 'lumisadetta',
                'thunderstorms-day': 'ukkosta'
            },
            wind: { calm: 'erittäin vähän tuulivoimaa', weak: 'vähän tuulivoimaa', normal: 'tavanomaisesti tuulivoimaa', strong: 'paljon tuulivoimaa' },
            tooltip: {
                weather: 'Yleissää',
                wind: 'Tuulivoimaennuste',
                temperatureAverage: 'Lämpötila, keskiarvo',
                price: 'Hinta',
                windPower: 'Tuulivoima',
                average: 'keskiarvo',
                range: 'min–max',
                windLevels: { calm: 'erittäin vähäinen', weak: 'vähäinen', normal: 'tavanomainen', strong: 'suuri' }
            }
        },
        en: {
            conditions: {
                'clear-day': 'clear',
                'partly-cloudy-day': 'partly cloudy',
                'overcast-day': 'cloudy',
                rain: 'rain',
                snow: 'snow',
                'thunderstorms-day': 'thunderstorms'
            },
            wind: { calm: 'very low wind-power outlook', weak: 'low wind-power outlook', normal: 'normal wind-power outlook', strong: 'high wind-power outlook' },
            tooltip: {
                weather: 'General weather',
                wind: 'Wind-power outlook',
                temperatureAverage: 'Temperature, average',
                price: 'Price',
                windPower: 'Wind power',
                average: 'average',
                range: 'min–max',
                windLevels: { calm: 'very low', weak: 'low', normal: 'normal', strong: 'high' }
            }
        }
    };
    let layoutFrame = null;
    let motionVisible = false;
    let motionObserver = null;
    let activeTooltipMark = null;
    let activeTooltipItem = null;
    let tooltipPinned = false;
    let dailySummaries = new Map();
    const motionQuery = typeof window.matchMedia === 'function'
        ? window.matchMedia('(prefers-reduced-motion: reduce)')
        : null;

    function locale() {
        return window.location.pathname.includes('index_en') ? 'en' : 'fi';
    }

    function createWeatherSvg(condition) {
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('class', 'np-weather-icon');
        svg.setAttribute('viewBox', '0 0 96 96');
        svg.setAttribute('aria-hidden', 'true');

        const sun = `
            <g class="np-weather-sun">
                <g class="np-weather-rays">
                    <path d="M34 8 V14 M34 50 V56 M10 32 H16 M52 32 H58 M17 15 L21 20 M47 45 L52 50 M17 49 L22 44 M47 19 L52 14"/>
                </g>
                <circle class="np-weather-sun-core" cx="34" cy="32" r="12"/>
            </g>`;
        const cloud = `
            <g class="np-weather-cloud">
                <path class="np-weather-cloud-front" d="M22 58 C22 50 29 44 38 45 C42 35 57 33 65 42 C76 41 84 48 83 58 C82 66 75 69 65 69 H38 C28 69 22 65 22 58Z"/>
            </g>`;
        const overcast = `
            <g class="np-weather-cloud">
                <path class="np-weather-cloud-back" d="M18 49 C18 42 24 37 31 38 C36 28 50 28 56 38 C65 37 72 43 71 51 C70 57 64 60 56 60 H31 C23 60 18 56 18 49Z"/>
                <path class="np-weather-cloud-front" d="M28 61 C28 53 35 47 44 48 C48 38 63 36 71 45 C82 44 90 51 89 61 C88 69 81 72 71 72 H44 C34 72 28 68 28 61Z"/>
            </g>`;
        const conditions = {
            'clear-day': `<g transform="translate(14 12)">${sun}</g>`,
            'partly-cloudy-day': `${sun}${cloud}`,
            'overcast-day': overcast,
            rain: `${cloud}<path class="np-weather-rain" d="M37 73 L34 82 M52 73 L49 84 M67 73 L64 82"/>`,
            snow: `${cloud}<circle class="np-weather-snow" cx="36" cy="78" r="2.5"/><circle class="np-weather-snow np-weather-delay-1" cx="51" cy="82" r="2.5"/><circle class="np-weather-snow np-weather-delay-2" cx="67" cy="77" r="2.5"/>`,
            'thunderstorms-day': `${cloud}<path class="np-weather-lightning" d="M50 68 L43 81 H51 L47 91 L61 76 H53 L59 68Z"/>`
        };
        svg.innerHTML = `
            <g class="np-weather-condition">${conditions[condition] || overcast}</g>
            <g class="np-windsock">
                <path class="np-windsock-pole" d="M80 9 V33"/>
                <g class="np-windsock-fabric-scale">
                    <g class="np-windsock-fabric">
                        <path class="np-windsock-body" d="M80 1 C92 1 106 4 120 7 L120 11 C106 11 92 15 80 17 Z"/>
                        <path class="np-windsock-stripe" d="M91 2.1 C93 2.4 95 2.7 97 3.2 L96.5 13 C94.5 13.4 92.5 13.8 90.5 14.2 Z"/>
                        <path class="np-windsock-stripe" d="M108 4.4 C110 4.9 112 5.4 114 5.9 L113.5 11.2 C111.5 11.3 109.5 11.5 107.5 11.7 Z"/>
                    </g>
                </g>
            </g>`;
        return svg;
    }

    function accessibleLabel(item) {
        const language = locale();
        const copy = labels[language];
        const date = new Intl.DateTimeFormat(language === 'fi' ? 'fi-FI' : 'en-GB', {
            weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Europe/Helsinki'
        }).format(new Date(item.timestamp));
        return `${date}: ${copy.conditions[item.condition]}, ${copy.wind[item.windLevel]}`;
    }

    function tooltipDate(item) {
        const language = locale();
        return new Intl.DateTimeFormat(language === 'fi' ? 'fi-FI' : 'en-GB', {
            weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Europe/Helsinki'
        }).format(new Date(item.timestamp));
    }

    function positionTooltip(mark) {
        const markRect = mark.getBoundingClientRect();
        const tooltipRect = tooltip.getBoundingClientRect();
        const viewportMargin = 8;
        const gap = 8;
        const maxLeft = Math.max(viewportMargin, window.innerWidth - tooltipRect.width - viewportMargin);
        const centeredLeft = markRect.left + (markRect.width - tooltipRect.width) / 2;
        let top = markRect.top - tooltipRect.height - gap;
        if (top < viewportMargin) top = markRect.bottom + gap;
        tooltip.style.left = `${Math.min(Math.max(centeredLeft, viewportMargin), maxLeft)}px`;
        tooltip.style.top = `${top}px`;
    }

    function finiteNumber(value) {
        if (value === null || value === undefined || value === '') return null;
        const numeric = Number(value);
        return Number.isFinite(numeric) ? numeric : null;
    }

    function addMetric(bin, metric, value) {
        if (!Number.isFinite(value)) return;
        const current = bin[metric] || { sum: 0, count: 0, min: value, max: value };
        current.sum += value;
        current.count += 1;
        current.min = Math.min(current.min, value);
        current.max = Math.max(current.max, value);
        bin[metric] = current;
    }

    function finishMetric(metric) {
        if (!metric?.count) return null;
        return {
            average: metric.sum / metric.count,
            min: metric.min,
            max: metric.max
        };
    }

    function buildDailySummaries(data) {
        if (!Array.isArray(data) || typeof window.getHelsinkiElectricityDayBoundary !== 'function') {
            return new Map();
        }
        const temperatureColumns = [...new Set(data.flatMap(row => (
            row && typeof row === 'object'
                ? Object.keys(row).filter(key => key.startsWith('t_'))
                : []
        )))];
        const bins = new Map();

        data.forEach(row => {
            const timestamp = new Date(row?.timestamp).getTime();
            const day = window.getHelsinkiElectricityDayBoundary(timestamp);
            if (!day) return;
            const bin = bins.get(day.key) || { key: day.key, start: day.start, end: day.end };
            const actualPrice = finiteNumber(row.Price_cpkWh);
            const predictedPrice = finiteNumber(row.PricePredict_cpkWh);
            addMetric(bin, 'price', actualPrice ?? predictedPrice);
            addMetric(bin, 'windPower', finiteNumber(row.WindPowerMW));

            const temperatures = temperatureColumns
                .map(column => finiteNumber(row[column]))
                .filter(Number.isFinite);
            if (temperatures.length) {
                addMetric(
                    bin,
                    'temperature',
                    temperatures.reduce((sum, value) => sum + value, 0) / temperatures.length
                );
            }
            bins.set(day.key, bin);
        });

        return new Map([...bins].map(([key, bin]) => [key, {
            key,
            start: bin.start,
            end: bin.end,
            price: finishMetric(bin.price),
            windPower: finishMetric(bin.windPower),
            temperature: finishMetric(bin.temperature)
        }]));
    }

    function formatNumber(value, fractionDigits) {
        return window.formatLocalizedNumber(value, {
            minimumFractionDigits: fractionDigits,
            maximumFractionDigits: fractionDigits
        });
    }

    function createDescriptionList(rows) {
        const list = document.createElement('dl');
        list.className = 'np-weather-tooltip-list';
        rows.forEach(([label, value]) => {
            const term = document.createElement('dt');
            term.textContent = label;
            const description = document.createElement('dd');
            description.textContent = value;
            list.append(term, description);
        });
        return list;
    }

    function createMetricSection(title, rows) {
        const section = document.createElement('section');
        section.className = 'np-weather-tooltip-section';
        const heading = document.createElement('strong');
        heading.textContent = title;
        section.append(heading, createDescriptionList(rows));
        return section;
    }

    function summaryFor(item) {
        const day = window.getHelsinkiElectricityDayBoundary?.(Number(item.timestamp));
        return day ? dailySummaries.get(day.key) : null;
    }

    function showTooltip(mark, item, pinned = false) {
        const language = locale();
        const copy = labels[language];
        const heading = document.createElement('strong');
        heading.textContent = tooltipDate(item);
        const summary = summaryFor(item);
        const contextRows = [[copy.tooltip.weather, copy.conditions[item.condition]]];
        if (summary?.temperature) {
            contextRows.push([
                copy.tooltip.temperatureAverage,
                `${formatNumber(summary.temperature.average, 1)} °C`
            ]);
        }
        contextRows.push([copy.tooltip.wind, copy.tooltip.windLevels[item.windLevel]]);
        const children = [heading, createDescriptionList(contextRows)];
        if (summary?.price) {
            children.push(createMetricSection(copy.tooltip.price, [
                [copy.tooltip.average, `${formatNumber(summary.price.average, 1)} ¢/kWh`],
                [copy.tooltip.range, `${formatNumber(summary.price.min, 1)}–${formatNumber(summary.price.max, 1)} ¢/kWh`]
            ]));
        }
        if (summary?.windPower) {
            children.push(createMetricSection(copy.tooltip.windPower, [
                [copy.tooltip.average, `${formatNumber(summary.windPower.average, 0)} MW`],
                [copy.tooltip.range, `${formatNumber(summary.windPower.min, 0)}–${formatNumber(summary.windPower.max, 0)} MW`]
            ]));
        }
        tooltip.replaceChildren(...children);
        tooltip.classList.add('is-visible');
        tooltip.setAttribute('aria-hidden', 'false');
        activeTooltipMark?.removeAttribute('aria-describedby');
        activeTooltipMark = mark;
        activeTooltipItem = item;
        tooltipPinned = pinned;
        mark.setAttribute('aria-describedby', tooltip.id);
        positionTooltip(mark);
    }

    function hideTooltip(force = false) {
        if (tooltipPinned && !force) return;
        activeTooltipMark?.removeAttribute('aria-describedby');
        activeTooltipMark = null;
        activeTooltipItem = null;
        tooltipPinned = false;
        tooltip.classList.remove('is-visible');
        tooltip.setAttribute('aria-hidden', 'true');
    }

    function attachTooltip(mark, item) {
        mark.addEventListener('mouseenter', () => showTooltip(mark, item));
        mark.addEventListener('mouseleave', () => hideTooltip());
        mark.addEventListener('focus', () => showTooltip(mark, item));
        mark.addEventListener('blur', () => hideTooltip());
        mark.addEventListener('click', event => {
            event.stopPropagation();
            if (activeTooltipMark === mark && tooltipPinned) {
                hideTooltip(true);
            } else {
                showTooltip(mark, item, true);
            }
        });
    }

    function createMark(item) {
        const mark = document.createElement('span');
        const label = accessibleLabel(item);
        mark.className = 'np-weather-mark';
        mark.dataset.timestamp = String(item.timestamp);
        mark.dataset.wind = item.windLevel;
        mark.setAttribute('role', 'img');
        mark.tabIndex = 0;
        mark.setAttribute('aria-label', label);
        mark.append(createWeatherSvg(item.condition));
        attachTooltip(mark, item);
        return mark;
    }

    function createSeparator(timestamp) {
        const separator = document.createElement('span');
        separator.className = 'np-weather-separator';
        separator.dataset.timestamp = String(timestamp);
        separator.setAttribute('aria-hidden', 'true');
        return separator;
    }

    function createRailChildren(items) {
        const children = [];
        items.forEach((item, index) => {
            children.push(createMark(item));
            const nextItem = items[index + 1];
            if (!nextItem || typeof window.getHelsinkiMidnightTimestamp !== 'function') return;
            const boundary = window.getHelsinkiMidnightTimestamp(1, new Date(item.timestamp));
            if (boundary > item.timestamp && boundary < nextItem.timestamp) {
                children.push(createSeparator(boundary));
            }
        });
        return children;
    }

    function positionMarks() {
        layoutFrame = null;
        if (!rail || !chart || typeof chart.convertToPixel !== 'function') {
            return;
        }
        const width = chart.getDom?.().clientWidth || rail.clientWidth;
        rail.querySelectorAll('.np-weather-mark, .np-weather-separator').forEach(item => {
            const x = chart.convertToPixel({ xAxisIndex: 0 }, Number(item.dataset.timestamp));
            const visible = Number.isFinite(x) && x >= 0 && x <= width;
            item.hidden = !visible;
            if (visible) item.style.left = `${x}px`;
        });
    }

    function scheduleLayout() {
        if (layoutFrame !== null) cancelAnimationFrame(layoutFrame);
        layoutFrame = requestAnimationFrame(positionMarks);
    }

    function stopIconMotion() {
        rail?.classList.remove('np-icon-motion-active');
    }

    function syncIconMotion() {
        stopIconMotion();
        if (
            !motionVisible
            || !rail?.querySelector('.np-weather-mark')
            || document.hidden
            || motionQuery?.matches
        ) return;
        rail.classList.add('np-icon-motion-active');
    }

    function observeIconMotion() {
        if (!rail) return;
        if (typeof window.IntersectionObserver !== 'function') {
            motionVisible = true;
            syncIconMotion();
            return;
        }
        motionObserver = new window.IntersectionObserver((entries) => {
            const entry = entries.find(item => item.target === rail);
            if (!entry) return;
            motionVisible = entry.isIntersecting && entry.intersectionRatio > 0;
            syncIconMotion();
        }, { threshold: 0.01 });
        motionObserver.observe(rail);
    }

    function render(data) {
        const validData = Array.isArray(data) ? data.filter(item => (
            Number.isFinite(Number(item?.timestamp))
            && item?.condition in labels.fi.conditions
            && item?.windLevel in labels.fi.wind
        )) : [];
        if (!rail) return;
        hideTooltip(true);
        rail.replaceChildren(...createRailChildren(validData));
        rail.hidden = validData.length === 0;
        scheduleLayout();
        syncIconMotion();
    }

    async function load() {
        try {
            const data = window.dataClient?.fetchJson
                ? await window.dataClient.fetchJson(endpoint)
                : await fetch(endpoint, { cache: 'no-cache' }).then(response => {
                    if (!response.ok) throw new Error(`Weather request failed (${response.status})`);
                    return response.json();
                });
            render(data);
        } catch (error) {
            console.warn('Daily weather icons unavailable:', error);
            render([]);
        }
    }

    async function loadDailySummaries() {
        try {
            const data = window.dataClient?.fetchJson
                ? await window.dataClient.fetchJson(predictionFullEndpoint)
                : await fetch(predictionFullEndpoint, { cache: 'no-cache' }).then(response => {
                    if (!response.ok) throw new Error(`Full prediction request failed (${response.status})`);
                    return response.json();
                });
            dailySummaries = buildDailySummaries(data);
            if (activeTooltipMark && activeTooltipItem) {
                showTooltip(activeTooltipMark, activeTooltipItem, tooltipPinned);
            }
        } catch (error) {
            console.warn('Daily forecast summary unavailable:', error);
            dailySummaries = new Map();
        }
    }

    if (chart && typeof chart.on === 'function') chart.on('finished', scheduleLayout);
    window.addEventListener('resize', scheduleLayout);
    window.predictionStore?.subscribe?.(scheduleLayout);
    document.addEventListener('visibilitychange', syncIconMotion);
    motionQuery?.addEventListener?.('change', syncIconMotion);
    const applyWeatherPalette = palette => {
        rail?.style.setProperty('--np-weather-separator-color', palette?.grid || 'silver');
        tooltip.style.setProperty('--np-weather-tooltip-bg', palette?.tooltipBg || '#ffffff');
        tooltip.style.setProperty('--np-weather-tooltip-border', palette?.tooltipBorder || 'rgba(31, 35, 40, 0.12)');
        tooltip.style.setProperty('--np-weather-tooltip-text', palette?.tooltipText || 'rgba(51, 51, 51, 0.9)');
    };
    applyWeatherPalette(resolveWeatherPalette('prediction'));
    subscribeWeatherPalette('prediction', applyWeatherPalette);
    document.addEventListener('click', event => {
        if (!event.target.closest?.('.np-weather-mark')) hideTooltip(true);
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') hideTooltip(true);
    });
    window.addEventListener('scroll', () => hideTooltip(true), { passive: true });
    window.addEventListener('resize', () => {
        if (activeTooltipMark) positionTooltip(activeTooltipMark);
    });
    observeIconMotion();
    window.weatherIcons = Object.freeze({
        createWeatherSvg,
        buildDailySummaries,
        positionMarks,
        render,
        load,
        syncIconMotion,
        stopIconMotion
    });
    load();
    loadDailySummaries();
})();

//#endregion weather_icons
