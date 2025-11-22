import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest';
import { loadScript, flushPromises, setPathname } from './utils';

const HOUR = 60 * 60 * 1000;

function bootstrapTheme() {
  const palette = {
    page: { light: { vars: {} }, dark: { vars: {} } },
    prediction: { light: { axis: '#666666', grid: 'silver', tooltipBg: '#ffffff', tooltipText: '#333333', tooltipBorder: '#cccccc', legendText: '#333333', sahkotinBar: 'lime', sahkotinBarOpacity: 0.2 } },
    cheapest: { light: { dots: { 3: '#222222', 6: '#333333', 12: '#444444' } } }
  };
  const subscribers = new Set();
  globalThis.__NP_THEME_NOTIFY__ = payload => {
    subscribers.forEach(fn => fn(payload));
  };
  globalThis.__NP_THEME__ = {
    palettes: palette,
    getMode: () => 'light',
    getPalette: scope => palette[scope]?.light || null,
    setMode: vi.fn(),
    subscribe: fn => {
      subscribers.add(fn);
      fn({ mode: 'light', effectiveMode: 'light', palettes: palette });
      return () => subscribers.delete(fn);
    }
  };
}

describe('deploy/js/cheapest.js integration', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setPathname('/index.html');
    bootstrapTheme();
    document.body.innerHTML = `
      <div id="cheapestWindows">
        <table>
          <tbody></tbody>
        </table>
      </div>
      <form id="cheapestControls"></form>
      <input id="cheapestDaysInput" value="4" />
      <input id="cheapestStartHourInput" value="0" />
      <input id="cheapestEndHourInput" value="23" />
    `;
    loadScript('deploy/js/config.js');
    globalThis.fetch.mockReset();
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.clearAllTimers();
    vi.useRealTimers();
  });

  it('renders rows when prediction data is available', async () => {
    const base = Date.UTC(2025, 0, 3, 6);
    const payload = {
      mergedSeries: [
        [base, 5],
        [base + HOUR, 4],
        [base + 2 * HOUR, 3]
      ],
      sahkotinSeries: [
        [base, 5]
      ],
      forecastSeries: [
        [base + HOUR, 4],
        [base + 2 * HOUR, 3]
      ],
      scaledPriceSeries: [],
      generatedAt: base,
      windows: [
        { duration: 3, average: 4, start: base, end: base + 3 * HOUR }
      ],
      meta: {}
    };
    window.predictionStore.setLatest(payload);

    loadScript('deploy/js/cheapest.js', { triggerDOMContentLoaded: true });
    await flushPromises(6);

    const rows = document.querySelectorAll('#cheapestWindows tbody tr');
    expect(rows.length).toBeGreaterThan(0);
    expect(rows[0].textContent.toLowerCase()).not.toContain('loading');
  });
});
