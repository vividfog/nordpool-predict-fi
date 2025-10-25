import { describe, expect, it, vi } from 'vitest';
import { loadScript } from './utils';

describe('deploy/js/layout.js', () => {
  it('resizes charts on window resize', () => {
    globalThis.nfpChart = { resize: vi.fn() };
    globalThis.historyChart = { resize: vi.fn() };
    globalThis.windPowerChart = { resize: vi.fn() };

    loadScript('deploy/js/layout.js');
    expect(typeof window.onresize).toBe('function');

    window.onresize();
    expect(nfpChart.resize).toHaveBeenCalled();
    expect(historyChart.resize).toHaveBeenCalled();
    expect(windPowerChart.resize).toHaveBeenCalled();
  });
});
