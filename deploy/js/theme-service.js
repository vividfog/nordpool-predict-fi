(function () {
    const runtimeTheme = window.__NP_THEME__ || null;
    const PALETTE_CACHE = new Map();
    const SUBSCRIBERS = new Set();

    function resolvePalette(scope) {
        if (!runtimeTheme || typeof runtimeTheme.getPalette !== 'function') {
            return null;
        }
        if (PALETTE_CACHE.has(scope)) {
            return PALETTE_CACHE.get(scope);
        }
        const palette = runtimeTheme.getPalette(scope) || null;
        PALETTE_CACHE.set(scope, palette);
        return palette;
    }

    function getPalette(scope) {
        if (!scope) {
            return null;
        }
        return resolvePalette(scope);
    }

    function subscribe(scope, handler) {
        if (typeof handler !== 'function') {
            return () => {};
        }
        const entry = { scope, handler };
        SUBSCRIBERS.add(entry);
        const palette = getPalette(scope);
        if (palette) {
            handler(palette);
        }
        return () => {
            SUBSCRIBERS.delete(entry);
        };
    }

    function notify(payload) {
        if (!payload || !payload.palettes) {
            return;
        }
        PALETTE_CACHE.clear();
        SUBSCRIBERS.forEach(entry => {
            try {
                entry.handler(getPalette(entry.scope));
            } catch (error) {
                console.error('themeService subscriber failed', error);
            }
        });
    }

    function init() {
        if (!runtimeTheme || typeof runtimeTheme.subscribe !== 'function') {
            return;
        }
        runtimeTheme.subscribe(payload => {
            notify(payload);
        });
    }

    function watchThemePalette(scope, handler) {
        return subscribe(scope, handler);
    }

    function getEffectiveMode() {
        if (runtimeTheme && typeof runtimeTheme.getEffectiveMode === 'function') {
            return runtimeTheme.getEffectiveMode();
        }
        return null;
    }

    function getMode() {
        if (runtimeTheme && typeof runtimeTheme.getMode === 'function') {
            return runtimeTheme.getMode();
        }
        return 'auto';
    }

    function setMode(option) {
        if (runtimeTheme && typeof runtimeTheme.setMode === 'function') {
            runtimeTheme.setMode(option);
        }
    }

    init();

    window.themeService = Object.freeze({
        getPalette,
        watchThemePalette,
        getMode,
        getEffectiveMode,
        setMode
    });

    window.watchThemePalette = watchThemePalette;
    window.getChartPalette = getPalette;
})();
