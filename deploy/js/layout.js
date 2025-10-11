//#region layout
// ==========================================================================
// Window resize handling and chart adjustments
// ==========================================================================

window.onresize = function() {
    nfpChart.resize();
    historyChart.resize();
    windPowerChart.resize();
};
