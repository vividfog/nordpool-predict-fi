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
    window.dataClient = {
      fetchJson: vi.fn().mockResolvedValue([
        { timestamp: 100000, condition: 'clear-day', windLevel: 'calm' },
        { timestamp: 200000, condition: 'rain', windLevel: 'strong' }
      ])
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
    expect(tooltip.textContent).toContain('Yleissää: selkeää');
    expect(tooltip.textContent).toContain('Tuulivoimaennuste: erittäin vähäinen');
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

    expect(tooltip.textContent).toContain('General weather: rain');
    expect(tooltip.textContent).toContain('Wind-power outlook: high');
  });
});
