import { beforeAll, describe, expect, it, vi } from 'vitest';
import { createEchartsMock, loadScript, flushPromises, buildPriceCsv, stubHelsinkiMidnights } from './utils';

const HOUR = 60 * 60 * 1000;

describe('deploy/js/prediction.js', () => {
  let chartMock;

  beforeAll(async () => {
    document.body.innerHTML = '<div id="predictionChart"></div>';
    chartMock = createEchartsMock();
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

  it('uses the responsive grid offset from the chart shell', () => {
    const shell = document.createElement('div');
    shell.id = 'predictionChartShell';
    shell.style.setProperty('--np-prediction-grid-top', '72px');
    shell.style.setProperty('--np-prediction-grid-bottom', '64px');
    document.body.append(shell);
    expect(getPredictionGridTop()).toBe(72);
    expect(getPredictionGridBottom()).toBe(64);
    shell.remove();
  });

  it('builds daily averages by Helsinki 01:00 publishing day', () => {
    const originalMidnightBuilder = window.getHelsinkiMidnightTimestamp;
    window.getHelsinkiMidnightTimestamp = vi.fn((offset, referenceDate) => {
      const reference = new Date(referenceDate);
      return Date.UTC(
        reference.getUTCFullYear(),
        reference.getUTCMonth(),
        reference.getUTCDate() + offset,
        -2
      );
    });
    try {
      const jan2MidnightLocal = Date.UTC(2025, 0, 1, 22);
      const series = [
        [jan2MidnightLocal, 10],
        [jan2MidnightLocal + HOUR, 14],
        [jan2MidnightLocal + 2 * HOUR, 30],
        ['bad', 99]
      ];
      const daily = buildDailyAverageSeries(series);
      expect(daily).toEqual([
        [jan2MidnightLocal, 10],
        [jan2MidnightLocal + HOUR, 22],
        [jan2MidnightLocal + 2 * HOUR, 22]
      ]);
    } finally {
      window.getHelsinkiMidnightTimestamp = originalMidnightBuilder;
    }
  });

  it('clips daily average segments to the hourly chart range', () => {
    const originalMidnightBuilder = window.getHelsinkiMidnightTimestamp;
    window.getHelsinkiMidnightTimestamp = vi.fn((offset, referenceDate) => {
      const reference = new Date(referenceDate);
      return Date.UTC(
        reference.getUTCFullYear(),
        reference.getUTCMonth(),
        reference.getUTCDate() + offset,
        -2
      );
    });
    try {
      const firstHour = Date.UTC(2025, 0, 2, 8);
      const series = [
        [firstHour, 10],
        [firstHour + HOUR, 12],
        [firstHour + 2 * HOUR, 14],
        [firstHour + 3 * HOUR, 16]
      ];
      const daily = buildDailyAverageSeries(series);
      expect(daily[0][0]).toBe(firstHour);
      expect(daily[daily.length - 1][0]).toBe(firstHour + 3 * HOUR);
      expect(daily).toHaveLength(4);
    } finally {
      window.getHelsinkiMidnightTimestamp = originalMidnightBuilder;
    }
  });

  it('does not duplicate daily average tooltip points at day boundaries', () => {
    const originalMidnightBuilder = window.getHelsinkiMidnightTimestamp;
    window.getHelsinkiMidnightTimestamp = vi.fn((offset, referenceDate) => {
      const reference = new Date(referenceDate);
      return Date.UTC(
        reference.getUTCFullYear(),
        reference.getUTCMonth(),
        reference.getUTCDate() + offset,
        -2
      );
    });
    try {
      const jan2MidnightLocal = Date.UTC(2025, 0, 1, 22);
      const series = [
        [jan2MidnightLocal, 10],
        [jan2MidnightLocal + HOUR, 20],
        [jan2MidnightLocal + 2 * HOUR, 22],
        [jan2MidnightLocal + 24 * HOUR, 30],
        [jan2MidnightLocal + 25 * HOUR, 40]
      ];
      const daily = buildDailyAverageSeries(series);
      const countsByTimestamp = daily.reduce((counts, [timestamp]) => {
        counts.set(timestamp, (counts.get(timestamp) || 0) + 1);
        return counts;
      }, new Map());
      expect([...countsByTimestamp.values()].every(count => count === 1)).toBe(true);
      expect(daily.find(item => item[0] === jan2MidnightLocal)[1]).toBe(10);
      expect(daily.find(item => item[0] === jan2MidnightLocal + HOUR)[1]).toBe(24);
      expect(daily.find(item => item[0] === jan2MidnightLocal + 24 * HOUR)[1]).toBe(24);
      expect(daily.find(item => item[0] === jan2MidnightLocal + 25 * HOUR)[1]).toBe(40);
    } finally {
      window.getHelsinkiMidnightTimestamp = originalMidnightBuilder;
    }
  });

  it('defaults the prediction chart to hourly mode', () => {
    const base = Date.UTC(2025, 0, 6, 8);
    processPredictionPayload(
      [
        [base, 10],
        [base + HOUR, 11],
        [base + 2 * HOUR, 12]
      ],
      [],
      buildPriceCsv([[base, 8]])
    );
    const fullOptionCall = [...chartMock.setOption.mock.calls]
      .reverse()
      .find(call => call[0]?.legend && Array.isArray(call[0]?.series) && call[0].series.some(series => series.id === 'daily-average-line'));
    expect(fullOptionCall).toBeTruthy();
    const option = fullOptionCall[0];
    const forecast = option.series.find(series => series.id === 'forecast-line');
    const daily = option.series.find(series => series.id === 'daily-average-line');
    expect(forecast.data.length).toBeGreaterThan(0);
    expect(daily.data.length).toBeGreaterThan(0);
    expect(option.grid.top).toBe(56);
    expect(option.grid.bottom).toBe(96);
    expect(option.legend.top).toBe(8);
    expect(option.legend.selected[getLocalizedText('daily_avg')]).toBe(false);
  });

  it('adds daily average as a normal optional legend series', () => {
    const base = Date.UTC(2025, 0, 7, 8);
    processPredictionPayload(
      [
        [base, 10],
        [base + HOUR, 11],
        [base + 2 * HOUR, 12]
      ],
      [[base + 2 * HOUR, 1]],
      buildPriceCsv([[base, 8]])
    );
    const dailyName = getLocalizedText('daily_avg');
    const forecastName = getLocalizedText('forecast');

    const chartCall = [...chartMock.setOption.mock.calls]
      .reverse()
      .find(call => Array.isArray(call[0]?.series) && call[0].legend?.selected?.[dailyName] === false);
    const chartOption = chartCall[0];
    expect(chartOption.legend.selected[forecastName]).toBe(true);
    expect(chartOption.legend.selected[dailyName]).toBe(false);
    expect(chartOption.series.find(series => series.id === 'forecast-line').data.length).toBeGreaterThan(0);
    expect(chartOption.series.find(series => series.id === 'sahkotin-line').data.length).toBeGreaterThan(0);
    expect(chartOption.series.find(series => series.id === 'scaled-price-markers').markPoint.data.length).toBeGreaterThanOrEqual(0);
    const dailySeries = chartOption.series.find(series => series.id === 'daily-average-line');
    expect(dailySeries.data.length).toBeGreaterThan(0);
    expect(dailySeries.lineStyle.color).toBe('DeepPink');
    expect(dailySeries.lineStyle.type).toBe('dotted');
    expect(dailySeries.itemStyle.color).toBe('DeepPink');
    expect(dailySeries.tooltip.show).toBe(true);
  });

  it('restores and persists prediction legend selections', () => {
    const storageKey = 'np_prediction_legend_selection';
    const base = Date.UTC(2025, 0, 9, 8);
    const dailyName = getLocalizedText('daily_avg');
    const forecastName = getLocalizedText('forecast');
    const scaledName = getLocalizedText('scaled_price');

    window.appStorage.set(storageKey, {
      Nordpool: false,
      [forecastName]: true,
      [scaledName]: false,
      [dailyName]: true,
      stale: true
    });

    try {
      processPredictionPayload(
        [
          [base, 10],
          [base + HOUR, 11],
          [base + 2 * HOUR, 12]
        ],
        [[base + 2 * HOUR, 1]],
        buildPriceCsv([[base, 8]])
      );

      const chartCall = [...chartMock.setOption.mock.calls]
        .reverse()
        .find(call => Array.isArray(call[0]?.series) && call[0].legend?.selected?.[dailyName] === true);
      expect(chartCall[0].legend.selected).toMatchObject({
        Nordpool: false,
        [forecastName]: true,
        [scaledName]: false,
        [dailyName]: true
      });
      expect(chartCall[0].legend.selected.stale).toBeUndefined();

      chartMock.trigger('legendselectchanged', {
        selected: {
          Nordpool: true,
          [forecastName]: false,
          [scaledName]: true,
          [dailyName]: false,
          stale: true
        }
      });
      expect(window.appStorage.get(storageKey)).toEqual({
        Nordpool: true,
        [forecastName]: false,
        [scaledName]: true,
        [dailyName]: false
      });
    } finally {
      window.appStorage.remove(storageKey);
    }
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

  it('renders forecast-only chart data when Sähkötin fetch fails', async () => {
    vi.useFakeTimers();
    const base = Date.UTC(2025, 0, 8, 9);
    vi.setSystemTime(base);
    const predictionSeries = [
      [base, 9],
      [base + HOUR, 10],
      [base + 2 * HOUR, 11]
    ];
    const scaledSeries = predictionSeries.map(([ts]) => [ts, null]);

    try {
      globalThis.fetch.mockImplementation(url => {
        if (String(url).includes('prediction.json')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(predictionSeries)
          });
        }
        if (String(url).includes('prediction_scaled')) {
          return Promise.resolve({
            ok: true,
            text: () => Promise.resolve(JSON.stringify(scaledSeries))
          });
        }
        if (String(url).includes('sahkotin')) {
          return Promise.reject(new Error('sahkotin unavailable'));
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([])
        });
      });

      await fetchPredictionData({ force: true });
      await flushPromises(2);

      const payload = window.predictionStore.getLatest();
      expect(payload.sahkotinSeries).toEqual([]);
      expect(payload.forecastSeries[0][0]).toBe(base + HOUR);
      expect(payload.mergedSeries.length).toBeGreaterThan(0);
    } finally {
      vi.useRealTimers();
    }
  });
});
