if (window.location.hostname === "nordpool-predict-fi.web.app") {
    window.location.href = "https://sahkovatkain.web.app" + window.location.pathname + window.location.search;
}

//#region conf
// ==========================================================================
// Base configuration and environment detection
// ==========================================================================

// Determine base URL based on hosting environment
var baseUrl = (function() {
    switch (window.location.hostname) {
        case "":
        case "localhost":
            return "http://localhost:5005";
        case "rpi4":
            return "http://rpi4:5000";
        case "nordpool-predict-fi.web.app":
            return "https://nordpool-predict-fi.web.app";
        case "sahkovatkain.web.app":
            return "https://sahkovatkain.web.app";
        default:
            return "https://raw.githubusercontent.com/vividfog/nordpool-predict-fi/main/deploy";
    }
})();

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
    let currentTime = new Date();
    let month = currentTime.getMonth() + 1;
    let day = currentTime.getDate();
    let hours = currentTime.getHours();
    let minutes = currentTime.getMinutes();

    hours = hours < 10 ? '0' + hours : hours;
    minutes = minutes < 10 ? '0' + minutes : minutes;

    return day + '.' + month + '. klo ' + hours + ':' + minutes;
}

// ==========================================================================
// Chart construction and formatting utilities
// ==========================================================================

function createTooltipFormatter(seriesNameMappings = {}) {
    return function(params) {
        var weekdays = ['su', 'ma', 'ti', 'ke', 'to', 'pe', 'la'];
        var date = new Date(params[0].axisValue);
        
        var weekday = weekdays[date.getDay()];
        var day = date.getDate();
        var month = date.getMonth() + 1;
        var hours = ("0" + date.getHours()).slice(-2);
        var minutes = ("0" + date.getMinutes()).slice(-2);
        
        var formattedDateString = `${weekday} ${day}.${month}. klo ${hours}:${minutes}`;
        var result = formattedDateString + '<br/>';
        
        // Sort params to show Nordpool data first if it exists
        params.sort((a, b) => {
            if (a.seriesName === 'Nordpool') return -1;
            if (b.seriesName === 'Nordpool') return 1;
            return 0;
        });
        
        params.forEach(function(item) {
            if (item.seriesType !== 'line' && item.seriesType !== 'bar') return;
            
            var valueRounded = item.value[1] !== undefined ? item.value[1].toFixed(1) : '';
            var unitLabel = seriesNameMappings[item.seriesName] || '¢/kWh';
            result += item.marker + " " + item.seriesName + ': ' + valueRounded + ' ' + unitLabel + '<br/>';
        });
        
        return result;
    };
}

function createXAxisFormatter(showFullDate = false) {
    return function(value) {
        var date = new Date(value);
        var weekdays = ['su', 'ma', 'ti', 'ke', 'to', 'pe', 'la'];
        var weekday = weekdays[date.getDay()];
        
        if (showFullDate) {
            return date.toLocaleDateString('fi-FI');
        }
        return weekday;
    };
}

function createCurrentTimeMarkLine() {
    return {
        symbol: 'none',
        label: {
            formatter: formatCurrentTimeLabel,
            position: 'end'
        },
        lineStyle: {
            type: 'dotted',
            color: 'crimson',
            width: 1.5
        },
        data: [{ xAxis: new Date().getTime() }]
    };
}

//#region options
// ==========================================================================
// Chart base configuration builder
// ==========================================================================

