import { beforeAll, describe, expect, it, vi } from 'vitest';
import { createEchartsMock, loadScript, flushPromises, buildPriceCsv, stubHelsinkiMidnights } from './utils';

const HOUR = 60 * 60 * 1000;

describe('deploy/js/prediction.js', () => {
  beforeAll(async () => {
    document.body.innerHTML = '<div id="predictionChart"></div>';
    const chartMock = createEchartsMock();
    globalThis.echarts = {
      init: () => chartMock
    };

    const now = Date.UTC(2025, 0, 1, 8);
    vi.useFakeTimers();
    vi.setSystemTime(now);

    const predictionSeries = Array.from({ length: 6 }, (_, idx) => [now + idx * HOUR, 10 + idx]);
    const scaledSeries = predictionSeries.map(([ts], idx) => [ts, idx % 2 === 0 ? 1 : null]);
    const csvLines = buildPriceCsv(predictionSeries.map(([ts, value]) => [ts, value - 2]));

    vi.spyOn(globalThis, 'fetch').mockImplementation(url => {
      if (String(url).includes('prediction_scaled')) {
        return Promise.resolve({
          ok: true,
          text: () => Promise.resolve(JSON.stringify(scaledSeries))
        });
      }
      if (String(url).includes('prediction.json')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(predictionSeries)
        });
      }
      if (String(url).includes('sahkotin')) {
        return Promise.resolve({
          ok: true,
          text: () => Promise.resolve(csvLines)
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([])
      });
    });

    loadScript('deploy/js/config.js');
    stubHelsinkiMidnights(now);
    loadScript('deploy/js/prediction.js');

    await flushPromises(4);

    vi.useRealTimers();
  });

  it('merges price series preferring latest values', () => {
    const base = Date.UTC(2025, 0, 1);
    const actual = [
      [base, 10],
      [base + HOUR, 11]
    ];
    const forecast = [
      [base - HOUR, 9],
      [base, 12]
    ];
    const merged = mergePriceSeries(actual, forecast);
    expect(merged).toEqual([
      [base - HOUR, 9],
      [base, 10],
      [base + HOUR, 11]
    ]);
  });

  it('clamps lookahead days within configured window', () => {
    expect(clampLookaheadDays(NaN)).toBe(4);
    expect(clampLookaheadDays(0)).toBe(1);
    expect(clampLookaheadDays(9)).toBe(7);
  });

  it('computes lookahead hours respecting Helsinki hour rollovers', () => {
    const now = Date.UTC(2025, 2, 29, 21); // DST weekend
    const hours = computeLookaheadHours(now, 4);
    expect(hours).toBeGreaterThan(0);
    expect(hours).toBeLessThanOrEqual(168);
  });

  it('builds start-hour masks inclusively across midnight', () => {
    expect(buildStartHourMask(0, 23)).toBeNull();
    const mask = buildStartHourMask(22, 2);
    expect(mask).not.toBeNull();
    expect(mask.has(22)).toBe(true);
    expect(mask.has(0)).toBe(true);
    expect(mask.has(3)).toBe(false);
  });

  it('detects hourly sequences with tolerance', () => {
    const seq = [
      [0, 1],
      [HOUR + 200, 2]
    ];
    expect(isHourlySequence(seq)).toBe(true);
    const broken = [
      [0, 1],
      [HOUR * 2, 2]
    ];
    expect(isHourlySequence(broken)).toBe(false);
  });

  it('finds cheapest windows under constraints', () => {
    const base = Date.UTC(2025, 0, 1);
    const series = Array.from({ length: 8 }, (_, idx) => [base + idx * HOUR, idx + 1]);
    const window = computeCheapestWindow(series, 3, {
      nowMs: base + 2 * HOUR,
      lookaheadLimit: base + 8 * HOUR,
      mask: buildStartHourMask(0, 23)
    });
    expect(window.start).toBe(base);
    const constrained = findCheapestWindow(series, 2, {
      earliestStart: base + 3 * HOUR,
      minEnd: base + 5 * HOUR,
      mask: null
    });
    expect(constrained.start).toBe(base + 3 * HOUR);
  });

  it('formats window payloads', () => {
    expect(formatWindowPayload(3, null)).toEqual({
      duration: 3,
      average: null,
      start: null,
      end: null
    });
  });

  it('computes Helsinki hour from UTC timestamp', () => {
    const timestamp = Date.UTC(2025, 9, 26, 21); // Oct 26 00:00 local next day
    const hour = getHelsinkiHour(timestamp);
    expect(hour).toBeTypeOf('number');
    expect(hour).toBeGreaterThanOrEqual(0);
    expect(hour).toBeLessThan(24);
  });

  it('builds cheapest window payload with defaults', () => {
    const base = Date.UTC(2025, 0, 1);
    const series = Array.from({ length: 12 }, (_, idx) => [base + idx * HOUR, idx + 5]);
    const payload = buildCheapestWindowPayload(series, base + HOUR);
    expect(payload.meta.lookaheadDays).toBe(4);
    expect(payload.windows).toHaveLength(3);
    expect(window.buildCheapestWindowPayload).toBeTypeOf('function');
  });

  it('filters forecasts to start right after realized Sähkötin hours', () => {
    vi.useFakeTimers();
    const base = Date.UTC(2025, 0, 2, 6);
    vi.setSystemTime(base);
    const predictionSeries = [
      [base, 10],
      [base + HOUR, 11],
      [base + 2 * HOUR, 12]
    ];
    const scaledSeries = predictionSeries.map(([ts]) => [ts, 1]);
    const sahkotinCsv = buildPriceCsv([
      [base, 5],
      [base + HOUR, 6]
    ]);
    const payloads = [];
    const unsubscribe = window.predictionStore.subscribe(payload => payloads.push(payload));
    try {
      processPredictionPayload(predictionSeries, scaledSeries, sahkotinCsv);
      const payload = payloads[payloads.length - 1];
      expect(payload.sahkotinSeries[payload.sahkotinSeries.length - 1][0]).toBe(base + HOUR);
      expect(payload.forecastSeries[0][0]).toBe(base + 2 * HOUR);
      expect(payload.scaledPriceSeries[0][0]).toBe(base + 2 * HOUR);
      const mergedTimestamps = payload.mergedSeries.map(item => item[0]);
      expect(mergedTimestamps).toEqual([base, base + HOUR, base + 2 * HOUR]);
    } finally {
      unsubscribe();
      vi.useRealTimers();
    }
  });

  it('falls back to current time when Sähkötin data is empty', () => {
    vi.useFakeTimers();
    const base = Date.UTC(2025, 0, 5, 9);
    vi.setSystemTime(base);
    const predictions = [
      [base, 9],
      [base + HOUR, 10]
    ];
    const scaled = predictions.map(([ts]) => [ts, null]);
    const payloads = [];
    const unsubscribe = window.predictionStore.subscribe(payload => payloads.push(payload));
    try {
      processPredictionPayload(predictions, scaled, 'hour,price\n');
      const payload = payloads[payloads.length - 1];
      expect(payload.sahkotinSeries.length).toBe(0);
      expect(payload.forecastSeries[0][0]).toBe(base + HOUR);
      expect(payload.mergedSeries[0][0]).toBe(base + HOUR);
    } finally {
      unsubscribe();
      vi.useRealTimers();
    }
  });
});
