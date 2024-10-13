if (window.location.hostname === "nordpool-predict-fi.web.app") {
    window.location.href = "https://sahkovatkain.web.app" + window.location.pathname + window.location.search;
}

// Hosted on GitHub, Firebase Hosting, or locally?
var baseUrl;

switch (window.location.hostname) {
    case "":
    case "localhost":
        baseUrl = "http://localhost:5005";
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
        document.getElementById('narration').innerHTML = marked.parse(text);
    })
    .catch(error => console.error('Fetching Markdown failed:', error));

//////////////////////////////////////////////////////////////////////////
// eCharts code for PREDICTION chart, including data from Sähkötin.fi
var nfpChart = echarts.init(document.getElementById('predictionChart'));

// Calculate start and end dates for Sähkötin
var startDate = addDays(new Date(), -2).toISOString();
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

// Helper function to calculate date ranges
function addDays(date, days) {
    var result = new Date(date);
    result.setHours(0, 0, 0, 0);
    result.setDate(result.getDate() + days);
    return result;
}

// Fetch the data from both the prediction and Sähkötin sources and display the chart
Promise.all([
    // Fetch the prediction data from the specified URL and parse it as JSON
    // Note: Prediction data is in UTC
    fetch(npfUrl).then(r => r.json()),
    // Fetch the Sähkötin data, which is in CSV format, and retrieve it as text
    // Note: Sähkötin data is in UTC
    fetch(`${sahkotinUrl}?${sahkotinParams}`).then(r => r.text())
])
    .then(([npfData, sahkotinCsv]) => {
        // Prepare the Sähkötin series data for the chart
        // Split the CSV data into lines, skip the header, and map each line to a data point
        var sahkotinSeriesData = sahkotinCsv.split('\n').slice(1).map(line => {
            // Split each line by comma to separate timestamp and price
            var [timestamp, price] = line.split(',');
            // Parse the timestamp into a JavaScript Date object and convert it to milliseconds
            // Implicit time zone interpretation happens here; assuming UTC
            var parsedTime = new Date(timestamp).getTime();
            // Convert the parsed time to a human-readable string for logging
            // Implicit conversion from UTC to local time happens here
            var localTime = new Date(parsedTime).toString();
            // Log the timestamp and price for debugging purposes
            console.log(`Sähkötin timestamp: ${localTime}, Price: ${parseFloat(price)} ¢/kWh`);
            // Return the parsed time and price as a data point
            return [parsedTime, parseFloat(price)];
        });

        // Align the Sähkötin data to the Nordpool data
        // Determine the last timestamp in the Sähkötin data and subtract 25 hours for overlap (the price data contains the 00-01 hour too)
        var lastSahkotinTimestamp = Math.max(...sahkotinSeriesData.map(item => item[0])) - (25 * 60 * 60 * 1000);
        // Log the adjusted last timestamp for debugging
        // Implicit conversion from UTC to local time happens here
        console.log("End of Sähkötin data for today; displaying the Nordpool prediction data from:", new Date(lastSahkotinTimestamp).toString());

        // Prepare the NPF series data, with one overlapping 24 hour period
        var npfSeriesData = npfData
            // Map each item in the NPF data to a data point
            .map(item => [item[0], item[1]])
            // Filter out data points that are older than the adjusted last Sähkötin timestamp
            .filter(item => item[0] > lastSahkotinTimestamp);

        // Log each prediction timestamp and price for debugging
        npfSeriesData.forEach(item => {
            // Implicit conversion from UTC to local time happens here
            var localTime = new Date(item[0]).toString();
            console.log(`Prediction timestamp: ${localTime}, Price: ${item[1]} ¢/kWh`);
        });

        // Define the chart options, including both the prediction and Sähkötin series
        nfpChart.setOption({
            // Set the chart title (currently empty)
            title: {
                text: ' '
            },
            // Define the legend for the chart, specifying the series names and position
            legend: {
                data: ['Nordpool', 'Ennuste'],
                right: 16
            },
            // Configure the tooltip to display information when hovering over the chart
            tooltip: {
                trigger: 'axis',
                formatter: function (params) {
                    // Define an array of weekday abbreviations for formatting dates
                    var weekdays = ['su', 'ma', 'ti', 'ke', 'to', 'pe', 'la'];
                    // Convert the axis value to a Date object
                    // Implicit conversion from UTC to local time happens here
                    var date = new Date(params[0].axisValue);

                    // Extract and format the date components for display
                    var weekday = weekdays[date.getDay()];
                    var year = date.getFullYear();
                    var month = date.getMonth() + 1;
                    var day = date.getDate();
                    var hours = ("0" + date.getHours()).slice(-2);
                    var minutes = ("0" + date.getMinutes()).slice(-2);
                    var formattedDateString = `${weekday} ${day}.${month}. klo ${hours}`;

                    // Initialize the result string with the formatted date
                    var result = formattedDateString + '<br/>';
                    // Append each series' data to the result string
                    params.forEach(function (item) {
                        var valueRounded = item.value[1].toFixed(1);
                        result += item.marker + " " + item.seriesName + ': ' + valueRounded + ' ¢/kWh<br/>';
                    });

                    // Return the formatted result string for the tooltip
                    return result;
                }
            },

            // Configure the x-axis of the chart
            xAxis: {
                type: 'time',
                boundaryGap: false,
                axisLabel: {
                    formatter: function (value) {
                        // Convert the axis value to a Date object
                        // Implicit conversion from UTC to local time happens here
                        var date = new Date(value);

                        // Define an array of weekday abbreviations for formatting dates
                        var weekdays = ['su', 'ma', 'ti', 'ke', 'to', 'pe', 'la'];
                        // Extract and format the date components for display
                        var year = date.getFullYear();
                        var day = ("0" + date.getDate()).slice(-2);
                        var month = date.getMonth() + 1;
                        var weekday = weekdays[date.getDay()];

                        // Return the formatted date string for the axis label
                        return weekday + ' ' + day + '.';
                    }
                }
            },
            // Configure the y-axis of the chart
            yAxis: {
                type: 'value',
                name: '¢/kWh ALV24',
                nameLocation: 'end',
                nameGap: 20,
                // Set the maximum value of the y-axis to the nearest higher multiple of 10
                max: value => Math.ceil(value.max / 10) * 10,
                nameTextStyle: {
                    fontWeight: 'regular'
                },
                axisLabel: {
                    formatter: function (value) {
                        // Format the axis label value to have no decimal places
                        return value.toFixed(0);
                    }
                }
            },

            // Define the visual map for setting gradient colors based on price ranges
            // This visual map applies to the realized price series
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

            // This visual map applies to the predicted price series
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

            // Define the series for the chart, including both prediction and Sähkötin data
            series: [
                {
                    name: 'Ennuste',
                    type: 'line',
                    data: npfSeriesData,
                    symbol: 'none',
                    lineStyle: {
                        type: 'dotted',
                        width: 2
                    },
                    opacity: 0.9
                },
                {
                    name: 'Nordpool',
                    type: 'line',
                    data: sahkotinSeriesData,
                    symbol: 'none',
                    step: 'middle',
                    opacity: 0.9
                },
                {
                    type: 'line',
                    markLine: {
                        symbol: 'none',
                        label: {
                            formatter: function () {
                                // Get the current time and format it as hours and minutes
                                // Implicit conversion from local time to UTC happens here
                                let currentTime = new Date();
                                let hours = currentTime.getHours();
                                let minutes = currentTime.getMinutes();

                                // Add leading zeros to hours and minutes if necessary
                                hours = hours < 10 ? '0' + hours : hours;
                                minutes = minutes < 10 ? '0' + minutes : minutes;
                                // Return the formatted time string for the mark line label
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
                                // Set the x-axis position of the mark line to the current time
                                // Implicit conversion from local time to UTC happens here
                                xAxis: new Date().getTime()
                            }
                        ]
                    }
                }
            ]
        });
    })
    .catch(error => {
        // Log an error message if there is an issue fetching or processing the data
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
// START: eCharts code for windPowerChart

// Initialize the wind power chart
var windPowerChart = echarts.init(document.getElementById('windPowerChart'));

// Fetch the wind power data from the URL
var windPowerUrl = `${baseUrl}/windpower.json`;

fetch(windPowerUrl)
    .then(response => {
        if (!response.ok) {
            throw new Error('Network response was not ok: ' + response.statusText);
        }
        return response.json();
    })
    .then(windPowerData => {
        console.log("Wind Power Data:", windPowerData); // Log the data for debugging

        // Prepare wind power series data
        var windPowerSeriesData = windPowerData.map(item => [item[0], item[1] / 1000]);
        console.log("Processed Wind Power Series Data:", windPowerSeriesData);

        // Set option for wind power chart
        windPowerChart.setOption({
            title: {
                text: ' '  // Clear the title
            },
            legend: {
                show: false,
                data: ['Tuulivoima (GW)'],
                right: 16
            },
            tooltip: {
                trigger: 'axis',
                formatter: function (params) {
                    var weekdays = ['su', 'ma', 'ti', 'ke', 'to', 'pe', 'la']; // Finnish weekdays
                    var date = new Date(params[0].axisValue);

                    var weekday = weekdays[date.getDay()];
                    var day = date.getDate();
                    var month = date.getMonth() + 1; // Month is zero-based

                    var hours = ("0" + date.getHours()).slice(-2);
                    var minutes = ("0" + date.getMinutes()).slice(-2);

                    var formattedDateString = `${weekday} ${day}.${month}. klo ${hours}:${minutes}`;
                    
                    var result = formattedDateString + '<br/>';
                    params.forEach(function (item) {
                        var valueRounded = item.value[1].toFixed(0); // Display integer GW values
                        result += item.marker + " " + item.seriesName + ': ' + valueRounded + ' GW<br/>';
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
                        var weekday = weekdays[date.getDay()];
                        var day = date.getDate();
                        var month = date.getMonth() + 1;  // add 1 since getMonth() starts from 0
                        return `${weekday} ${day}.${month}.`;
                    }
                }
            },
            yAxis: {
                type: 'value',
                name: 'GW',
                nameLocation: 'end',
                nameGap: 20,
                max: 7, // gigawatts
                nameTextStyle: {
                    fontWeight: 'regular'
                },
                axisLabel: {
                    formatter: function (value) {
                        return value.toFixed(0); // Display without any decimal places
                    }
                }
            },

            // Set wind power gradient colors
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
                        color: 'rgba(135, 206, 250, 0.1)' // skyblue
                    },
                    opacity: 0.9,
                    markLine: {
                        symbol: 'none',
                        label: {
                            formatter: function () {
                                let currentTime = new Date();
                                let hours = currentTime.getHours();
                                let minutes = currentTime.getMinutes();
            
                                hours = hours < 10 ? '0' + hours : hours;
                                minutes = minutes < 10 ? '0' + minutes : minutes;
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
                                xAxis: new Date().getTime()
                            }
                        ]
                    }
                }
            ]
        });
    })
    .catch(error => console.error('Error fetching wind power data:', error));

