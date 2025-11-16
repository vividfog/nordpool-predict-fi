import { describe, expect, it, vi } from 'vitest';
import { flushPromises, loadScript, setPredictionStorePayload } from './utils';

describe('deploy/js/narration.js', () => {
  it('renders narration markdown', async () => {
    document.body.innerHTML = '<div id="narration"></div>';
    globalThis.marked = { parse: vi.fn(() => '<p>ok</p>') };

    globalThis.fetch.mockResolvedValue({
      ok: true,
      text: () => Promise.resolve('# Title')
    });

    loadScript('deploy/js/config.js');
    loadScript('deploy/js/narration.js');
    await flushPromises(6);

    expect(marked.parse).toHaveBeenCalledWith('# Title');
    expect(document.getElementById('narration').innerHTML).toBe('<p>ok</p>');
  });

  it('logs when fetch fails', async () => {
    document.body.innerHTML = '<div id="narration"></div>';
    globalThis.marked = { parse: vi.fn() };
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    globalThis.fetch.mockResolvedValue({
      ok: false,
      text: () => Promise.resolve('')
    });

    loadScript('deploy/js/config.js');
    loadScript('deploy/js/narration.js');
    await flushPromises(6);

    expect(errorSpy).toHaveBeenCalled();
  });

  it('skips redundant reloads unless token increases', async () => {
    vi.useFakeTimers();
    const now = Date.UTC(2025, 0, 1, 12);
    vi.setSystemTime(new Date(now));

    document.body.innerHTML = '<div id="narration"></div>';
    globalThis.marked = { parse: vi.fn(() => '<p>render</p>') };
    globalThis.fetch.mockImplementation(() => Promise.resolve({
      ok: true,
      text: () => Promise.resolve('# Body')
    }));

    loadScript('deploy/js/config.js');
    loadScript('deploy/js/narration.js');
    await flushPromises(6);
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);

    globalThis.fetch.mockClear();
    setPredictionStorePayload({ generatedAt: now });
    await flushPromises(2);
    expect(globalThis.fetch).toHaveBeenCalledTimes(0);

    setPredictionStorePayload({ generatedAt: now + 1 });
    await flushPromises(6);
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);

    vi.useRealTimers();
  });
});
