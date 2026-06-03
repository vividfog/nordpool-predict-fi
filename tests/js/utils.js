import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { vi } from 'vitest';

const loadedScripts = new Set();
const baseDependencies = [
  'deploy/js/fetch-utils.js',
  'deploy/js/chart-formatters.js',
  'deploy/js/prediction-store.js'
];

export function loadScript(relativePath, options = {}) {
  if (!baseDependencies.includes(relativePath)) {
    for (const dependency of baseDependencies) {
      if (!loadedScripts.has(dependency)) {
        loadScript(dependency);
      }
    }
  }

  if (baseDependencies.includes(relativePath) && loadedScripts.has(relativePath)) {
    return;
  }

  const code = readFileSync(resolve(process.cwd(), relativePath), 'utf-8');
  window.eval(code);
  if (baseDependencies.includes(relativePath)) {
    loadedScripts.add(relativePath);
  }
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
  const handlers = new Map();
  const resize = vi.fn();
  const setOption = vi.fn();
  const clear = vi.fn();
  const getOption = vi.fn(() => ({ series: [] }));
  const on = vi.fn((eventName, handler) => {
    handlers.set(eventName, handler);
  });
  const off = vi.fn((eventName) => {
    handlers.delete(eventName);
  });
  const trigger = (eventName, payload) => {
    const handler = handlers.get(eventName);
    if (handler) {
      handler(payload);
    }
  };
  return {
    resize,
    setOption,
    clear,
    getOption,
    on,
    off,
    trigger
  };
}

export function setPathname(pathname) {
  window.history.replaceState({}, '', pathname);
}

export function stubHelsinkiMidnights(baseTimestamp) {
  const HOUR = 60 * 60 * 1000;
  const base = Number.isFinite(baseTimestamp) ? baseTimestamp : Date.UTC(2025, 0, 1);
  const resolveBase = referenceDate => {
    if (referenceDate instanceof Date && Number.isFinite(referenceDate.getTime())) {
      return Date.UTC(
        referenceDate.getUTCFullYear(),
        referenceDate.getUTCMonth(),
        referenceDate.getUTCDate()
      );
    }
    return base;
  };
  const isoBuilder = vi.fn((offset, referenceDate) => {
    const resolvedBase = resolveBase(referenceDate);
    const hours = Number.isFinite(offset) ? offset * 24 : 0;
    return new Date(resolvedBase + hours * HOUR).toISOString();
  });
  const tsBuilder = vi.fn((offset, referenceDate) => {
    const resolvedBase = resolveBase(referenceDate);
    const hours = Number.isFinite(offset) ? offset * 24 : 0;
    return resolvedBase + hours * HOUR;
  });
  window.getHelsinkiMidnightISOString = isoBuilder;
  window.getHelsinkiMidnightTimestamp = tsBuilder;
  return { isoBuilder, tsBuilder };
}

/**
 * Build a simple Sähkötin-style CSV string from timestamp/value pairs.
 */
export function buildPriceCsv(rows) {
  const header = ['timestamp,price'];
  const body = (rows || []).map(([timestamp, value]) => {
    return `${new Date(timestamp).toISOString()},${value}`;
  });
  return header.concat(body).join('\n');
}

export function setPredictionStorePayload(payload, options = {}) {
  const store = window.predictionStore;
  if (!store || typeof store.setLatest !== 'function') {
    throw new Error('predictionStore is not available in the test environment');
  }
  store.setLatest(payload, options);
}
