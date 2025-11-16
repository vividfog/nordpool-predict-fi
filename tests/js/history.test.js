import { beforeAll, describe, expect, it, vi } from 'vitest';
import { createEchartsMock, flushPromises, loadScript, setPathname, buildPriceCsv, setPredictionStorePayload } from './utils';

const HOUR = 60 * 60 * 1000;

describe('deploy/js/history.js', () => {
  beforeAll(async () => {
    setPathname('/index.html');
    loadScript('deploy/js/config.js');

    document.body.innerHTML = `
      <div id="historyChart"></div>
      <div class="history-toggle"><button data-period="3"></button></div>
      <select id="pruneDropdown"></select>
    `;

    const chartMock = createEchartsMock();
    chartMock.getOption.mockReturnValue({
      series: [
        { data: [] },
        { data: [] },
        { data: [] },
        { data: [], name: 'Nordpool' }
      ]
    });

    globalThis.echarts = {
      init: () => chartMock
    };

    const sampleSeries = Array.from({ length: 6 }, (_, idx) => [
      Date.UTC(2025, 0, 1) + idx * HOUR,
      10 + idx
    ]);

    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock;

    fetchMock.mockImplementation(url => {
      const urlString = String(url);
      if (urlString.includes('prices.csv')) {
        return Promise.resolve({
          ok: true,
          text: () => Promise.resolve(buildPriceCsv(sampleSeries))
        });
      }
      if (urlString.includes('prediction_snapshot')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(sampleSeries)
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(sampleSeries)
      });
    });

    loadScript('deploy/js/history.js');
    await flushPromises(4);
  });

  it('prunes data based on hour window', () => {
    const base = Date.UTC(2025, 0, 1);
    const data = [
      [base, 1],
      [base + HOUR, 2],
      [base + 2 * HOUR, 3],
      [base + 3 * HOUR, 4]
    ];
    expect(pruneData(data, '2').length).toBe(2);
    expect(pruneData(data, 'max').length).toBe(4);
  });

  it('processes Sahkotin CSV data', () => {
    const sahkotinCsv = buildPriceCsv([[Date.UTC(2025, 0, 1), 7]]);
    const parsed = processSahkotinCsv(sahkotinCsv);
    const finite = parsed.filter(([, value]) => Number.isFinite(value));
    expect(finite).toEqual([[Date.UTC(2025, 0, 1), 7]]);
  });

  it('sets up history chart and stores originals', () => {
    const base = Date.UTC(2025, 0, 1);
    const dataset = [
      null,
      [
        [base, 10],
        [base + HOUR, 12]
      ]
    ];
    const count = setupHistoryChart(dataset, '120');
    expect(count).toBeGreaterThan(0);
    const applied = window.historyChart.setOption.mock.calls.at(-1)[0];
    expect(applied.series.length).toBeGreaterThan(0);
  });

  it('adds Sahkotin data and applies averaging', () => {
    const chartOptions = window.historyChart.getOption();
    chartOptions.series.push({ name: 'Nordpool', data: [] });
    window.historyChart.getOption.mockReturnValue(chartOptions);

    const sahkotinSeries = [
      [Date.UTC(2025, 0, 1), 5],
      [Date.UTC(2025, 0, 1, 1), 6]
    ];
    addSahkotinDataToChart(sahkotinSeries);
    const updated = window.historyChart.setOption.mock.calls.at(-1)[0];
    expect(updated.series.some(series => series.name === 'Nordpool')).toBe(true);
  });

  it('guards refreshes behind prediction token changes', async () => {
    const fetchHistoricalSpy = vi.spyOn(window, 'fetchHistoricalData').mockResolvedValue([[ [0, 1] ]]);
    const setupSpy = vi.spyOn(window, 'setupHistoryChart').mockReturnValue(1);
    const sahkoSpy = vi.spyOn(window, 'setupSahkotinData').mockResolvedValue();

    setPredictionStorePayload({ generatedAt: 0 });
    await flushPromises(4);
    expect(fetchHistoricalSpy).not.toHaveBeenCalled();

    fetchHistoricalSpy.mockClear();
    setupSpy.mockClear();
    sahkoSpy.mockClear();

    setPredictionStorePayload({ generatedAt: Number.MAX_SAFE_INTEGER });
    await flushPromises(4);
    expect(fetchHistoricalSpy).toHaveBeenCalledTimes(1);
    expect(setupSpy).toHaveBeenCalledTimes(1);
    expect(sahkoSpy).toHaveBeenCalledTimes(1);

    fetchHistoricalSpy.mockRestore();
    setupSpy.mockRestore();
    sahkoSpy.mockRestore();
  });
});
