
if (window.location.hostname === "nordpool-predict-fi.web.app") {
    window.location.href = "https://sahkovatkain.web.app" + window.location.pathname + window.location.search;
}

// Hosted on GitHub, Firebase Hosting, or locally?
var baseUrl;

switch (window.location.hostname) {
    case "":
        baseUrl = "";
        break;
    case "nordpool-predict-fi.web.app":
        baseUrl = "https://nordpool-predict-fi.web.app";
        break;
    case "sahkovatkain.web.app":
        baseUrl = "https://sahkovatkain.web.app";
        break;
    default:
        baseUrl = "https://raw.githubusercontent.com/vividfog/nordpool-predict-fi/main/deploy";
}

//////////////////////////////////////////////////////////////////////////
// Fetch the narration text from the Markdown file
fetch(`${baseUrl}/narration.md`)
    .then(response => {
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        return response.text();
    })
    .then(text => {
        // LLM generated text in quotes
        document.getElementById('narration').innerHTML = marked.parse("\"" + text + "\"");
    })
    .catch(error => console.error('Fetching Markdown failed:', error));

//////////////////////////////////////////////////////////////////////////
// eCharts code for PREDICTION chart, including data from Sähkötin.fi
var nfpChart = echarts.init(document.getElementById('predictionChart'));

// Calculate start and end dates for Sähkötin
var startDate = addDays(new Date(), -2).toISOString();
var endDate = addDays(new Date(), 2).toISOString();

// URLs for the datasets
var npfUrl = `${baseUrl}/prediction.json`; // Using your existing baseUrl for NPF data
var sahkotinUrl = 'https://sahkotin.fi/prices.csv';
var sahkotinParams = new URLSearchParams({
    fix: 'true',
    vat: 'true',
    start: startDate,
    end: endDate,
});

// Helper function to calculate date ranges
function addDays(date, days) {
    var result = new Date(date);
    result.setHours(0, 0, 0, 0);
    result.setDate(result.getDate() + days);
    return result;
}

// Fetch the data and display the chart
Promise.all([
    fetch(npfUrl).then(r => r.json()), // Fetch NPF data
    fetch(`${sahkotinUrl}?${sahkotinParams}`).then(r => r.text()) // Fetch Sähkötin data
])
    .then(([npfData, sahkotinCsv]) => {
        // Prepare NPF series data
        var npfSeriesData = npfData.map(item => [item[0], item[1]]);

        // Prepare Sähkötin series data
        var sahkotinSeriesData = sahkotinCsv.split('\n').slice(1).map(line => {
            var [timestamp, price] = line.split(',');
            return [new Date(timestamp).getTime(), parseFloat(price)];
        });

        // Define the chart option with both series
        nfpChart.setOption({
            title: {
                text: ' '
            },
            legend: {
                data: ['Nordpool', 'Ennuste'],
                right: 16
            },
            tooltip: {
                trigger: 'axis',
                formatter: function (params) {
                    var result = params[0].axisValueLabel + '<br/>';
                    params.forEach(function (item) {
                        // Round the value to one decimal place
                        var valueRounded = item.value[1].toFixed(1);
                        result += item.marker + " " + item.seriesName + ': ' + valueRounded + ' ¢/kWh<br/>';
                    });
                    return result;
                }
            },
            xAxis: {
                type: 'time',
                boundaryGap: false,
                axisLabel: {
                    formatter: function (value) {
                        var date = new Date(value);
                        var weekdays = ['su', 'ma', 'ti', 'ke', 'to', 'pe', 'la'];
                        var year = date.getFullYear();
                        var day = ("0" + date.getDate()).slice(-2);
                        var month = date.getMonth() + 1;  // add 1 since getMonth() starts from 0
                        var weekday = weekdays[date.getDay()];

                        return weekday + ' ' + day + '.';
                    }
                }
            },
            yAxis: {
                type: 'value',
                name: '¢/kWh ALV24',
                nameLocation: 'end',
                nameGap: 20,
                max: value => Math.ceil(value.max / 10) * 10,
                nameTextStyle: {
                    fontWeight: 'regular'
                },
                axisLabel: {
                    formatter: function (value) {
                        // Round the cents to one decimal place
                        return value.toFixed(0);
                    }
                }
            },

            // Set gradient colors for the realized price
            visualMap: [{
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
                outOfRange: {
                    color: '#999'
                }
            },

            // Set gradient colors for the predicted price
            {
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
                outOfRange: {
                    color: '#999'
                }
            }],

            // Data series
            series: [
                {
                    // Prediction
                    name: 'Ennuste',
                    type: 'line',
                    data: npfSeriesData,
                    symbol: 'none',
                    lineStyle: {
                        type: 'dotted',
                        width: 3
                    },
                },
                {
                    // Realized
                    name: 'Nordpool',
                    type: 'line',
                    data: sahkotinSeriesData,
                    symbol: 'none',
                    step: 'middle',
                },
                {
                    // MarkLine for current time
                    type: 'line',
                    markLine: {
                        // Hides the symbol at the end of the line
                        symbol: 'none',
                        label: {
                            formatter: function () {
                                let currentTime = new Date();
                                let hours = currentTime.getHours();
                                let minutes = currentTime.getMinutes();

                                hours = hours < 10 ? '0' + hours : hours;
                                minutes = minutes < 10 ? '0' + minutes : minutes;
                                // This will be local time 24 hour formatted string
                                return 'klo ' + hours + ':' + minutes;
                            },
                            position: 'end'
                        },
                        lineStyle: {
                            type: 'dotted',
                            color: 'skyblue',
                            width: 1.5
                        },
                        data: [
                            {
                                // Current time as the position for the line
                                xAxis: new Date().getTime()
                            }
                        ]
                    }
                }
            ]
        });

        // Match the time axis of the two series
        var npfSeriesData = npfData.map(item => [item[0] * 1000, item[1]]);

        var sahkotinSeriesData = sahkotinCsv.split('\n').slice(1).map(line => {
            var [timestamp, price] = line.split(',');
            return [new Date(timestamp).getTime(), parseFloat(price)];
        });
    })
    .catch(error => {
        console.error('Error fetching or processing data:', error);
    });

