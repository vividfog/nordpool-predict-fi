import { describe, expect, it, vi } from 'vitest';
import { createEchartsMock, flushPromises, loadScript, setPathname } from './utils';

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
    const sahkotinCsv = [
      'timestamp,price',
      `${new Date(base).toISOString()},6`,
      `${new Date(base + HOUR).toISOString()},7`
    ].join('\n');
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

    expect(chart.setOption).toHaveBeenCalledTimes(1);
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
});
