//#region layout
// ==========================================================================
// Window resize handling and chart adjustments
// ==========================================================================

function safeResize(chart) {
    if (chart && typeof chart.resize === 'function') {
        chart.resize();
    }
}

function handleResize() {
    safeResize(window.nfpChart);
    safeResize(window.historyChart);
    safeResize(window.windPowerChart);
}

window.addEventListener('resize', handleResize);
window.onresize = handleResize;
