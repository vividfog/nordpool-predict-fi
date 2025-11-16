import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { loadScript } from './utils';

const READY_EVENT = 'np-theme-service-ready';

function resetGlobals(originalTheme) {
    if (originalTheme) {
        window.__NP_THEME__ = originalTheme;
    } else {
        delete window.__NP_THEME__;
    }
    delete window.themeService;
    delete window.watchThemePalette;
    delete window.getChartPalette;
}

describe('deploy/js/theme-service.js', () => {
    let originalTheme;
    let currentPalettes;
    let runtimeSubscriber;

    beforeEach(() => {
        originalTheme = window.__NP_THEME__ || null;
        currentPalettes = {
            prediction: {
                light: { axis: '#111111' }
            }
        };
        runtimeSubscriber = null;
        window.__NP_THEME__ = {
            getPalette: scope => currentPalettes[scope]?.light || null,
            getMode: vi.fn(() => 'auto'),
            getEffectiveMode: vi.fn(() => 'light'),
            setMode: vi.fn(),
            subscribe: vi.fn(handler => {
                runtimeSubscriber = payload => {
                    currentPalettes = payload.palettes || currentPalettes;
                    handler(payload);
                };
                handler({ mode: 'auto', effectiveMode: 'light', palettes: currentPalettes });
                return () => {
                    runtimeSubscriber = null;
                };
            })
        };
        delete window.themeService;
        delete window.watchThemePalette;
        delete window.getChartPalette;
    });

    afterEach(() => {
        resetGlobals(originalTheme);
    });

    it('notifies palette watchers and refreshes caches', () => {
        loadScript('deploy/js/theme-service.js');
        const handler = vi.fn();
        window.watchThemePalette('prediction', handler);
        expect(handler).toHaveBeenCalledWith(currentPalettes.prediction.light);

        const nextPalettes = {
            prediction: {
                light: { axis: '#222222' }
            }
        };
        runtimeSubscriber({ mode: 'auto', effectiveMode: 'light', palettes: nextPalettes });
        expect(handler).toHaveBeenCalledTimes(2);
        expect(handler.mock.calls.at(-1)[0]).toEqual(nextPalettes.prediction.light);
    });

    it('forwards subscribe payloads and dispatches readiness event', () => {
        const readySpy = vi.fn();
        window.addEventListener(READY_EVENT, readySpy);
        loadScript('deploy/js/theme-service.js');

        expect(typeof window.themeService.subscribe).toBe('function');
        const handler = vi.fn();
        const unsubscribe = window.themeService.subscribe(handler);
        expect(handler).toHaveBeenCalledWith({
            mode: 'auto',
            effectiveMode: 'light',
            palettes: currentPalettes
        });
        expect(typeof unsubscribe).toBe('function');

        const nextPayload = {
            mode: 'dark',
            effectiveMode: 'dark',
            palettes: currentPalettes
        };
        runtimeSubscriber(nextPayload);
        expect(handler).toHaveBeenCalledTimes(2);
        expect(handler).toHaveBeenLastCalledWith(nextPayload);

        expect(readySpy).toHaveBeenCalled();
        expect(readySpy.mock.calls[0][0].detail).toBe(window.themeService);
        window.removeEventListener(READY_EVENT, readySpy);
    });
});
