import { describe, expect, it, vi } from 'vitest';
import { flushPromises, loadScript } from './utils';

describe('deploy/js/cheapest.js', () => {
  const buildPayload = vi.fn();

  function defaultPayload() {
    return {
      windows: [
        {
          duration: 3,
          average: 8.5,
          start: Date.UTC(2025, 0, 1, 8),
          end: Date.UTC(2025, 0, 1, 11)
        }
      ],
      meta: {
        lookaheadDays: 2,
        startHour: 7,
        endHour: 22
      }
    };
  }

  async function mountCheapest(options = {}) {
    loadScript('deploy/js/config.js');
    if (!options.skipClearStorage) {
      window.appStorage?.remove?.('np_cheapest_preferences');
    }

    if (options.seedPreferences) {
      window.appStorage?.set?.('np_cheapest_preferences', options.seedPreferences);
    }

    window.CHEAPEST_WINDOW_DEFAULTS = {
      lookaheadDays: 2,
      minLookaheadDays: 1,
      maxLookaheadDays: 7,
      startHour: 0,
      endHour: 23,
      minHour: 0,
      maxHour: 23
    };

    buildPayload.mockReset();
    buildPayload.mockImplementation(() => options.windowPayload ?? defaultPayload());
    window.buildCheapestWindowPayload = buildPayload;

    document.body.innerHTML = `
      <div id="cheapestWindows">
        <table>
          <tbody></tbody>
        </table>
      </div>
      <form id="cheapestControls"></form>
      <input id="cheapestDaysInput" />
      <input id="cheapestStartHourInput" />
      <input id="cheapestEndHourInput" />
    `;

    window.latestPredictionData = options.predictionPayload ?? {
      mergedSeries: [
        [Date.UTC(2025, 0, 1, 8), 7],
        [Date.UTC(2025, 0, 1, 9), 6]
      ],
      meta: {}
    };

    vi.useFakeTimers();
    loadScript('deploy/js/cheapest.js', { triggerDOMContentLoaded: true });
    await flushPromises();
  }

  it('renders cheapest windows table rows', async () => {
    await mountCheapest();
    const rows = document.querySelectorAll('#cheapestWindows tbody tr');
    expect(rows.length).toBe(1);
    expect(rows[0].textContent).toContain('3 h');
    expect(buildPayload).toHaveBeenCalled();
    vi.useRealTimers();
  });

  it('preserves stored preferences when prediction meta updates arrive', async () => {
    await mountCheapest({
      seedPreferences: {
        lookaheadDays: 5,
        startHour: 7,
        endHour: 19
      }
    });
    buildPayload.mockClear();
    window.dispatchEvent(new CustomEvent('prediction-data-ready', {
      detail: {
        mergedSeries: [[Date.UTC(2025, 0, 2, 10), 4]],
        meta: {
          lookaheadDays: 3,
          startHour: 6,
          endHour: 20
        }
      }
    }));
    expect(buildPayload).toHaveBeenCalled();
    const lastCall = buildPayload.mock.calls.at(-1);
    expect(lastCall[2]).toMatchObject({
      lookaheadDays: 5,
      startHour: 7,
      endHour: 19
    });
    vi.useRealTimers();
  });

  it('normalizes control inputs on change', async () => {
    await mountCheapest();
    const lookaheadInput = document.getElementById('cheapestDaysInput');
    lookaheadInput.value = '9';
    lookaheadInput.dispatchEvent(new Event('change'));
    expect(lookaheadInput.value).toBe('7');
    vi.useRealTimers();
  });

  it('falls back gracefully when appStorage is disabled', async () => {
    await mountCheapest();

    const originalEnabled = window.appStorage.enabled;
    window.appStorage.enabled = false;
    window.appStorage.remove('np_cheapest_preferences');

    buildPayload.mockClear();
    window.dispatchEvent(new CustomEvent('prediction-data-ready', {
        detail: {
            mergedSeries: [[Date.UTC(2025, 0, 2, 12), 5]],
            meta: {}
        }
    }));

    expect(buildPayload).toHaveBeenCalled();
    const lastCall = buildPayload.mock.calls.at(-1);
    expect(lastCall[2]).toMatchObject({
      lookaheadDays: 2,
      startHour: 0,
      endHour: 23
    });

    window.appStorage.enabled = originalEnabled;
    vi.useRealTimers();
  });
});
