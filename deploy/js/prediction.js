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
var scaledPriceUrl = `${baseUrl}/prediction_scaled.json`; // Add URL for scaled prices
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
    fetch(scaledPriceUrl)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error ${response.status}`);
            }
            return response.text();
        })
        .then(text => {
            try {
                return text ? JSON.parse(text) : [];
            } catch (e) {
                console.warn('Failed to parse scaled price data JSON:', e);
                return [];
            }
        })
        .catch(e => { 
            console.warn('Failed to fetch or parse scaled price data:', e); 
            return []; 
        }),
    fetch(`${sahkotinUrl}?${sahkotinParams}`).then(r => r.text())
])
    .then(([npfData, scaledPriceData, sahkotinCsv]) => {
        // Process Sähkötin data
        var sahkotinSeriesData = sahkotinCsv.split('\n').slice(1).map(line => {
            var [timestamp, price] = line.split(',');
            var parsedTime = new Date(timestamp).getTime();
            var localTime = new Date(parsedTime).toString();
            console.log(`Sähkötin timestamp: ${localTime}, Price: ${parseFloat(price)} ¢/kWh`);
            return [parsedTime, parseFloat(price)];
        });

        // Find the last timestamp in Sähkötin data
        var lastSahkotinTimestamp = Math.max(...sahkotinSeriesData.map(item => item[0]));
        console.log("End of Sähkötin data for today; displaying the Nordpool prediction data from:", 
            new Date(lastSahkotinTimestamp).toString());
        
        // Include one hour from the prediction data that overlaps with the last hour of Sähkötin data
        // to ensure continuity in the chart
        const oneHourInMilliseconds = 60 * 60 * 1000;
        const overlapThreshold = lastSahkotinTimestamp - oneHourInMilliseconds;

        // Prepare NPF series data
        var npfSeriesData = npfData
            .map(item => [item[0], item[1]])
            .filter(item => item[0] > overlapThreshold); // Include one overlapping hour

        // Debug logs
        npfSeriesData.forEach(item => {
            var localTime = new Date(item[0]).toString();
            console.log(`Prediction timestamp: ${localTime}, Price: ${item[1]} ¢/kWh`);
        });

        // Create a map of timestamps to predicted prices for later reference
        const priceByTimestamp = {};
        npfSeriesData.forEach(item => {
            priceByTimestamp[item[0]] = item[1];
        });

        // Prepare scaled price series data
        var scaledPriceSeriesData = scaledPriceData
            // Spike hours get a small red bar on the timeline
            .map(item => [item[0], item[1] !== null ? -0.25 : null])
            .filter(item => item[0] > overlapThreshold); // Use same threshold as regular predictions, keep nulls for gaps

        console.log("Scaled Price Data loaded:", scaledPriceSeriesData.length, "data points");

        // Create chart options
        const chartOptions = createBaseChartOptions({
            legend: {
                data: [
                    {
                        name: 'Nordpool', 
                        icon: 'circle',
                        itemStyle: {
                            color: 'lime'
                        }
                    },
                    {
                        name: getLocalizedText('forecast'),
                        icon: 'circle',
                        itemStyle: {
                            color: 'skyblue'
                        }
                    }, 
                    {
                        name: getLocalizedText('scaled_price'),
                        // Specify the desired icon shape
                        icon: 'circle', 
                        // Specify the desired color for the legend item
                        itemStyle: {
                            color: 'crimson' 
                        },
                    }
                ],
                right: 16,
                selected: {
                    'Nordpool': true,
                    [getLocalizedText('forecast')]: true,
                    [getLocalizedText('scaled_price')]: true
                }
            },
            tooltipFormatter: createTooltipFormatter(),
            visualMap: [
                {
                    // For realized price
                    show: false,
                    seriesIndex: [3],
                    top: 50,
                    right: 10,
                    pieces: [
                        { lte: 5, color: 'lime', opacity: 1.0 },
                        { gt: 5, lte: 10, color: 'limegreen', opacity: 1.0 },
                        { gt: 10, lte: 15, color: 'gold', opacity: 1.0 },
                        { gt: 15, lte: 20, color: 'darkorange', opacity: 1.0 },
                        { gt: 20, lte: 30, color: 'red', opacity: 1.0 },
                        { gt: 30, color: 'darkred', opacity: 1.0 }
                    ],
                    outOfRange: { color: '#999', opacity: 1.0 }
                },
                {
                    // For predicted price
                    show: false,
                    seriesIndex: [1],
                    top: 50,
                    right: 10,
                    pieces: [
                        { lte: 5, color: 'skyblue', opacity: 1.0 },
                        { gt: 5, lte: 10, color: 'deepskyblue', opacity: 1.0 },
                        { gt: 10, lte: 15, color: 'dodgerblue', opacity: 1.0 },
                        { gt: 15, lte: 20, color: 'blue', opacity: 1.0 },
                        { gt: 20, lte: 30, color: 'darkblue', opacity: 1.0 },
                        { gt: 30, color: 'midnightblue', opacity: 1.0 }
                    ],
                    outOfRange: { color: '#999', opacity: 1.0 }
                }
            ],
            series: [
                {
                    // Background bar for prediction data
                    name: 'Ennuste BG',
                    type: 'bar',
                    data: npfSeriesData,
                    barWidth: '40%',
                    itemStyle: {
                        color: 'deepskyblue',
                        opacity: 0.10
                    },
                    silent: true,
                    z: 1,
                    tooltip: {
                        show: false
                    }
                },
                {
                    name: getLocalizedText('forecast'),
                    type: 'line',
                    data: npfSeriesData,
                    symbol: 'none',
                    step: 'middle',
                    lineStyle: {
                        width: 1.5,
                        type: 'solid'
                    },
                    opacity: 1.0,
                    z: 3
                },
                {
                    // Background bar for realized price data
                    name: 'Nordpool BG',
                    type: 'bar',
                    data: sahkotinSeriesData,
                    barWidth: '40%',
                    itemStyle: {
                        color: 'lime',
                        opacity: 0.10
                    },
                    silent: true,
                    z: 1,
                    tooltip: {
                        show: false
                    }
                },
                {
                    name: 'Nordpool',
                    type: 'line',
                    data: sahkotinSeriesData,
                    symbol: 'none',
                    step: 'middle',
                    lineStyle: {
                        width: 1.5,
                        type: 'solid'
                    },
                    opacity: 1.0,
                    z: 3
                },
                {
                    name: getLocalizedText('scaled_price'),
                    type: 'line',
                    data: scaledPriceSeriesData.map(item => [item[0], null]),
                    markPoint: {
                        symbol: 'triangle',  // Options: 'circle', 'rect', 'triangle', 'diamond', 'pin', 'arrow'
                        symbolSize: [4, 4],
                        symbolRotate: 0,
                        itemStyle: {
                            color: 'crimson'
                        },
                        data: scaledPriceSeriesData
                            .filter(item => {
                                // Only show triangles for hours with both a spike risk AND a price > 5 cents
                                return item[1] !== null && priceByTimestamp[item[0]] > 8;
                            })
                            .map(item => ({
                                coord: [item[0], 0.1],
                                value: ''
                            }))
                    },
                    tooltip: {
                        show: false
                    },
                    z: 5
                },
                {
                    type: 'line',
                    markLine: createCurrentTimeMarkLine(),
                    z: 4
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