// Function to update the vertical marker position
function updateMarkerPosition() {
    console.log('marker position update...');
    var currentTime = new Date().getTime(); // Get current time in milliseconds

    // Update the markLine data for the current time marker
    var option = nfpChart.getOption(); // Get the current chart options to overwrite
    option.series.forEach((series) => {
        if (series.markLine) {
            series.markLine.data = [
                {
                    xAxis: currentTime
                }
            ];
        }
    });

    // Set the updated option to the chart without not merging
    nfpChart.setOption(option, false, false);
}

// Call the updateMarkerPosition function to update the marker
setInterval(updateMarkerPosition, 10000); // 10000 milliseconds = check every 10 seconds

// END: eCharts code predictions

//////////////////////////////////////////////////////////////////////////
// START: eCharts code for historyChart

// Make sure ECharts is loaded and the DOM element exists
var historyChart = echarts.init(document.getElementById('historyChart'));

// Utility function to generate date strings for the past 14 days
function getPastDateStrings(count) {
    const dates = [];
    for (let i = 0; i < count; i++) {
        const d = new Date();
        d.setDate(d.getDate() - i);
        dates.push(d.toISOString().split('T')[0]); // Format YYYY-MM-DD
    }
    return dates;
}

// Construct URLs for fetching historical data
const dateStrings = getPastDateStrings(14);
const historicalUrls = dateStrings.map(date => `${baseUrl}/prediction_snapshot_${date}.json`);
// console.log("Datestrings: ", historicalUrls);

// Fetch and process historical data from the constructed URLs
function fetchHistoricalData(urls) {
    // console.log("fetchHistoricalData trying: ", urls);
    return Promise.all(urls.map(url =>
        fetch(url).then(response => {
            if (!response.ok) {
                // DEBUG only, not all files are supposed to exist
                // throw new Error(`Failed to fetch ${url}: ${response.statusText}`);
            }
            return response.json();
        }).catch(error => {
            // DEBUG only, not all files are supposed to exist
            // console.error("Fetching error for URL:", url, error);
            return null; // Return null for snapshots that don't (yet) exist
        })
    ));
}

