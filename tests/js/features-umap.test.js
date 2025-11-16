import { describe, expect, it, vi } from 'vitest';
import { flushPromises, loadScript, setPredictionStorePayload } from './utils';

describe('deploy/js/features-umap.js', () => {
  it('renders feature embedding when data is available', async () => {
    loadScript('deploy/js/config.js');
    document.body.innerHTML = '<div id="featureEmbeddingChart"></div>';

    const newPlot = vi.fn();
    globalThis.Plotly = { newPlot };

    const payload = {
      groups: {
        weather: { en: 'Weather', fi: 'Sää', color: '#123456' }
      },
      features: [
        {
          group: 'weather',
          label: 'Temp',
          corr_price: 0.4,
          latest: 5,
          mean: 3,
          std: 1,
          x: 1,
          y: 2,
          z: 3
        }
      ]
    };

    globalThis.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(payload)
    });

    loadScript('deploy/js/features-umap.js', { triggerDOMContentLoaded: true });
    await flushPromises(6);

    expect(newPlot).toHaveBeenCalledTimes(1);
    const traces = newPlot.mock.calls[0][1];
    expect(traces).toHaveLength(1);
    expect(traces[0].name).toBe('Sää');
  });

  it('shows error message when fetch fails', async () => {
    loadScript('deploy/js/config.js');
    document.body.innerHTML = '<div id="featureEmbeddingChart"></div>';
    globalThis.Plotly = { newPlot: vi.fn() };

    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    globalThis.fetch.mockRejectedValue(new Error('fail'));

    loadScript('deploy/js/features-umap.js', { triggerDOMContentLoaded: true });
    await flushPromises(6);

    expect(errorSpy).toHaveBeenCalled();
    const container = document.getElementById('featureEmbeddingChart');
    expect(container.textContent).toMatch(/Feature embedding|Piirteiden upotusta/);
  });

  it('suppresses duplicate fetches while pending and when token unchanged', async () => {
    loadScript('deploy/js/config.js');
    document.body.innerHTML = '<div id="featureEmbeddingChart"></div>';

    const payload = {
      groups: { g: { en: 'Group', fi: 'Ryhmä' } },
      features: [
        { group: 'g', label: 'Foo', corr_price: 0.2, latest: 1, mean: 1, std: 0.1, x: 0, y: 0, z: 0 }
      ]
    };

    let resolvePending;
    const firstPromise = new Promise(resolve => { resolvePending = resolve; });
    globalThis.fetch.mockImplementation(() => firstPromise);

    const newPlot = vi.fn();
    const react = vi.fn();
    globalThis.Plotly = { newPlot, react };

    vi.useFakeTimers();
    vi.setSystemTime(new Date('2025-01-01T00:00:00Z'));

    loadScript('deploy/js/features-umap.js', { triggerDOMContentLoaded: true });
    setPredictionStorePayload({ generatedAt: 0 });
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);

    resolvePending({
      ok: true,
      json: () => Promise.resolve(payload)
    });
    await flushPromises(8);
    expect(newPlot).toHaveBeenCalledTimes(1);

    globalThis.fetch.mockClear();
    globalThis.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(payload)
    });

    const nextToken = Date.now() + 1;
    setPredictionStorePayload({ generatedAt: nextToken });
    await flushPromises(8);
    expect(globalThis.fetch.mock.calls.length).toBeGreaterThan(0);
    expect(react).toHaveBeenCalledTimes(1);

    const callsBeforeRepeat = globalThis.fetch.mock.calls.length;
    setPredictionStorePayload({ generatedAt: nextToken });
    await flushPromises(4);
    expect(globalThis.fetch.mock.calls.length).toBe(callsBeforeRepeat);

    vi.useRealTimers();
  });
});
