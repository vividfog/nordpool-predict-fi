import { describe, expect, it, vi } from 'vitest';
import { createEchartsMock, loadScript, setPathname, setPredictionStorePayload } from './utils';

const HOUR = 60 * 60 * 1000;

function setupCalendar(payload) {
  loadScript('deploy/js/config.js');
  const chart = createEchartsMock();
  chart.getOption = vi.fn(() => ({ series: [] }));
  globalThis.echarts = {
    init: () => chart
  };

  document.body.innerHTML = `
    <div id="priceCalendar"></div>
    <div id="priceCalendarStatus"></div>
    <div id="priceCalendarLegend"></div>
  `;

  setPredictionStorePayload(null, { silent: true });
  setPredictionStorePayload(payload, { silent: true });
  loadScript('deploy/js/calendar.js', { triggerDOMContentLoaded: true });

  return chart;
}

describe('deploy/js/calendar.js', () => {
  it('renders calendar data when payload is available', () => {
    setPathname('/index.html');
    vi.useFakeTimers();
    const anchor = Date.UTC(2025, 2, 28, 21);
    vi.setSystemTime(anchor);
    const base = Date.UTC(2025, 2, 28, 22); // ensure DST weekend coverage
    const payload = {
      mergedSeries: [
        [base, 10],
        [base + HOUR, 12],
        [base + 2 * HOUR, 8]
      ],
      sahkotinSeries: [],
      forecastSeries: []
    };
    const chart = setupCalendar(payload);

    expect(chart.setOption).toHaveBeenCalledTimes(1);
    const option = chart.setOption.mock.calls[0][0];
    expect(option.series[0].data.some(cell => Number.isFinite(cell[2]))).toBe(true);

    const status = document.getElementById('priceCalendarStatus');
    expect(status.style.display).toBe('none');
    const legend = document.getElementById('priceCalendarLegend');
    expect(legend.children.length).toBeGreaterThan(0);
    vi.useRealTimers();
  });

  it('clears chart when payload lacks usable data', () => {
    setPathname('/index.html');
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2025-03-28T21:00:00Z'));
    const chart = setupCalendar({
      mergedSeries: [[Date.now(), NaN]]
    });
    expect(chart.clear).toHaveBeenCalled();
    const status = document.getElementById('priceCalendarStatus');
    expect(status.textContent).toContain('Odottaa');
    vi.useRealTimers();
  });
});