// Function to update the vertical marker position for windPowerChart
function updateWindMarkerPosition() {
    var currentTime = new Date().getTime(); // Get current time in milliseconds

    // Update the markLine data for the current time marker
    var option = windPowerChart.getOption(); // Get the current chart options to modify
    option.series.forEach((series) => {
        if (series.markLine) {
            series.markLine.data = [
                {
                    xAxis: currentTime
                }
            ];
        }
    });

    // Update the chart with the new option
    windPowerChart.setOption(option, false, false);
}

// Call the update function periodically to update the marker
setInterval(updateWindMarkerPosition, 10000); // Update every 10 seconds

// END: eCharts code for windPowerChart

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
        d.setHours(0, 0, 0, 0); // Set time to midnight local time
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
            width: index === 0 ? 1.5 : 1,
            type: index === 0 ? 'solid' : 'dotted'
        },
        color: 'dodgerblue',
        opacity: Math.pow(0.9, index)-.1
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
    const startDate = getPastDateStrings(14).pop();
    const startDateTime = new Date(startDate);
    startDateTime.setHours(0, 0, 0, 0); // Ensure start time is midnight local time
    const endDate = addDays(new Date(), 2).toISOString();

    const sahkotinUrl = 'https://sahkotin.fi/prices.csv';
    const sahkotinParams = new URLSearchParams({
        fix: 'true',
        vat: 'true',
        start: startDateTime.toISOString(),
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
            width: 1.5
        },
        color: 'orange',
        opacity: 0.9
    };

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
    windPowerChart.resize();
}


