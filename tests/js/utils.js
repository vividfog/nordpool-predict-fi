import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { vi } from 'vitest';

export function loadScript(relativePath, options = {}) {
  const code = readFileSync(resolve(process.cwd(), relativePath), 'utf-8');
  window.eval(code);
  if (options.triggerDOMContentLoaded) {
    document.dispatchEvent(new Event('DOMContentLoaded'));
  }
}

export async function flushPromises(times = 2) {
  for (let index = 0; index < times; index++) {
    await Promise.resolve();
  }
}

export function createEchartsMock() {
  const resize = vi.fn();
  const setOption = vi.fn();
  const clear = vi.fn();
  const getOption = vi.fn(() => ({ series: [] }));
  return {
    resize,
    setOption,
    clear,
    getOption
  };
}

export function setPathname(pathname) {
  window.history.replaceState({}, '', pathname);
}
