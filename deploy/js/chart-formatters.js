(function () {
    const HOUR_MS = 60 * 60 * 1000;

    function getLocalizedTextSafe(key) {
        if (typeof window.getLocalizedText === 'function') {
            return window.getLocalizedText(key);
        }
        if (key === 'weekdays') {
            return ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        }
        return key;
    }

    function getTimePrefixSafe() {
        if (typeof window.getTimePrefix === 'function') {
            return window.getTimePrefix();
        }
        return '';
    }

    function createTooltipFormatter(seriesNameMappings = {}) {
        return function tooltipFormatter(params) {
            const weekdays = getLocalizedTextSafe('weekdays');
            const date = new Date(params[0].axisValue);
            const weekday = weekdays[date.getDay()];
            const day = date.getDate();
            const month = date.getMonth() + 1;
            const hours = (`0${date.getHours()}`).slice(-2);
            const minutes = (`0${date.getMinutes()}`).slice(-2);
            const prefix = getTimePrefixSafe();
            const formattedDateString = `${weekday} ${day}.${month}. ${prefix} ${hours}:${minutes}`;
            let result = `${formattedDateString}<br/>`;

            params.sort((a, b) => {
                if (a.seriesName === 'Nordpool') return -1;
                if (b.seriesName === 'Nordpool') return 1;
                return 0;
            });

            params.forEach(item => {
                if (item.seriesType !== 'line' && item.seriesType !== 'bar') {
                    return;
                }
                const valueRounded = (item.value[1] !== null && typeof item.value[1] !== 'undefined')
                    ? item.value[1].toFixed(1)
                    : '-';
                const unitLabel = seriesNameMappings[item.seriesName] || '¢/kWh';
                result += `${item.marker} ${item.seriesName}: ${valueRounded} ${unitLabel}<br/>`;
            });

            return result;
        };
    }

    function createXAxisFormatter(showFullDate = false) {
        return function xAxisFormatter(value) {
            const date = new Date(value);
            const weekdays = getLocalizedTextSafe('weekdays');
            const weekday = weekdays[date.getDay()];
            if (showFullDate) {
                const day = date.getDate();
                const month = date.getMonth() + 1;
                return `${day}.${month}.`;
            }
            return weekday;
        };
    }

    window.chartFormatters = Object.freeze({
        createTooltipFormatter,
        createXAxisFormatter,
    });

    window.createTooltipFormatter = createTooltipFormatter;
    window.createXAxisFormatter = createXAxisFormatter;
})();
