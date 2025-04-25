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
                    top: 50,
                    right: 10,
                    pieces: [
                        { lte: 5, color: 'lime' },
                        { gt: 5, lte: 10, color: 'limegreen' },
                        { gt: 10, lte: 15, color: 'gold' },
                        { gt: 15, lte: 20, color: 'darkorange' },
                        { gt: 20, lte: 30, color: 'red' },
                        { gt: 30, color: 'darkred' }
                    ],
                    outOfRange: { color: '#999' }
                },
                {
                    // For predicted price
                    show: false,
                    seriesIndex: [0],
                    top: 50,
                    right: 10,
                    pieces: [
                        { lte: 5, color: 'skyblue' },
                        { gt: 5, lte: 10, color: 'deepskyblue' },
                        { gt: 10, lte: 15, color: 'dodgerblue' },
                        { gt: 15, lte: 20, color: 'blue' },
                        { gt: 20, lte: 30, color: 'darkblue' },
                        { gt: 30, color: 'midnightblue' }
                    ],
                    outOfRange: { color: '#999' }
                }
            ],
            series: [
                {
                    name: 'Ennuste',
                    type: 'line',
                    data: npfSeriesData,
                    symbol: 'none',
                    step: 'start',
                    lineStyle: {
                        width: 2,
                        type: 'solid'
                    },
                    opacity: 1.0
                },
                {
                    name: 'Nordpool',
                    type: 'line',
                    data: sahkotinSeriesData,
                    symbol: 'none',
                    step: 'start',
                    lineStyle: {
                        width: 2,
                        type: 'solid'
                    },
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

Promise.all([
    fetch(windPowerUrl).then(response => {
        if (!response.ok) {
            throw new Error('Network response was not ok: ' + response.statusText);
        }
        return response.json();
    }),
    fetch(`${sahkotinUrl}?${sahkotinParams}`).then(r => r.text()).then(text => {
        const sahkotinData = text.split('\n').slice(1).map(line => {
            const [timestamp, price] = line.split(',');
            return [new Date(timestamp).getTime(), parseFloat(price)];
        });
        return sahkotinData;
    }),
    fetch(npfUrl).then(r => r.json()) // Add prediction data
])
    .then(([windPowerData, sahkotinData, npfData]) => {
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

        // Find the last timestamp in Sähkötin data (actual prices)
        var lastSahkotinTimestamp = Math.max(...sahkotinData.map(item => item[0]));
        console.log("End of Sähkötin data; next showing prediction data from:", 
            new Date(lastSahkotinTimestamp).toString());
            
        // Prepare the prediction data for dates after Sähkötin data ends
        var npfSeriesData = npfData
            .map(item => [item[0], item[1]])
            .filter(item => item[0] > lastSahkotinTimestamp);

        // Filter Sähkötin data for the same time range as windPowerData
        var sahkotinPriceData = sahkotinData.filter(item => item[0] >= todayTimestamp);
        
        // Combine Sähkötin (actual) and NPF (predicted) price data
        var combinedPriceData = [...sahkotinPriceData, ...npfSeriesData];

        // Create custom options for wind power chart
        windPowerChart.setOption({
            title: { text: ' ' },
            legend: { show: false },
            tooltip: {
                trigger: 'axis',
                formatter: function(params) {
                    var weekdays = ['su', 'ma', 'ti', 'ke', 'to', 'pe', 'la'];
                    var date = new Date(params[0].axisValue);
                    
                    var weekday = weekdays[date.getDay()];
                    var day = date.getDate();
                    var month = date.getMonth() + 1;
                    var hours = ("0" + date.getHours()).slice(-2);
                    var minutes = ("0" + date.getMinutes()).slice(-2);
                    
                    var formattedDateString = `${weekday} ${day}.${month}. klo ${hours}:${minutes}`;
                    var result = formattedDateString + '<br/>';
                    
                    params.forEach(function(item) {
                        if (item.seriesType !== 'line' && item.seriesType !== 'bar') return;
                        
                        var valueRounded = item.value[1] !== undefined ? item.value[1].toFixed(1) : '';
                        var unitLabel = item.seriesName === 'Tuulivoima (GW)' ? 'GW' : '¢/kWh';
                        result += item.marker + " " + item.seriesName + ': ' + valueRounded + ' ' + unitLabel + '<br/>';
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
                        var date = new Date(value);
                        var weekdays = ['su', 'ma', 'ti', 'ke', 'to', 'pe', 'la'];
                        var weekday = weekdays[date.getDay()];
                        return weekday;
                    }
                },
                axisTick: {
                    alignWithLabel: true,
                    interval: 0
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
                    name: '¢/kWh',
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
                    // For wind power
                    show: false,
                    seriesIndex: 1,
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
                {
                    // For price
                    show: false,
                    seriesIndex: 0,
                    pieces: [
                        { gt: 0, color: '#AEB6BF' }
                    ],
                    outOfRange: {
                        color: '#999'
                    }
                }
            ],
            series: [
                {
                    name: 'Hinta',
                    type: 'bar',
                    barWidth: '40%',
                    data: combinedPriceData,
                    yAxisIndex: 1,
                    z: 1,
                    itemStyle: {
                        opacity: 0.3
                    }
                },
                {
                    name: 'Tuulivoima (GW)',
                    type: 'line',
                    data: windPowerSeriesData,
                    symbol: 'none',
                    lineStyle: {
                        type: 'solid',
                        width: 1.5
                    },
                    step: 'start',
                    areaStyle: { 
                        color: 'rgba(135, 206, 250, 0.2)' // skyblue
                    },
                    opacity: 0.9,
                    z: 2,
                    markLine: createCurrentTimeMarkLine()
                }
            ]
        });
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

// Variables to store original chart data
let originalData = [];
let currentAveragePeriod = 3;
let sahkotinOriginalData = [];

// ==========================================================================
// Toggle button event handlers
// ==========================================================================

document.addEventListener('DOMContentLoaded', function() {
    const toggleButtons = document.querySelectorAll('.history-toggle button');
    
    toggleButtons.forEach(button => {
        button.addEventListener('click', function() {
            // Remove active class from all buttons
            toggleButtons.forEach(btn => btn.classList.remove('active'));
            
            // Add active class to clicked button
            this.classList.add('active');
            
            // Get the moving average period from data attribute
            currentAveragePeriod = parseInt(this.getAttribute('data-period'));
            
            // Apply time binning to chart data
            applyMovingAverageToChart(currentAveragePeriod);
        });
    });
});

// Function to apply time binning to all series in the chart
function applyMovingAverageToChart(hours) {
    // Skip if no original data available yet
    if (!originalData.length) return;

    const option = historyChart.getOption();
    
    // Apply time binning to each series except the last one (which is the marker)
    for (let i = 0; i < originalData.length; i++) {
        // Apply time binning to the series data
        const binnedData = calculateTimeBins(originalData[i], hours);
        
        // Update the series data in the chart
        if (option.series[i]) {
            option.series[i].data = binnedData;
        }
    }
    
    // Apply time binning specifically to the Nordpool series
    const seriesIndex = option.series.findIndex(s => s.name === 'Nordpool');
    if (seriesIndex >= 0) {
        const binnedData = calculateTimeBins(sahkotinOriginalData, hours);
        option.series[seriesIndex].data = binnedData;
    }

    // Update the chart with the new data
    historyChart.setOption(option, false, false);
}

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

    const series = cleanedData.map((seriesData, index) => {
        // Calculate opacity with a more dramatic fade for older predictions
        // const opacityValue = index === 0 ? 0.9 : Math.max(0.5, 0.95 - (index * 0.1));
        const opacityValue = index === 0 ? 0.8 : 0.15;
        
        return {
            name: index === 0 ? "Uusin" : `${0 - index} pv sitten`,
            type: 'line',
            data: seriesData.map(item => [item[0], item[1]]),
            symbol: 'none',
            step: 'start',
            lineStyle: {
                width: index === 0 ? 2 : 2,
                type: index === 0 ? 'solid' : 'solid',
                opacity: opacityValue
            },
            color: 'dodgerblue'
        };
    });

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
    
    // Add zoom controls to the history chart
    historyChartOptions.dataZoom = [
        {
            type: 'slider',
            xAxisIndex: 0,
            start: 25,
            end: 100,
            bottom: 10,
            height: 30
        },
        {
            type: 'inside',
            xAxisIndex: 0,
            start: 25,
            end: 100
        }
    ];

    historyChart.setOption(historyChartOptions);
    console.log("setupHistoryChart found", series.length, "snapshots");
    originalData = cleanedData.map(seriesData => seriesData.map(item => [item[0], item[1]]));
    return series.length;
}

function addSahkotinDataToChart(sahkotinData) {
    // Store original data for rolling average calculations
    const originalSahkotinData = [...sahkotinData];
    
    const sahkotinSeries = {
        name: 'Nordpool',
        type: 'line',
        data: sahkotinData,
        symbol: 'none',
        step: 'start',
        lineStyle: {
            type: 'solid',
            width: 2,
            opacity: 0.9
        },
        color: 'orange',
    };
    
    historyChart.setOption({
        series: historyChart.getOption().series.concat(sahkotinSeries)
    });
    
    // Apply the current average period if one is already selected
    if (currentAveragePeriod > 0) {
        // Find the Nordpool series in the chart options
        const options = historyChart.getOption();
        const seriesIndex = options.series.findIndex(s => s.name === 'Nordpool');
        
        if (seriesIndex >= 0) {
            // Apply time binning only to the Nordpool series
            const binnedData = calculateTimeBins(originalSahkotinData, currentAveragePeriod);
            options.series[seriesIndex].data = binnedData;
            historyChart.setOption(options, false, false);
        }
    }
    
    // Store the original Sähkötin data for future toggle operations
    sahkotinOriginalData = originalSahkotinData;
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
            
            // Apply the default binning after adding Sahkotin data
            applyMovingAverageToChart(currentAveragePeriod);
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

