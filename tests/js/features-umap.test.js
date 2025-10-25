import { describe, expect, it, vi } from 'vitest';
import { flushPromises, loadScript } from './utils';

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
});
