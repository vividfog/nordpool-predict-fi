import { afterEach, beforeEach, vi } from 'vitest';

const defaultUrl = new URL(window.location.href);

const defaultFetchMock = () => {
  throw new Error('fetch not mocked for this test');
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  vi.clearAllTimers();

  document.body.innerHTML = '';
  window.history.replaceState({}, '', defaultUrl.href);

  if (!('fetch' in globalThis)) {
    throw new Error('Global fetch is required for these tests.');
  }

  if (!vi.isMockFunction(globalThis.fetch)) {
    globalThis.fetch = vi.fn(defaultFetchMock);
  } else {
    globalThis.fetch.mockReset();
    globalThis.fetch.mockImplementation(defaultFetchMock);
  }
});

afterEach(() => {
  document.body.innerHTML = '';
});