function createBaseChartOptions(config) {
    return {
        title: { text: ' ' },
        legend: config.legend || { show: false },
        tooltip: {
            trigger: 'axis',
            formatter: config.tooltipFormatter || createTooltipFormatter()
        },
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
}

//#region markers
// ==========================================================================
// Chart update and marker position utilities
// ==========================================================================

function updateMarkerPosition(chart) {
    var currentTime = new Date().getTime();
    var option = chart.getOption();
    
    option.series.forEach((series) => {
        if (series.markLine) {
            series.markLine.data = [{ xAxis: currentTime }];
        }
    });
    
    chart.setOption(option, false, false);
}

//#region narration
// ==========================================================================
// Fetch and display narration text
// ==========================================================================

const narrationFile = window.location.pathname.includes('index_en') ? 'narration_en.md' : 'narration.md';

fetch(`${baseUrl}/${narrationFile}`)
    .then(response => {
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        return response.text();
    })
    .then(text => {
        document.getElementById('narration').innerHTML = marked.parse(text);
    })
    .catch(error => console.error('Fetching Markdown failed:', error));

//#region prediction
// ==========================================================================
// Spot price prediction chart initialization and data handling
// ==========================================================================

var nfpChart = echarts.init(document.getElementById('predictionChart'));

// Calculate dates for API requests
var startDate = addDays(new Date(), -0).toISOString();
var endDate = addDays(new Date(), 2).toISOString();

// URLs for the datasets
var npfUrl = `${baseUrl}/prediction.json`;
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
    fetch(`${sahkotinUrl}?${sahkotinParams}`).then(r => r.text())
])
    .then(([npfData, sahkotinCsv]) => {
        // Process Sähkötin data
        var sahkotinSeriesData = sahkotinCsv.split('\n').slice(1).map(line => {
            var [timestamp, price] = line.split(',');
            var parsedTime = new Date(timestamp).getTime();
            var localTime = new Date(parsedTime).toString();
            console.log(`Sähkötin timestamp: ${localTime}, Price: ${parseFloat(price)} ¢/kWh`);
            return [parsedTime, parseFloat(price)];
        });

        // No overlap for bar chart experiment
        var lastSahkotinTimestamp = Math.max(...sahkotinSeriesData.map(item => item[0]));
        console.log("End of Sähkötin data for today; displaying the Nordpool prediction data from:", 
            new Date(lastSahkotinTimestamp).toString());

        // Prepare NPF series data
        var npfSeriesData = npfData
            .map(item => [item[0], item[1]])
            .filter(item => item[0] > lastSahkotinTimestamp);

        // Debug logs
        npfSeriesData.forEach(item => {
            var localTime = new Date(item[0]).toString();
            console.log(`Prediction timestamp: ${localTime}, Price: ${item[1]} ¢/kWh`);
        });

        // Create chart options
        const chartOptions = createBaseChartOptions({
            legend: {
                data: ['Nordpool', 'Ennuste'],
                right: 16
            },
            tooltipFormatter: createTooltipFormatter(),
            visualMap: [
                {
                    // For realized price
                    show: false,
                    seriesIndex: [1],
                    pieces: [{ lte: 10000, color: 'limegreen' }],
                    outOfRange: { color: '#999' }
                },
                {
                    // For predicted price
                    show: false,
                    seriesIndex: [0],
                    pieces: [{ lte: 10000, color: 'dodgerblue' }],
                    outOfRange: { color: '#999' }
                }
            ],
            series: [
                {
                    name: 'Ennuste',
                    type: 'bar',
                    barWidth: '40%',
                    data: npfSeriesData,
                    symbol: 'none',
                    opacity: 1.0
                },
                {
                    name: 'Nordpool',
                    type: 'bar',
                    barWidth: '40%',
                    data: sahkotinSeriesData,
                    symbol: 'none',
                    step: 'middle',
                    opacity: 1.0
                },
                {
                    type: 'line',
                    markLine: createCurrentTimeMarkLine()
                }
            ]
        });

        nfpChart.setOption(chartOptions);
    })
    .catch(error => {
        console.error('Error fetching or processing data:', error);
    });

// Setup interval for marker updates
setInterval(() => updateMarkerPosition(nfpChart), 10000);

//#region windpower
// ==========================================================================
// Wind power generation chart and data handling
// ==========================================================================

var windPowerChart = echarts.init(document.getElementById('windPowerChart'));
var windPowerUrl = `${baseUrl}/windpower.json`;

// ==========================================================================
// Fetching and processing wind power data
// ==========================================================================

