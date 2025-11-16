import { describe, expect, it, beforeAll, beforeEach, vi } from 'vitest';
import { loadScript, setPathname } from './utils';

describe('deploy/js/config.js', () => {
  function localMidnightTimestamp(year, month, day) {
    const utc = Date.UTC(year, month, day, 0, 0, 0);
    const offsetMinutes = new Date(utc).getTimezoneOffset();
    return utc + offsetMinutes * 60 * 1000;
  }

  beforeAll(() => {
    const palette = {
      page: { light: { vars: {} }, dark: { vars: {} } },
      prediction: {
        light: {
          axis: '#666666',
          grid: 'silver',
          tooltipBg: '#ffffff',
          tooltipText: '#333333',
          tooltipBorder: '#cccccc',
          legendText: '#222222',
          markLineLabel: 'black',
          markLineLine: 'black',
          chartBackground: 'transparent',
          sahkotinBar: 'lime',
          sahkotinBarOpacity: 0.1,
          sahkotinLine: 'lime',
          spikeMarker: 'crimson',
          outOfRange: '#999999'
        }
      },
      history: {
        light: {
          axis: '#666666',
          grid: 'silver',
          tooltipBg: '#ffffff',
          tooltipText: '#333333',
          tooltipBorder: '#cccccc',
          legendText: '#222222',
          markLineLabel: 'black',
          markLineLine: 'black',
          zoomBackground: '#f0f2f5',
          zoomBorder: '#dddddd'
        }
      },
      windpower: {
        light: {
          axis: '#666666',
          grid: 'silver',
          tooltipBg: '#ffffff',
          tooltipText: '#333333',
          tooltipBorder: '#cccccc',
          legendText: '#222222',
          markLineLabel: 'black',
          markLineLine: 'black',
          barColor: '#cccccc',
          areaFill: '#dddddd',
          outOfRange: '#999999'
        }
      },
      calendar: {
        light: {
          axis: '#333333',
          fallback: '#222222',
          border: '#ffffff',
          emphasis: 'dodgerblue'
        }
      },
      cheapest: {
        light: {
          dots: {
            3: '#111111',
            6: '#222222',
            12: '#333333'
          }
        }
      },
      featuresUmap: {
        light: {
          background: '#ffffff',
          scenePlane: '#eeeeee',
          legendText: '#111111',
          hoverBg: '#ffffff',
          hoverText: '#000000'
        }
      }
    };
    const subscribers = new Set();
    globalThis.__NP_THEME_NOTIFY__ = payload => {
      subscribers.forEach(fn => fn(payload));
    };
    globalThis.__NP_THEME__ = {
      palettes: palette,
      getMode: () => 'light',
      getPalette: (scope) => palette[scope]?.light || null,
      setMode: vi.fn(),
      subscribe: (fn) => {
        subscribers.add(fn);
        fn({ mode: 'light', effectiveMode: 'light', palettes: palette });
        return () => subscribers.delete(fn);
      }
    };
    loadScript('deploy/js/config.js');
  });

  beforeEach(() => {
    setPathname('/index.html');
  });

  it('computes addDays with midnight alignment', () => {
    const base = new Date('2025-02-01T13:45:00Z');
    const added = addDays(base, 3);
    const expected = new Date(base);
    expected.setDate(expected.getDate() + 3);
    expected.setHours(0, 0, 0, 0);
    expect(added.getTime()).toBe(expected.getTime());
    expect(added.getHours()).toBe(0);
    expect(added.getMinutes()).toBe(0);
    expect(added.getSeconds()).toBe(0);
  });

  it('returns past date strings', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2025-03-18T09:00:00Z'));
    const dates = getPastDateStrings(3);
    expect(dates).toEqual(['2025-03-18', '2025-03-17', '2025-03-16']);
    vi.useRealTimers();
  });

  it('formats current time with localized prefix', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2025-01-05T10:07:00Z'));
    const label = formatCurrentTimeLabel();
    expect(label).toContain('5.1.');
    expect(label).toContain('klo');
    vi.useRealTimers();
  });

  it('calculates moving average and time bins', () => {
    const series = [
      [0, 1],
      [1, 2],
      [2, 3],
      [3, 4]
    ];
    const averaged = calculateMovingAverage(series, 2);
    expect(averaged.map(item => Number(item[1].toFixed(2)))).toEqual([1, 1.5, 2.5, 3.5]);

    const timestamps = [
      [Date.UTC(2025, 0, 1, 0), 10],
      [Date.UTC(2025, 0, 1, 1), 20],
      [Date.UTC(2025, 0, 1, 3), 30]
    ];
    const bins = calculateTimeBins(timestamps, 2);
    expect(bins).toHaveLength(2);
    expect(bins[0][1]).toBe(15);
  });

  it('provides localized text and prefix', () => {
    expect(getTimePrefix()).toBe('klo');
    expect(getLocalizedText('forecast')).toBe('Ennuste');
    setPathname('/index_en.html');
    expect(getTimePrefix()).toBe('at');
    expect(getLocalizedText('forecast')).toBe('Forecast');
  });

  it('maps price bands and colors', () => {
    expect(getSahkotinPriceColor(12)).toBe('gold');
    expect(getSahkotinPriceColor(50)).toBe('darkred');
    expect(getSahkotinPriceColor(null, '#111')).toBe('#111');
    const pieces = getSahkotinVisualMapPieces();
    expect(pieces[0]).toMatchObject({ lte: 5 });
    expect(pieces[pieces.length - 1]).toMatchObject({ gt: 30 });
  });

  it('applies translations to DOM elements', () => {
    document.body.innerHTML = `
      <select>
        <option data-i18n="forecast"></option>
      </select>
    `;
    applyTranslations();
    expect(document.querySelector('option').textContent).toBe('Ennuste');
  });

  it('creates grid split intervals', () => {
    const dayGrid = createTimeGrids();
    const weekGrid = createTimeGrids(true);
    const mondayMidnightLocal = localMidnightTimestamp(2025, 0, 6);
    const midday = mondayMidnightLocal + 12 * 60 * 60 * 1000;
    expect(dayGrid.xAxis.splitLine.interval(0, mondayMidnightLocal)).toBe(true);
    expect(dayGrid.xAxis.splitLine.interval(0, midday)).toBe(false);
    expect(weekGrid.xAxis.splitLine.interval(0, mondayMidnightLocal)).toBe(true);
  });

  it('formats tooltips and axis labels', () => {
    const formatter = createTooltipFormatter({ Nordpool: '¢/kWh' });
    const result = formatter([{
      axisValue: Date.UTC(2025, 0, 1, 12),
      seriesName: 'Nordpool',
      seriesType: 'line',
      value: [Date.UTC(2025, 0, 1, 12), 13.4],
      marker: '*'
    }]);
    expect(result).toContain('13.4 ¢/kWh');

    const axisFormatter = createXAxisFormatter(true);
    expect(axisFormatter(Date.UTC(2025, 0, 2))).toBe('2.1.');
  });

  it('builds base chart options and updates markers', () => {
    const options = createBaseChartOptions({
      legend: { show: true },
      series: [{ name: 'Test' }],
      isHistoryChart: true
    });
    expect(options.legend.show).toBe(true);
    expect(options.xAxis.splitLine.interval(0, Date.UTC(2025, 0, 6))).toBe(true);

    const chart = {
      getOption: vi.fn(() => ({
        series: [{ markLine: {} }]
      })),
      setOption: vi.fn()
    };
    updateMarkerPosition(chart);
    expect(chart.getOption).toHaveBeenCalled();
    expect(chart.setOption).toHaveBeenCalled();
  });

  it('persists appStorage data and falls back gracefully', () => {
    const key = `np-test-${Date.now()}`;
    expect(window.appStorage.enabled).toBe(true);

    window.appStorage.set(key, { value: 42 });
    expect(window.appStorage.get(key)).toEqual({ value: 42 });

    window.appStorage.remove(key);
    expect(window.appStorage.get(key)).toBeNull();
    expect(window.appStorage.get(key, 'fallback')).toBe('fallback');

    const previous = window.appStorage.enabled;
    window.appStorage.enabled = false;
    expect(window.appStorage.get(key, 'alt')).toBe('alt');
    window.appStorage.set(key, { shouldNotPersist: true });
    window.appStorage.enabled = previous;
  });

  it('provides palette helpers backed by the theme service', () => {
    const palette = window.resolveChartPalette('prediction');
    expect(palette).toBeDefined();
    expect(palette.axis).toBe('#666666');

    const handler = vi.fn();
    const unsubscribe = window.subscribeThemePalette('prediction', handler);
    expect(typeof unsubscribe).toBe('function');
    expect(handler).toHaveBeenCalledTimes(1);

    const payload = {
      mode: 'dark',
      effectiveMode: 'dark',
      palettes: globalThis.__NP_THEME__?.palettes
    };
    globalThis.__NP_THEME_NOTIFY__(payload);
    expect(handler).toHaveBeenCalledTimes(2);
    unsubscribe();
  });

  it('creates cache-busted URLs with tokens', () => {
    const base = 'https://example.com/data.json';
    expect(createCacheBustedUrl(base, 123)).toBe(`${base}?cb=123`);
    expect(createCacheBustedUrl(`${base}?foo=bar`, 456)).toBe(`${base}?foo=bar&cb=456`);
  });
});
