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
        console.log("Wind Power Chart: End of Sähkötin data; next showing prediction data from:", 
            new Date(lastSahkotinTimestamp).toString());
        
        // Overlap disabled for wind power chart: all prices are bars, line continuity not needed
        const overlapThreshold = lastSahkotinTimestamp;
            
        // Filter Sähkötin data for the same time range as windPowerData
        var sahkotinPriceData = sahkotinData
            .filter(item => item[0] >= todayTimestamp);
        
        // Prepare the prediction data for dates after Sähkötin data ends with one hour overlap
        var npfSeriesData = npfData
            .map(item => [item[0], item[1]])
            .filter(item => item[0] > overlapThreshold);

        const localizedPrice = getLocalizedText('price') + ' (¢/kWh)';
        const localizedWindPower = getLocalizedText('windPower');

        // Create chart series for both price data sources
        const sahkotinPriceSeries = {
            name: localizedPrice,
            type: 'bar',
            barWidth: '40%',
            data: sahkotinPriceData,
            yAxisIndex: 1,
            z: 1,
            itemStyle: {
                color: '#AEB6BF',
                opacity: 0.3
            }
        };
        
        const npfPriceSeries = {
            name: localizedPrice,
            type: 'bar',
            barWidth: '40%',
            data: npfSeriesData,
            yAxisIndex: 1,
            z: 1,
            itemStyle: {
                color: '#AEB6BF',
                opacity: 0.3
            }
        };

        // Create custom options for wind power chart
        windPowerChart.setOption({
            title: { text: ' ' },
            grid: {
                left: 8,
                right: 12,
                top: 28,
                bottom: 48,
                containLabel: true
            },
            legend: {
                data: [
                    {
                        name: localizedWindPower,
                        icon: 'circle',
                        itemStyle: {
                            color: 'dodgerblue'
                        }
                    },
                    {
                        name: localizedPrice,
                        icon: 'circle',
                        itemStyle: {
                            color: '#AEB6BF'
                        }
                    }
                ],
                right: 16,
                selected: {
                    [localizedWindPower]: true,
                    [localizedPrice]: true
                }
            },
            tooltip: {
                trigger: 'axis',
                formatter: function(params) {
                    var weekdays = getLocalizedText('weekdays');
                    var date = new Date(params[0].axisValue);
                    
                    var weekday = weekdays[date.getDay()];
                    var day = date.getDate();
                    var month = date.getMonth() + 1;
                    var hours = ("0" + date.getHours()).slice(-2);
                    var minutes = ("0" + date.getMinutes()).slice(-2);
                    
                    // Use dynamic time prefix
                    var timePrefix = getTimePrefix();
                    var formattedDateString = `${weekday} ${day}.${month}. ${timePrefix} ${hours}:${minutes}`;
                    var result = formattedDateString + '<br/>';
                    
                    // Sort params to show wind power first
                    params.sort((a, b) => {
                        if (a.seriesName === localizedWindPower) return -1;
                        if (b.seriesName === localizedWindPower) return 1;
                        return 0;
                    });

                    params.forEach(function(item) {
                        if (item.seriesType !== 'line' && item.seriesType !== 'bar') return;
                        
                        var valueRounded = item.value[1] !== undefined ? item.value[1].toFixed(1) : '';
                        result += item.marker + " " + item.seriesName + ': ' + valueRounded + '<br/>';
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
                        var weekdays = getLocalizedText('weekdays');
                        var weekday = weekdays[date.getDay()];
                        return weekday;
                    }
                },
                axisTick: {
                    alignWithLabel: true,
                    interval: 0
                },
                splitLine: {
                    show: true,
                    lineStyle: {
                        color: 'silver',
                        width: 0.5,
                        type: 'dashed',
                        opacity: 0.40
                    },
                    interval: function(index, value) {
                        const date = new Date(value);
                        return date.getHours() === 0 && date.getMinutes() === 0;
                    }
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
                    seriesIndex: 2,
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
                    // For price - Sähkötin data
                    show: false,
                    seriesIndex: 0,
                    pieces: [
                        { gt: 0, color: '#AEB6BF' }
                    ],
                    outOfRange: {
                        color: '#999'
                    }
                },
                {
                    // For price - NPF data
                    show: false,
                    seriesIndex: 1,
                    pieces: [
                        { gt: 0, color: '#AEB6BF' }
                    ],
                    outOfRange: {
                        color: '#999'
                    }
                }
            ],
            series: [
                sahkotinPriceSeries,
                npfPriceSeries,
                {
                    name: localizedWindPower,
                    type: 'line',
                    data: windPowerSeriesData,
                    symbol: 'none',
                    lineStyle: {
                        type: 'solid',
                        width: 1.5
                    },
                    step: 'middle',
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