fetch(windPowerUrl)
    .then(response => {
        if (!response.ok) {
            throw new Error('Network response was not ok: ' + response.statusText);
        }
        return response.json();
    })
    .then(windPowerData => {
        console.log("Wind Power Data:", windPowerData);

        // Get start of today in local time
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const todayTimestamp = today.getTime();

        // Filter and prepare wind power series data (convert to GW)
        var windPowerSeriesData = windPowerData
            .filter(item => item[0] >= todayTimestamp)
            .map(item => [item[0], item[1] / 1000]);
        
        console.log("Processed Wind Power Series Data:", windPowerSeriesData);

        // Create wind power chart options
        const windChartOptions = createBaseChartOptions({
            yAxisName: 'GW',
            yAxisMax: 8,  // Fixed max for GW scale
            tooltipFormatter: createTooltipFormatter({ 'Tuulivoima (GW)': 'GW' }),
            visualMap: {
                show: false,
                seriesIndex: 0,
                pieces: [
                    { lte: 1, color: 'red' },
                    { gt: 1, lte: 2, color: 'skyblue' },
                    { gt: 2, lte: 3, color: 'deepskyblue' },
                    { gt: 3, lte: 4, color: 'dodgerblue' },
                    { gt: 4, lte: 5, color: 'blue' },
                    { gt: 5, lte: 6, color: 'mediumblue' },
                    { gt: 6, lte: 7, color: 'darkblue' },
                    { gt: 7, color: 'midnightblue' }
                ],
                outOfRange: {
                    color: '#999'
                }
            },
            series: [
                {
                    name: 'Tuulivoima (GW)',
                    type: 'line',
                    data: windPowerSeriesData,
                    symbol: 'none',
                    lineStyle: {
                        type: 'solid',
                        width: 1.5
                    },
                    step: 'end',
                    areaStyle: { 
                        color: 'rgba(135, 206, 250, 0.2)' // skyblue
                    },
                    opacity: 0.9,
                    markLine: createCurrentTimeMarkLine()
                }
            ]
        });

        windPowerChart.setOption(windChartOptions);
    })
    .catch(error => console.error('Error fetching wind power data:', error));

// Setup interval for marker updates
setInterval(() => updateMarkerPosition(windPowerChart), 10000);

//#region history
// ==========================================================================
// Historical price chart initialization
// ==========================================================================

var historyChart = echarts.init(document.getElementById('historyChart'));

// Construct URLs for fetching historical data
const dateStrings = getPastDateStrings(35); // 30 days plus 5 days of prediction data
const historicalUrls = dateStrings.map(date => `${baseUrl}/prediction_snapshot_${date}.json`);

// ==========================================================================
// Historical data fetching and processing
// ==========================================================================

function fetchHistoricalData(urls) {
    const today = new Date();
    const cutoffDate = new Date(today);
    cutoffDate.setDate(today.getDate() - 30);
    const cutoffTimestamp = cutoffDate.getTime();

    return Promise.all(urls.map(url => {
        console.log(`[fetchHistoricalData] Fetching URL: ${url}`);

        return fetch(url)
            .then(response => {
                console.log(`[fetchHistoricalData] Response status: ${response.status} from ${url}`);
                if (!response.ok) {
                    console.warn(`[fetchHistoricalData] Failed to fetch or file not found: ${url}`);
                }
                return response.json();
            })
            .then(jsonData => {
                if (!jsonData) {
                    console.warn(`[fetchHistoricalData] No data returned for: ${url}`);
                    return null;
                }

                console.log(`[fetchHistoricalData] Raw JSON length for ${url}: ${jsonData.length}`);

                const match = url.match(/(\d{4}-\d{2}-\d{2})/);
                if (match) {
                    const snapshotDateString = match[1];
                    const snapshotDateTime = new Date(`${snapshotDateString}T00:00:00Z`).getTime();
                    console.log(`[fetchHistoricalData] Snapshot date: ${snapshotDateString}, which is ${snapshotDateTime} in ms UTC`);

                    const skipDays = 2; 
                    const cutoffMs = snapshotDateTime + skipDays * 24 * 60 * 60 * 1000;

                    const originalCount = jsonData.length;
                    // Filter out data older than the day after the snapshot and older than 30 days from today
                    jsonData = jsonData.filter(item => item[0] >= cutoffMs && item[0] >= cutoffTimestamp);

                    console.log(
                        `[fetchHistoricalData] Filtered out ${originalCount - jsonData.length} of ${originalCount} entries for ${url}, 
                         cutoffMs: ${cutoffMs}`
                    );
                } else {
                    console.warn(`[fetchHistoricalData] No date found in filename: ${url}`);
                }

                console.log(`[fetchHistoricalData] Final JSON length for ${url}: ${jsonData.length}`);
                return jsonData;
            })
            .catch(error => {
                console.error(`[fetchHistoricalData] Error fetching or parsing ${url}:`, error);
                return null;
            });
    }));
}

