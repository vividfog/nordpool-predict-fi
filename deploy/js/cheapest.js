document.addEventListener('DOMContentLoaded', function() {
    const card = document.getElementById('cheapestWindows');
    if (!card) {
        return;
    }

    const tableBody = card.querySelector('tbody');
    if (!tableBody) {
        return;
    }

    const isEnglish = window.location.pathname.includes('index_en');
    const HELSINKI_TIMEZONE = 'Europe/Helsinki';
    const REFRESH_INTERVAL_MS = 60000;
    const DOT_COLORS = {
        3: '#87CEEB',
        6: '#00BFFF',
        12: '#1E90FF',
        custom: '#7B68EE'
    };
    const TABLE_HEADERS = {
        duration: getLocalizedText('cheapest_column_duration'),
        average: getLocalizedText('cheapest_column_average'),
        countdown: getLocalizedText('cheapest_column_countdown'),
        start: getLocalizedText('cheapest_column_start')
    };

    let latestData = null;
    let refreshTimer = null;

    function setMessageRow(text) {
        tableBody.innerHTML = `
            <tr class="cheapest-row cheapest-row-empty">
                <td colspan="4">${text}</td>
            </tr>
        `;
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
        const isCustom = windowInfo.isCustom;
        const accent = isCustom ? DOT_COLORS.custom : DOT_COLORS[duration] || DOT_COLORS.custom;
        const label = isCustom
            ? getLocalizedText('cheapest_custom_label')
            : `${duration} h`;

        return `
            <span class="cheapest-badge">
                <span class="cheapest-dot" style="background-color:${accent};"></span>
                ${label}
            </span>
        `;
    }

    function buildRows(data) {
        if (!data || !Array.isArray(data.windows)) {
            return [];
        }

        const baseRows = data.windows.map(windowInfo => ({
            ...windowInfo,
            isCustom: false
        }));

        if (data.customWindow) {
            baseRows.push({
                ...data.customWindow,
                isCustom: true
            });
        }

        return baseRows;
    }

    function renderRows() {
        if (!latestData) {
            setMessageRow(getLocalizedText('cheapest_table_loading'));
            return;
        }

        const rows = buildRows(latestData);
        if (!rows.length) {
            setMessageRow(getLocalizedText('cheapest_table_none'));
            return;
        }

        tableBody.innerHTML = rows.map(windowInfo => {
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
    }

    function startCountdownUpdates() {
        if (refreshTimer) {
            clearInterval(refreshTimer);
        }
        refreshTimer = setInterval(renderRows, REFRESH_INTERVAL_MS);
    }

    window.addEventListener('prediction-data-ready', function(event) {
        latestData = event.detail;
        renderRows();
        startCountdownUpdates();
    });

    if (window.latestPredictionData) {
        latestData = window.latestPredictionData;
        renderRows();
        startCountdownUpdates();
    } else {
        setMessageRow(getLocalizedText('cheapest_table_loading'));
    }
});
