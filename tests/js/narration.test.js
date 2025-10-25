import { describe, expect, it, vi } from 'vitest';
import { flushPromises, loadScript } from './utils';

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
});
