import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, loadScript } from './utils';

describe('deploy/js/weather-icons.js', () => {
  let chart;
  let motionObserverCallback;
  let observedRail;
  let setIntervalSpy;

  beforeEach(async () => {
    document.body.innerHTML = '<div id="predictionWeather"></div>';
    chart = {
      convertToPixel: vi.fn((_finder, timestamp) => timestamp / 1000),
      getDom: () => ({ clientWidth: 500 }),
      on: vi.fn()
    };
    window.nfpChart = chart;
    window.DATA_ENDPOINTS = { weather: 'https://example.test/weather.json' };
    window.getHelsinkiMidnightTimestamp = vi.fn((_offset, referenceDate) => (
      referenceDate.getTime() + 60000
    ));
    window.getHelsinkiElectricityDayBoundary = vi.fn(() => ({
      key: 'test-day',
      start: 0,
      end: 24 * 60 * 60 * 1000
    }));
    const weatherData = [
      { timestamp: 100000, condition: 'clear-day', windLevel: 'calm' },
      { timestamp: 200000, condition: 'rain', windLevel: 'strong' }
    ];
    const fullData = [
      {
        timestamp: '2025-01-01T00:00:00Z',
        Price_cpkWh: 1234.5,
        PricePredict_cpkWh: 9999,
        WindPowerMW: 1000,
        t_1: 10,
        t_2: 12
      },
      {
        timestamp: '2025-01-01T01:00:00Z',
        Price_cpkWh: null,
        PricePredict_cpkWh: 1300,
        WindPowerMW: 1500,
        t_1: 13,
        t_2: 15
      }
    ];
    window.dataClient = {
      fetchJson: vi.fn(url => Promise.resolve(
        String(url).includes('prediction_full') ? fullData : weatherData
      ))
    };
    vi.stubGlobal('requestAnimationFrame', callback => {
      callback();
      return 1;
    });
    vi.stubGlobal('cancelAnimationFrame', vi.fn());
    setIntervalSpy = vi.spyOn(window, 'setInterval');
    window.IntersectionObserver = class {
      constructor(callback) {
        motionObserverCallback = callback;
      }

      observe(target) {
        observedRail = target;
      }

      disconnect() {}
    };

    loadScript('deploy/js/weather-icons.js');
    await flushPromises(4);
  });

  it('renders one accessible single-SVG pictogram per valid day', () => {
    const marks = document.querySelectorAll('.np-weather-mark');
    expect(marks).toHaveLength(2);
    expect(marks[0].querySelectorAll('svg')).toHaveLength(1);
    expect(marks[0].querySelectorAll('.np-weather-condition')).toHaveLength(1);
    expect(marks[0].querySelectorAll('.np-windsock')).toHaveLength(1);
    expect(marks[1].querySelectorAll('.np-windsock')).toHaveLength(1);
    expect(document.querySelectorAll('.np-windsock-fabric-scale')).toHaveLength(2);
    expect(document.querySelectorAll('.np-windsock-pole')).toHaveLength(2);
    expect([...document.querySelectorAll('.np-windsock-pole')]
      .every(pole => pole.parentElement.classList.contains('np-windsock'))).toBe(true);
    expect([...document.querySelectorAll('.np-windsock-pole')]
      .every(pole => !pole.getAttribute('d').includes('H'))).toBe(true);
    expect(document.querySelectorAll('.np-windsock-joint')).toHaveLength(0);
    expect(document.querySelectorAll('.np-weather-gust')).toHaveLength(0);
    expect(marks[0].hasAttribute('title')).toBe(false);
    expect(marks[0].tabIndex).toBe(0);
    expect(marks[0].getAttribute('aria-label')).toContain('erittäin vähän tuulivoimaa');
    expect(marks[1].dataset.wind).toBe('strong');
  });

  it('positions icons from the ECharts time-axis conversion', () => {
    const marks = document.querySelectorAll('.np-weather-mark');
    const separators = document.querySelectorAll('.np-weather-separator');
    expect(chart.convertToPixel).toHaveBeenCalledWith({ xAxisIndex: 0 }, 100000);
    expect(marks[0].style.left).toBe('100px');
    expect(marks[1].style.left).toBe('200px');
    expect(separators).toHaveLength(1);
    expect(chart.convertToPixel).toHaveBeenCalledWith({ xAxisIndex: 0 }, 160000);
    expect(separators[0].style.left).toBe('160px');
  });

  it('drops malformed records instead of rendering misleading icons', () => {
    window.weatherIcons.render([
      { timestamp: 300000, condition: 'not-weather', windLevel: 'strong' },
      { timestamp: 400000, condition: 'snow', windLevel: 'weak' }
    ]);
    const marks = document.querySelectorAll('.np-weather-mark');
    expect(marks).toHaveLength(1);
    expect(marks[0].getAttribute('aria-label')).toContain('lumisadetta');
  });

  it('enables CSS motion only while the icon rail is visible', () => {
    const rail = document.getElementById('predictionWeather');
    expect(observedRail).toBe(rail);
    expect(rail.classList.contains('np-icon-motion-active')).toBe(false);
    expect(setIntervalSpy).not.toHaveBeenCalled();

    motionObserverCallback([{
      target: rail,
      isIntersecting: true,
      intersectionRatio: 1
    }]);
    expect(rail.classList.contains('np-icon-motion-active')).toBe(true);

    motionObserverCallback([{
      target: rail,
      isIntersecting: false,
      intersectionRatio: 0
    }]);
    expect(rail.classList.contains('np-icon-motion-active')).toBe(false);
  });

  it('shows a localized accessible weather tooltip', () => {
    const mark = document.querySelector('.np-weather-mark');
    const tooltip = document.getElementById('npWeatherTooltip');
    mark.dispatchEvent(new MouseEvent('mouseenter'));

    expect(tooltip.classList.contains('is-visible')).toBe(true);
    expect(tooltip.textContent).toContain('Yleissääselkeää');
    expect(tooltip.textContent).toContain('Lämpötila, keskiarvo12,5 °C');
    expect(tooltip.textContent).toContain('Tuulivoimaennusteerittäin vähäinen');
    expect(tooltip.textContent).toContain('keskiarvo1 267,3 ¢/kWh');
    expect(tooltip.textContent).toContain('min–max1 234,5–1 300,0 ¢/kWh');
    expect(tooltip.textContent).toContain('keskiarvo1 250 MW');
    expect(mark.getAttribute('aria-describedby')).toBe('npWeatherTooltip');

    mark.dispatchEvent(new MouseEvent('mouseleave'));
    expect(tooltip.classList.contains('is-visible')).toBe(false);
  });

  it('uses English tooltip copy on the English page', () => {
    window.history.replaceState({}, '', '/index_en.html');
    window.weatherIcons.render([
      { timestamp: 100000, condition: 'rain', windLevel: 'strong' }
    ]);
    const mark = document.querySelector('.np-weather-mark');
    const tooltip = document.getElementById('npWeatherTooltip');
    mark.dispatchEvent(new MouseEvent('mouseenter'));

    expect(tooltip.textContent).toContain('General weatherrain');
    expect(tooltip.textContent).toContain('Temperature, average12.5 °C');
    expect(tooltip.textContent).toContain('Wind-power outlookhigh');
    expect(tooltip.textContent).toContain('average1,267.3 ¢/kWh');
  });

  it('aggregates actual-first price, wind power, and station temperatures by electricity day', () => {
    const summaries = window.weatherIcons.buildDailySummaries([
      {
        timestamp: '2025-01-01T00:00:00Z',
        Price_cpkWh: 5,
        PricePredict_cpkWh: 50,
        WindPowerMW: 1000,
        t_1: 2,
        t_2: 4
      },
      {
        timestamp: '2025-01-01T01:00:00Z',
        Price_cpkWh: null,
        PricePredict_cpkWh: 9,
        WindPowerMW: 2000,
        t_1: 6,
        t_2: 8
      }
    ]);
    expect(summaries.get('test-day')).toMatchObject({
      price: { average: 7, min: 5, max: 9 },
      windPower: { average: 1500, min: 1000, max: 2000 },
      temperature: { average: 5, min: 3, max: 7 }
    });
  });
});
