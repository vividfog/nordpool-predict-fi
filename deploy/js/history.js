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
let currentPruneOption = '120'; // Default to 5-day lookahead
let sahkotinOriginalData = [];

// ==========================================================================
// Toggle button event handlers
// ==========================================================================

document.addEventListener('DOMContentLoaded', function() {
    applyTranslations();

    const toggleButtons = document.querySelectorAll('.history-toggle button');
    const pruneDropdown = document.getElementById('pruneDropdown');
    
    toggleButtons.forEach(button => {
        button.addEventListener('click', function() {
            // Remove active class from all buttons
            toggleButtons.forEach(btn => btn.classList.remove('active'));
            
            // Add active class to clicked button
            this.classList.add('active');
            
            // Get the moving average period from data attribute
            currentAveragePeriod = parseInt(this.getAttribute('data-period'));
            
            // Apply time binning to chart data
            applyPruningAndAveragingToChart();
        });
    });

    pruneDropdown.addEventListener('change', function() {
        currentPruneOption = this.value;
        applyPruningAndAveragingToChart();
    });
});

// Apply pruning and then moving average to the chart
function applyPruningAndAveragingToChart() {
    if (!originalData.length) return;

    const option = historyChart.getOption();
    
    // Apply pruning first
    const prunedData = originalData.map(series => {
        return pruneData(series, currentPruneOption);
    });

    // Then apply moving average to the pruned data
    for (let i = 0; i < prunedData.length; i++) {
        const averagedData = calculateTimeBins(prunedData[i], currentAveragePeriod);
        if (option.series[i]) {
            option.series[i].data = averagedData;
        }
    }

    // Nordpool data is not pruned, but it is averaged
    const seriesIndex = option.series.findIndex(s => s.name === 'Nordpool');
    if (seriesIndex >= 0) {
        const averagedNordpoolData = calculateTimeBins(sahkotinOriginalData, currentAveragePeriod);
        option.series[seriesIndex].data = averagedNordpoolData;
    }

    historyChart.setOption(option, false, false);
}

// ==========================================================================
// Historical data fetching and processing
// ==========================================================================

function pruneData(data, option) {
    if (option === 'max' || !data || data.length === 0) {
        return data;
    }

    const hours = parseInt(option);
    if (isNaN(hours)) {
        return data;
    }

    const startTime = data[0][0];
    const cutoffTime = startTime + hours * 60 * 60 * 1000;
    
    return data.filter(item => item[0] < cutoffTime);
}

function fetchHistoricalData(urls) {
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
                    // Only filter out data older than the day after the snapshot
                    jsonData = jsonData.filter(item => item[0] >= cutoffMs);

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

function setupHistoryChart(data, pruneOption) {
    const cleanedData = data.filter(item => item !== null).slice(1);
    console.log("setupHistoryChart found these snapshots: ", cleanedData);

    const series = cleanedData.map((seriesData, index) => {
        // Prune data before rendering
        const prunedData = pruneData(seriesData, pruneOption);

        // Calculate opacity for older series
        // const opacityValue = index === 0 ? 0.9 : Math.max(0.5, 0.95 - (index * 0.1));
        const opacityValue = index === 0 ? 0.4 : 0.4;
        
        return {
            name: index === 0 ? getLocalizedText('latest') : `${index} ${getLocalizedText('daysAgo')}`,
            type: 'line',
            data: prunedData.map(item => [item[0], item[1]]),
            symbol: 'none',
            step: 'middle',
            lineStyle: {
                width: index === 0 ? 1.5 : 1.5,
                type: index === 0 ? 'dotted' : 'dotted',
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
        series: series,
        isHistoryChart: true // Flag to use weekly grid lines
    });
    
    // Add zoom controls to the history chart
    historyChartOptions.dataZoom = [
        {
            type: 'slider',
            xAxisIndex: 0,
            start: 33,
            end: 100,
            bottom: 10,
            height: 30
        },
        {
            type: 'inside',
            xAxisIndex: 0,
            start: 33,
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
        step: 'middle',
        lineStyle: {
            type: 'solid',
            width: 2,
            opacity: 0.8
        },
        color: 'limegreen',
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
            applyPruningAndAveragingToChart();
        })
        .catch(error => console.error("Error fetching Sähkötin data:", error));
}

//#region init
// ==========================================================================
// Initialize history chart with fetched data
// ==========================================================================

fetchHistoricalData(historicalUrls)
    .then(data => {
        setupHistoryChart(data, currentPruneOption);
        setupSahkotinData();
    })
    .catch(error => console.error("Error in chart setup:", error));

// Setup interval for marker updates
setInterval(() => updateMarkerPosition(historyChart), 10000);
