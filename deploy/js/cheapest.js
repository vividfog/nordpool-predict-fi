//#region cheapest
const cheapestStorage = window.appStorage && window.appStorage.enabled ? window.appStorage : null;
const CHEAPEST_STORAGE_KEY = 'np_cheapest_preferences';

document.addEventListener('DOMContentLoaded', function() {
    //#region dom_setup
    const card = document.getElementById('cheapestWindows');
    if (!card) {
        return;
    }

const tableBody = card.querySelector('tbody');
    if (!tableBody) {
        return;
    }

    const controlsForm = document.getElementById('cheapestControls');
    const lookaheadInput = document.getElementById('cheapestDaysInput');
    const startHourInput = document.getElementById('cheapestStartHourInput');
    const endHourInput = document.getElementById('cheapestEndHourInput');

    const resolveCheapestPalette = typeof window.resolveChartPalette === 'function'
        ? window.resolveChartPalette
        : () => null;
    const subscribeCheapestPalette = typeof window.subscribeThemePalette === 'function'
        ? window.subscribeThemePalette
        : () => () => {};
    const CHEAPEST_THEME_UNSUB_KEY = '__np_cheapest_theme_unsub__';
    const isEnglish = window.location.pathname.includes('index_en');
    const HELSINKI_TIMEZONE = 'Europe/Helsinki';
    const REFRESH_INTERVAL_MS = 60000;
    let cheapestPalette = resolveCheapestPalette('cheapest');
    const DOT_COLORS = {
        3: '#87CEEB',
        6: '#00BFFF',
        12: '#1E90FF'
    };
    const TABLE_HEADERS = {
        duration: getLocalizedText('cheapest_column_duration'),
        average: getLocalizedText('cheapest_column_average'),
        countdown: getLocalizedText('cheapest_column_countdown'),
        start: getLocalizedText('cheapest_column_start')
    };

const defaultsSource = window.CHEAPEST_WINDOW_DEFAULTS || {};
const hasOwn = Object.hasOwn ? Object.hasOwn.bind(Object) : (obj, prop) => Object.prototype.hasOwnProperty.call(obj, prop);
    const defaults = {
        lookaheadDays: ensureNumber(defaultsSource.lookaheadDays, 4),
        minLookaheadDays: ensureNumber(defaultsSource.minLookaheadDays, 1),
        maxLookaheadDays: ensureNumber(defaultsSource.maxLookaheadDays, 7),
        startHour: ensureNumber(defaultsSource.startHour, 0),
        endHour: ensureNumber(defaultsSource.endHour, 23),
        minHour: ensureNumber(defaultsSource.minHour, 0),
        maxHour: ensureNumber(defaultsSource.maxHour, 23)
    };
    const baseDefaults = Object.assign({}, defaults);
    const savedCheapest = cheapestStorage ? cheapestStorage.get(CHEAPEST_STORAGE_KEY) : null;
    let hasStoredCheapest = Boolean(savedCheapest);
    if (savedCheapest) {
        if (hasOwn(savedCheapest, 'lookaheadDays')) {
            defaults.lookaheadDays = clampDays(savedCheapest.lookaheadDays, defaults.lookaheadDays);
        }
        if (hasOwn(savedCheapest, 'startHour')) {
            const fallbackStart = defaults.startHour;
            defaults.startHour = clampHourValue(savedCheapest.startHour, fallbackStart, baseDefaults.startHour);
        }
        if (hasOwn(savedCheapest, 'endHour')) {
            const fallbackEnd = defaults.endHour;
            defaults.endHour = clampHourValue(savedCheapest.endHour, fallbackEnd, baseDefaults.endHour);
        }
    }

    let predictionData = null;
    let latestWindowState = null;
    let refreshTimer = null;
    let currentConfig = {
        lookaheadDays: defaults.lookaheadDays,
        startHour: defaults.startHour,
        endHour: defaults.endHour
    };
    const PULSE_CLASS = 'cheapest-refresh';
    let pulseTimer = null;
    const PULSE_DURATION_MS = 1100;

    syncControlsWithConfig(currentConfig);
    attachControls();
    persistCheapestSettings();

    const predictionStore = window.predictionStore || null;
    if (!predictionStore || typeof predictionStore.subscribe !== 'function') {
        console.warn('predictionStore unavailable; cheapest module idle');
        setMessageRow(getLocalizedText('cheapest_table_loading'));
        return;
    }
    const initialPrediction = typeof predictionStore.getLatest === 'function'
        ? predictionStore.getLatest()
        : null;
    if (initialPrediction) {
        handlePredictionPayload(initialPrediction);
    } else {
        setMessageRow(getLocalizedText('cheapest_table_loading'));
    }
    predictionStore.subscribe(handlePredictionPayload);

    //#region helpers

    function ensureNumber(value, fallback) {
        const numeric = Number(value);
        return Number.isFinite(numeric) ? numeric : fallback;
    }

    function toInteger(input) {
        if (typeof input === 'number') {
            return Number.isFinite(input) ? Math.round(input) : NaN;
        }
        if (typeof input !== 'string') {
            return NaN;
        }
        const trimmed = input.trim();
        if (trimmed === '') {
            return NaN;
        }
        const parsed = Number.parseInt(trimmed, 10);
        return Number.isFinite(parsed) ? parsed : NaN;
    }

    function toHourCandidate(input) {
        if (typeof input === 'number') {
            return Number.isFinite(input) ? Math.round(input) : NaN;
        }
        if (typeof input !== 'string') {
            return NaN;
        }
        const digits = input.replace(/[^0-9]/g, '');
        if (!digits) {
            return NaN;
        }
        const parsed = Number.parseInt(digits, 10);
        return Number.isFinite(parsed) ? parsed : NaN;
    }

    function clampDays(value, fallback) {
        const candidate = toInteger(value);
        const baseline = Number.isNaN(candidate) ? toInteger(fallback) : candidate;
        if (!Number.isFinite(baseline)) {
            return defaults.lookaheadDays;
        }
        if (baseline < defaults.minLookaheadDays) {
            return defaults.minLookaheadDays;
        }
        if (baseline > defaults.maxLookaheadDays) {
            return defaults.maxLookaheadDays;
        }
        return baseline;
    }

    function clampHourValue(value, fallback, defaultValue) {
        const candidate = toHourCandidate(value);
        const baseline = Number.isNaN(candidate) ? toHourCandidate(fallback) : candidate;
        const pivot = Number.isNaN(baseline) ? defaultValue : baseline;
        if (pivot < defaults.minHour) {
            return defaults.minHour;
        }
        if (pivot > defaults.maxHour) {
            return defaults.maxHour;
        }
        return pivot;
    }

    //#region render

    function setMessageRow(text) {
        tableBody.innerHTML = `
            <tr class="cheapest-row cheapest-row-empty">
                <td colspan="4">${text}</td>
            </tr>
        `;
    }

    function syncControlsWithConfig(config) {
        const normalized = {
        lookaheadDays: clampDays(config?.lookaheadDays, defaults.lookaheadDays),
        startHour: clampHourValue(config?.startHour, defaults.startHour, defaults.startHour),
        endHour: clampHourValue(config?.endHour, defaults.endHour, defaults.endHour)
        };

        if (lookaheadInput) {
            lookaheadInput.value = normalized.lookaheadDays.toString();
        }
        if (startHourInput) {
            startHourInput.value = normalized.startHour.toString();
        }
        if (endHourInput) {
            endHourInput.value = normalized.endHour.toString();
        }

        currentConfig = normalized;
        return normalized;
    }

    function normalizeControlsFromInputs() {
        const normalized = {
            lookaheadDays: clampDays(lookaheadInput?.value, currentConfig.lookaheadDays),
            startHour: clampHourValue(startHourInput?.value, currentConfig.startHour, defaults.startHour),
            endHour: clampHourValue(endHourInput?.value, currentConfig.endHour, defaults.endHour)
        };

        if (lookaheadInput) {
            lookaheadInput.value = normalized.lookaheadDays.toString();
        }
        if (startHourInput) {
            startHourInput.value = normalized.startHour.toString();
        }
        if (endHourInput) {
            endHourInput.value = normalized.endHour.toString();
        }

        currentConfig = normalized;
        return normalized;
    }

    /**
     * Persists the current cheapest window configuration when storage is available.
     * Safely no-ops if storage is disabled or unavailable.
     */
    function persistCheapestSettings() {
        if (!cheapestStorage) {
            return;
        }
        hasStoredCheapest = true;
        cheapestStorage.set(CHEAPEST_STORAGE_KEY, {
            lookaheadDays: currentConfig.lookaheadDays,
            startHour: currentConfig.startHour,
            endHour: currentConfig.endHour
        });
    }

    function formatStart(timestamp) {
        if (!Number.isFinite(timestamp)) {
            return '--';
        }

        const date = new Date(timestamp);
        const parts = new Intl.DateTimeFormat(isEnglish ? 'en-GB' : 'fi-FI', {
            weekday: 'short',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
            timeZone: HELSINKI_TIMEZONE
        }).formatToParts(date);

        const weekday = parts.find(part => part.type === 'weekday')?.value ?? '';
        const hour = parts.find(part => part.type === 'hour')?.value ?? '00';
        const minute = parts.find(part => part.type === 'minute')?.value ?? '00';
        const prefix = getTimePrefix();

        const normalizedHour = hour.padStart(2, '0');
        const normalizedMinute = minute.padStart(2, '0');

        return `${weekday} ${prefix} ${normalizedHour}:${normalizedMinute}`;
    }

    function formatCountdown(startTs, endTs) {
        if (!Number.isFinite(startTs)) {
            return getLocalizedText('cheapest_waiting');
        }

        const now = Date.now();

        if (startTs > now) {
            return formatFutureCountdown(startTs - now);
        }

        if (Number.isFinite(endTs) && endTs > now) {
            return getLocalizedText('cheapest_now');
        }

        if (!Number.isFinite(endTs)) {
            return getLocalizedText('cheapest_now');
        }

        if (endTs <= now) {
            return getLocalizedText('cheapest_ended');
        }

        return getLocalizedText('cheapest_waiting');
    }

    function formatFutureCountdown(diffMs) {
        const minutesTotal = Math.max(Math.round(diffMs / 60000), 0);
        const minutesInDay = 24 * 60;
        const days = Math.floor(minutesTotal / minutesInDay);
        const hours = Math.floor((minutesTotal % minutesInDay) / 60);
        const minutes = minutesTotal % 60;

        if (days > 0) {
            return `${days} ${getLocalizedText('cheapest_day_unit')} ${hours} ${getLocalizedText('cheapest_hour_unit')}`;
        }

        return `${hours} ${getLocalizedText('cheapest_hour_unit')} ${minutes.toString().padStart(2, '0')} ${getLocalizedText('cheapest_minute_unit')}`;
    }

    function badgeMarkup(windowInfo) {
        const duration = Number(windowInfo.duration);
        const accent = getDotColor(duration);
        const label = Number.isFinite(duration) ? `${duration} h` : '--';

        return `
            <span class="cheapest-badge">
                <span class="cheapest-dot" style="background-color:${accent};"></span>
                ${label}
            </span>
        `;
    }

    function renderRows(options = {}) {
        const shouldPulse = options.pulse !== false;

        if (!predictionData) {
            setMessageRow(getLocalizedText('cheapest_table_loading'));
            if (shouldPulse) {
                triggerTablePulse();
            }
            return;
        }

        const windows = latestWindowState?.windows;
        if (!windows) {
            setMessageRow(getLocalizedText('cheapest_table_loading'));
            if (shouldPulse) {
                triggerTablePulse();
            }
            return;
        }

        if (!windows.length) {
            setMessageRow(getLocalizedText('cheapest_table_none'));
            if (shouldPulse) {
                triggerTablePulse();
            }
            return;
        }

        tableBody.innerHTML = windows.map(windowInfo => {
            const average = Number(windowInfo.average);
            const start = Number(windowInfo.start);
            const end = Number(windowInfo.end);

            const averageDisplay = Number.isFinite(average) ? average.toFixed(1) : '--';
            const countdown = formatCountdown(start, end);
            const startDisplay = Number.isFinite(start) ? formatStart(start) : '--';

            return `
                <tr class="cheapest-row">
                    <td class="cheapest-cell cheapest-cell-duration" data-label="${TABLE_HEADERS.duration}">
                        ${badgeMarkup(windowInfo)}
                    </td>
                    <td class="cheapest-cell cheapest-cell-average" data-label="${TABLE_HEADERS.average}">
                        ${averageDisplay}
                    </td>
                    <td class="cheapest-cell cheapest-cell-countdown" data-label="${TABLE_HEADERS.countdown}">
                        ${countdown}
                    </td>
                    <td class="cheapest-cell cheapest-cell-start" data-label="${TABLE_HEADERS.start}">
                        ${startDisplay}
                    </td>
                </tr>
            `;
        }).join('');

        if (shouldPulse) {
            triggerTablePulse();
        }
    }

    //#region payload_handling

    function updateCheapestWindows() {
        if (!predictionData || typeof window.buildCheapestWindowPayload !== 'function') {
            return;
        }

        const series = predictionData.mergedSeries;
        if (!Array.isArray(series) || series.length === 0) {
            return;
        }

        const payload = window.buildCheapestWindowPayload(series, Date.now(), currentConfig);
        latestWindowState = payload;

        predictionData.windows = payload.windows;
        predictionData.meta = Object.assign({}, predictionData.meta, payload.meta, currentConfig);

        if (predictionStore && typeof predictionStore.setLatest === 'function') {
            predictionStore.setLatest(predictionData, { silent: true });
        }
    }

    function handlePredictionPayload(payload) {
        if (!payload) {
            return;
        }

        predictionData = payload;
        const meta = payload?.meta || {};
        const mergedPreferences = {
            lookaheadDays: hasStoredCheapest
                ? currentConfig.lookaheadDays
                : (Number.isFinite(meta.lookaheadDays) ? meta.lookaheadDays : currentConfig.lookaheadDays),
            startHour: hasStoredCheapest
                ? currentConfig.startHour
                : (Number.isFinite(meta.startHour) ? meta.startHour : currentConfig.startHour),
            endHour: hasStoredCheapest
                ? currentConfig.endHour
                : (Number.isFinite(meta.endHour) ? meta.endHour : currentConfig.endHour)
        };

        syncControlsWithConfig(mergedPreferences);
        persistCheapestSettings();
        updateCheapestWindows();
        renderRows();
        startCountdownUpdates();
    }

    function startCountdownUpdates() {
        if (refreshTimer) {
            clearInterval(refreshTimer);
        }
        refreshTimer = setInterval(function() {
            updateCheapestWindows();
            renderRows({ pulse: false });
        }, REFRESH_INTERVAL_MS);
    }

    function handleControlsInput() {
        normalizeControlsFromInputs();
        persistCheapestSettings();
        updateCheapestWindows();
        renderRows();
    }

    function attachControls() {
        if (controlsForm) {
            controlsForm.addEventListener('submit', function(event) {
                event.preventDefault();
            });
        }

        [lookaheadInput, startHourInput, endHourInput].forEach(input => {
            if (!input) {
                return;
            }
            input.addEventListener('change', handleControlsInput);
        });
    }

    function getDotColor(duration) {
        const paletteDots = cheapestPalette?.dots || DOT_COLORS;
        const key = String(duration);
        return paletteDots[key] || '#7B68EE';
    }

    //#region theme

    if (window[CHEAPEST_THEME_UNSUB_KEY]) {
        try {
            window[CHEAPEST_THEME_UNSUB_KEY]();
        } catch (error) {
            console.warn('Failed to cleanup cheapest palette subscription', error);
        }
    }
    window[CHEAPEST_THEME_UNSUB_KEY] = subscribeCheapestPalette('cheapest', palette => {
        cheapestPalette = palette || cheapestPalette;
        renderRows({ pulse: false });
    });

    //#region animation

    function triggerTablePulse() {
        if (!card) {
            return;
        }
        if (pulseTimer) {
            clearTimeout(pulseTimer);
            pulseTimer = null;
        }
        card.classList.remove(PULSE_CLASS);
        // Force reflow so the animation can retrigger
        void card.offsetWidth;
        card.classList.add(PULSE_CLASS);
        pulseTimer = setTimeout(() => {
            card.classList.remove(PULSE_CLASS);
            pulseTimer = null;
        }, PULSE_DURATION_MS);
    }
});