// Function to set up the history chart with fetched data
function setupHistoryChart(data) {
    const cleanedData = data.filter(item => item !== null).slice(1);
    console.log("setupHistoryChart found these snapshots: ", cleanedData);

    const series = cleanedData.map((seriesData, index) => ({
        name: index === 0 ? "Uusin" : `${0 - index} pv sitten`,
        type: 'line',
        data: seriesData.map(item => [item[0], item[1]]),
        symbol: 'none',
        lineStyle: {
            width: index === 0 ? 2 : 1,
            type: index === 0 ? 'solid' : 'dotted'
        },
        color: 'dodgerblue',
        opacity: Math.pow(0.9, index),
    }));

    // Add a separate series item for the markLine
    series.push({
        type: 'line',
        data: [], // No line data needed, markLine will be used instead
        markLine: {
            symbol: 'none',
            label: {
                formatter: 'Nyt',
                position: 'end'
            },
            lineStyle: {
                type: 'dotted',
                color: 'skyblue',
                width: 1.5
            },
            data: [
                {
                    xAxis: new Date().getTime()
                }
            ]
        }
    });

    historyChart.setOption({
        tooltip: {
            trigger: 'axis',
            formatter: function (params) {
                var result = params[0].axisValueLabel + '<br/>';
                params.forEach(function (item) {
                    if (item.seriesType === 'line') {
                        var valueRounded = item.value[1] ? item.value[1].toFixed(1) : '';
                        result += item.marker + " " + item.seriesName + ': ' + valueRounded + ' ¢/kWh<br/>';
                    }
                });
                return result;
            }
        },
        xAxis: {
            type: 'time',
            boundaryGap: false,
            axisLabel: {
                interval: 0,
                formatter: function (value) {
                    var date = new Date(value);
                    return date.toLocaleDateString('fi-FI');
                },
                rotate: 45,
            }
        },
        yAxis: {
            type: 'value',
            name: '¢/kWh ALV24',
            nameLocation: 'end',
            nameGap: 20,
            max: value => Math.ceil(value.max / 10) * 10,
            nameTextStyle: {
                fontWeight: 'regular'
            },
            axisLabel: {
                formatter: function (value) {
                    return value.toFixed(0);
                }
            }
        },
        series: series
    });

    console.log("setupHistoryChart found", series.length, "snapshots");
    return series.length;
}


function setupSahkotinData(nrSeries) {
    // Assuming you've already calculated the start and end dates based on your requirement
    const startDate = getPastDateStrings(7).pop(); // Gets the earliest date from your range
    var endDate = addDays(new Date(), 2).toISOString();

    const sahkotinUrl = 'https://sahkotin.fi/prices.csv';
    const sahkotinParams = new URLSearchParams({
        fix: 'true',
        vat: 'true',
        start: startDate,
        end: endDate,
    });

    // Fetch Sähkötin data
    fetch(`${sahkotinUrl}?${sahkotinParams}`)
        .then(response => response.text())
        .then(csvData => {
            const sahkotinData = processSahkotinCsv(csvData);
            // Add Sähkötin data to chart
            addSahkotinDataToChart(sahkotinData, nrSeries);
        })
        .catch(error => console.error("Error fetching Sähkötin data:", error));
}

function processSahkotinCsv(csvData) {
    // Convert CSV to format expected by ECharts ([date, value] pairs)
    const lines = csvData.split('\n').slice(1); // Skip header
    return lines.map(line => {
        const [timestamp, price] = line.split(',');
        // Convert timestamp to time and price to float
        return [new Date(timestamp).getTime(), parseFloat(price)];
    });
}

function addSahkotinDataToChart(sahkotinData, nrSeries) {
    const sahkotinSeries = {
        name: 'Nordpool',
        type: 'line',
        data: sahkotinData,
        symbol: 'none',
        step: 'middle',
        lineStyle: {
            type: 'solid',
            width: 2
        },
        color: 'orange'
    };

    // Assuming 'historyChart' is accessible here; if not, you might need to make it globally accessible
    historyChart.setOption({
        series: historyChart.getOption().series.concat(sahkotinSeries)
    });
}


// Fetch historical data and set up the chart
fetchHistoricalData(historicalUrls).then(data => {
    var nrSeries = setupHistoryChart(data);
    setupSahkotinData(nrSeries);
}).catch(error => console.error("Error in chart setup:", error));

// END: eCharts code for historyChart

// Resize the chart when the window is resized
window.onresize = function () {
    nfpChart.resize();
    historyChart.resize();
}