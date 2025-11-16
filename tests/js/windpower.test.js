import { describe, expect, it, vi } from 'vitest';
import { createEchartsMock, flushPromises, loadScript, setPathname, buildPriceCsv, setPredictionStorePayload } from './utils';

const HOUR = 60 * 60 * 1000;

describe('deploy/js/windpower.js', () => {
  it('renders combined wind power and price data', async () => {
    setPathname('/index.html');
    loadScript('deploy/js/config.js');
    document.body.innerHTML = '<div id="windPowerChart"></div>';

    const chart = createEchartsMock();
    globalThis.echarts = { init: () => chart };

    const base = Date.UTC(2025, 0, 1);
    const windData = [
      [base, 1000],
      [base + HOUR, 1200]
    ];
    const sahkotinCsv = buildPriceCsv([
      [base, 6],
      [base + HOUR, 7]
    ]);
    const npfData = [
      [base + 2 * HOUR, 8]
    ];

    const windUrl = `${window.location.origin}/windpower.json`;
    globalThis.sahkotinUrl = 'https://example.com/prices.csv';
    globalThis.sahkotinParams = new URLSearchParams();
    globalThis.npfUrl = 'https://example.com/prediction.json';

    vi.useFakeTimers();
    vi.setSystemTime(new Date(base));

    globalThis.fetch.mockImplementation(url => {
      if (url === windUrl) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(windData)
        });
      }
      if (String(url).includes('prices.csv')) {
        return Promise.resolve({
          ok: true,
          text: () => Promise.resolve(sahkotinCsv)
        });
      }
      if (url === globalThis.npfUrl) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(npfData)
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([])
      });
    });

    loadScript('deploy/js/windpower.js');
    await flushPromises(8);

    expect(chart.setOption).toHaveBeenCalled();
    const option = chart.setOption.mock.calls[0][0];
    expect(option.series.some(series => series.name.includes('Tuulivoima'))).toBe(true);
    vi.useRealTimers();
  });

  it('logs error when fetch fails', async () => {
    setPathname('/index.html');
    loadScript('deploy/js/config.js');
    document.body.innerHTML = '<div id="windPowerChart"></div>';
    const chart = createEchartsMock();
    globalThis.echarts = { init: () => chart };

    globalThis.sahkotinUrl = 'https://example.com/prices.csv';
    globalThis.sahkotinParams = new URLSearchParams();
    globalThis.npfUrl = 'https://example.com/prediction.json';

    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    globalThis.fetch.mockRejectedValue(new Error('fail'));

    loadScript('deploy/js/windpower.js');
    await flushPromises(6);

    expect(errorSpy).toHaveBeenCalled();
  });

  it('only refetches when prediction token increases', async () => {
    setPathname('/index.html');
    loadScript('deploy/js/config.js');
    document.body.innerHTML = '<div id="windPowerChart"></div>';

    const chart = createEchartsMock();
    globalThis.echarts = { init: () => chart };

    const base = Date.UTC(2025, 0, 1);
    const windData = [
      [base, 1000],
      [base + HOUR, 1100]
    ];
    const csv = buildPriceCsv([
      [base, 7],
      [base + HOUR, 8]
    ]);
    const npfData = [
      [base + 2 * HOUR, 9]
    ];

    vi.useFakeTimers();
    vi.setSystemTime(new Date(base));

    globalThis.fetch.mockImplementation(url => {
      const urlString = String(url);
      if (urlString.includes('windpower.json')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(windData) });
      }
      if (urlString.includes('prices.csv')) {
        return Promise.resolve({ ok: true, text: () => Promise.resolve(csv) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve(npfData) });
    });

    loadScript('deploy/js/windpower.js');
    await flushPromises(8);

    globalThis.fetch.mockClear();
    setPredictionStorePayload({ generatedAt: 0 });
    await flushPromises(2);
    expect(globalThis.fetch).toHaveBeenCalledTimes(0);

    vi.setSystemTime(new Date(base + 2 * HOUR));
    globalThis.fetch.mockImplementation(url => {
      const urlString = String(url);
      if (urlString.includes('windpower.json')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(windData) });
      }
      if (urlString.includes('prices.csv')) {
        return Promise.resolve({ ok: true, text: () => Promise.resolve(csv) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve(npfData) });
    });

    const nextToken = base + 2 * HOUR + 1;
    setPredictionStorePayload({ generatedAt: nextToken });
    await flushPromises(8);
    expect(globalThis.fetch.mock.calls.length).toBeGreaterThanOrEqual(3);

    globalThis.fetch.mockClear();
    setPredictionStorePayload({ generatedAt: nextToken });
    await flushPromises(2);
    expect(globalThis.fetch).toHaveBeenCalledTimes(0);

    vi.useRealTimers();
  });
});