function processSahkotinCsv(csvData) {
    const lines = csvData.split('\n').slice(1); // Skip header
    return lines.map(line => {
        const [timestamp, price] = line.split(',');
        return [new Date(timestamp).getTime(), parseFloat(price)];
    });
}

//#region histchart
// ==========================================================================
// Historical chart presentation setup
// ==========================================================================

function setupHistoryChart(data) {
    const cleanedData = data.filter(item => item !== null).slice(1);
    console.log("setupHistoryChart found these snapshots: ", cleanedData);

    const series = cleanedData.map((seriesData, index) => ({
        name: index === 0 ? "Uusin" : `${0 - index} pv sitten`,
        type: 'line',
        data: seriesData.map(item => [item[0], item[1]]),
        symbol: 'none',
        lineStyle: {
            width: index === 0 ? 1.5 : 1,
            type: index === 0 ? 'solid' : 'dotted'
        },
        color: 'dodgerblue',
        opacity: Math.pow(0.95, index)-.1
    }));

    // Add a separate series item for the markLine
    series.push({
        type: 'line',
        data: [],
        markLine: createCurrentTimeMarkLine()
    });

    // Create history chart options
    const historyChartOptions = createBaseChartOptions({
        tooltipFormatter: createTooltipFormatter(),
        xAxisFormatter: createXAxisFormatter(true),
        series: series
    });

    historyChart.setOption(historyChartOptions);
    console.log("setupHistoryChart found", series.length, "snapshots");
    return series.length;
}

function addSahkotinDataToChart(sahkotinData) {
    const sahkotinSeries = {
        name: 'Nordpool',
        type: 'line',
        data: sahkotinData,
        symbol: 'none',
        step: 'middle',
        lineStyle: {
            type: 'solid',
            width: 1.5
        },
        color: 'orange',
        opacity: 0.9
    };
    
    historyChart.setOption({
        series: historyChart.getOption().series.concat(sahkotinSeries)
    });
}

//#region sahkotin
// ==========================================================================
// Sähkötin data fetching and chart integration
// ==========================================================================

function setupSahkotinData() {
    const startDate = getPastDateStrings(30).pop();
    var endDate = addDays(new Date(), 2).toISOString();

    const sahkotinUrl = 'https://sahkotin.fi/prices.csv';
    const sahkotinParams = new URLSearchParams({
        fix: 'true',
        vat: 'true',
        start: startDate,
        end: endDate,
    });

    fetch(`${sahkotinUrl}?${sahkotinParams}`)
        .then(response => response.text())
        .then(csvData => {
            const sahkotinData = processSahkotinCsv(csvData);
            addSahkotinDataToChart(sahkotinData);
        })
        .catch(error => console.error("Error fetching Sähkötin data:", error));
}

//#region init
// ==========================================================================
// Initialize history chart with fetched data
// ==========================================================================

fetchHistoricalData(historicalUrls)
    .then(data => {
        setupHistoryChart(data);
        setupSahkotinData();
    })
    .catch(error => console.error("Error in chart setup:", error));

// Setup interval for marker updates
setInterval(() => updateMarkerPosition(historyChart), 10000);

//#region layout
// ==========================================================================
// Window resize handling and chart adjustments
// ==========================================================================

window.onresize = function() {
    nfpChart.resize();
    historyChart.resize();
    windPowerChart.resize();
};

