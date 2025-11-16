(function() {
    const DEFAULT_MODE = 'auto';
    const MEDIA_QUERY = '(prefers-color-scheme: dark)';

    const palettes = {
        page: {
            light: {
                vars: {
                    '--np-body-bg': '#f0f2f5',
                    '--np-card-bg': '#ffffff',
                    '--np-card-shadow': '0 6px 8px rgba(0, 0, 0, 0.1)',
                    '--np-text': 'rgba(51, 51, 51, 0.9)',
                    '--np-muted': '#666666',
                    '--np-heading': 'rgba(102, 102, 102, 0.8)',
                    '--np-link': '#000000',
                    '--np-link-hover': '#000000',
                    '--np-disclaimer-text': '#666666',
                    '--np-control-bg': '#f0f2f5',
                    '--np-control-border': '#dddddd',
                    '--np-control-hover': '#dddddd',
                    '--np-control-text': '#666666',
                    '--np-input-bg': 'rgba(255, 255, 255, 0.9)',
                    '--np-input-border': 'rgba(0, 0, 0, 0.2)',
                    '--np-input-outline': 'rgba(65, 131, 215, 0.35)',
                    '--np-table-header': 'rgba(0, 0, 0, 0.5)',
                    '--np-table-divider': 'rgba(0, 0, 0, 0.08)',
                    '--np-table-empty': 'rgba(0, 0, 0, 0.6)',
                    '--np-mobile-label': 'rgba(31, 61, 117, 0.6)',
                    '--np-calendar-status': 'rgba(51, 51, 51, 0.66)',
                    '--np-calendar-legend': 'rgba(31, 35, 40, 0.72)',
                    '--np-calendar-swatch-border': 'rgba(31, 35, 40, 0.08)',
                    '--np-llm-text': 'rgba(102, 102, 102, 0.7)',
                    '--np-topbar-text': '#666666',
                    '--np-topbar-border': 'rgba(0, 0, 0, 0.08)',
                    '--np-theme-button-bg': '#f0f2f5',
                    '--np-theme-button-border': '#dddddd',
                    '--np-theme-button-text': '#666666',
                    '--np-theme-button-active': '#ffffff',
                    '--np-theme-button-active-text': '#000000',
                    '--np-pulse-a': 'rgba(135, 206, 235, 0.1)',
                    '--np-pulse-b': 'rgba(135, 206, 235, 0.25)',
                    '--np-price-calendar-border': '#ffffff',
                    '--np-price-calendar-empty': 'rgba(255, 255, 255, 0)',
                    '--np-price-calendar-null': 'rgba(0, 0, 0, 0)',
                    '--np-theme-chip-shadow': 'none',
                    '--np-topbar-bg': 'transparent'
                },
                metaColor: '#f0f2f5'
            },
            dark: {
                vars: {
                    '--np-body-bg': 'black',
                    '--np-card-bg': 'rgba(28, 28, 28, 1)',
                    '--np-card-shadow': 'none',
                    '--np-text': 'whitesmoke',
                    '--np-muted': 'silver',
                    '--np-heading': 'gainsboro',
                    '--np-link': 'whitesmoke',
                    '--np-link-hover': 'white',
                    '--np-disclaimer-text': 'silver',
                    '--np-control-bg': 'dimgrey',
                    '--np-control-border': 'slategray',
                    '--np-control-hover': 'gray',
                    '--np-control-text': 'whitesmoke',
                    '--np-input-bg': 'gray',
                    '--np-input-border': 'darkgray',
                    '--np-input-outline': 'gainsboro',
                    '--np-table-header': 'lightgray',
                    '--np-table-divider': 'darkslategray',
                    '--np-table-empty': 'silver',
                    '--np-mobile-label': 'lightgray',
                    '--np-calendar-status': 'silver',
                    '--np-calendar-legend': 'gainsboro',
                    '--np-calendar-swatch-border': 'gray',
                    '--np-llm-text': 'silver',
                    '--np-topbar-text': 'whitesmoke',
                    '--np-topbar-border': 'slategray',
                    '--np-theme-button-bg': 'dimgrey',
                    '--np-theme-button-border': 'slategray',
                    '--np-theme-button-text': 'whitesmoke',
                    '--np-theme-button-active': 'whitesmoke',
                    '--np-theme-button-active-text': 'black',
                    '--np-pulse-a': 'dimgray',
                    '--np-pulse-b': 'gray',
                    '--np-price-calendar-border': 'black',
                    '--np-price-calendar-empty': 'black',
                    '--np-price-calendar-null': 'black',
                    '--np-theme-chip-shadow': 'none',
                    '--np-topbar-bg': 'transparent'
                },
                metaColor: 'black'
            }
        },
        prediction: {
            light: {
                axis: '#666666',
                grid: 'silver',
                tooltipBg: '#ffffff',
                tooltipText: 'rgba(51, 51, 51, 0.9)',
                tooltipBorder: 'rgba(31, 35, 40, 0.12)',
                legendText: '#666666',
                forecastLegend: 'skyblue',
                markLineLabel: 'Black',
                markLineLine: 'rgba(51, 51, 51, 0.9)',
                chartBackground: 'transparent',
                sahkotinBar: 'lime',
                sahkotinBarOpacity: 0.10,
                sahkotinLine: 'lime',
                spikeMarker: 'crimson',
                outOfRange: '#999999',
                forecastBackgroundBar: 'deepskyblue',
                forecastVisualPieces: [
                    { lte: 5, color: 'skyblue', opacity: 1.0 },
                    { gt: 5, lte: 10, color: 'deepskyblue', opacity: 1.0 },
                    { gt: 10, lte: 15, color: 'dodgerblue', opacity: 1.0 },
                    { gt: 15, lte: 20, color: 'blue', opacity: 1.0 },
                    { gt: 20, lte: 30, color: 'darkblue', opacity: 1.0 },
                    { gt: 30, color: 'midnightblue', opacity: 1.0 }
                ]
            },
            dark: {
                axis: 'gainsboro',
                grid: 'rgba(69, 69, 69, 1)',
                tooltipBg: 'black',
                tooltipText: 'whitesmoke',
                tooltipBorder: 'slategray',
                legendText: 'whitesmoke',
                forecastLegend: 'skyblue',
                markLineLabel: 'white',
                markLineLine: 'gainsboro',
                chartBackground: 'transparent',
                sahkotinBar: 'lime',
                sahkotinBarOpacity: 0.10,
                sahkotinLine: 'lime',
                spikeMarker: 'crimson',
                outOfRange: '#999999',
                forecastBackgroundBar: 'deepskyblue',
                forecastVisualPieces: [
                    { lte: 5, color: 'rgba(135, 206, 235, 1.0)', opacity: 1.0 },
                    { gt: 5, lte: 10, color: 'rgba(108, 197, 255, 1.0)', opacity: 1.0 },
                    { gt: 10, lte: 15, color: 'rgba(83, 181, 255, 1.0)', opacity: 1.0 },
                    { gt: 15, lte: 20, color: 'rgba(61, 165, 255, 1.0)', opacity: 1.0 },
                    { gt: 20, lte: 30, color: 'rgba(42, 148, 255, 1.0)', opacity: 1.0 },
                    { gt: 30, color: 'rgba(28, 132, 255, 1.0)', opacity: 1.0 }
                ]
            }
        },
        history: {
            light: {
                axis: '#666666',
                grid: 'silver',
                tooltipBg: '#ffffff',
                tooltipText: 'rgba(51, 51, 51, 0.9)',
                tooltipBorder: 'rgba(31, 35, 40, 0.12)',
                legendText: '#666666',
                markLineLabel: 'Black',
                markLineLine: 'rgba(51, 51, 51, 0.9)',
                zoomBackground: '#f0f2f5',
                zoomBorder: '#dddddd',
                swarmLine: 'dodgerblue'
            },
            dark: {
                axis: 'gainsboro',
                grid: 'rgba(69, 69, 69, 1)',
                tooltipBg: 'black',
                tooltipText: 'whitesmoke',
                tooltipBorder: 'slategray',
                legendText: 'whitesmoke',
                markLineLabel: 'white',
                markLineLine: 'gainsboro',
                zoomBackground: 'dimgrey',
                zoomBorder: 'slategray',
                swarmLine: 'deepskyblue'
            }
        },
        windpower: {
            light: {
                axis: '#666666',
                grid: 'silver',
                tooltipBg: '#ffffff',
                tooltipText: 'rgba(51, 51, 51, 0.9)',
                tooltipBorder: 'rgba(31, 35, 40, 0.12)',
                legendText: '#666666',
                markLineLabel: 'Black',
                markLineLine: 'rgba(51, 51, 51, 0.9)',
                barColor: '#AEB6BF',
                areaFill: 'rgba(135, 206, 250, 0.2)',
                outOfRange: '#999999',
                windLegend: 'dodgerblue',
                windVisualPieces: [
                    { lte: 1, color: 'red' },
                    { gt: 1, lte: 2, color: 'skyblue' },
                    { gt: 2, lte: 3, color: 'deepskyblue' },
                    { gt: 3, lte: 4, color: 'dodgerblue' },
                    { gt: 4, lte: 5, color: 'blue' },
                    { gt: 5, lte: 6, color: 'mediumblue' },
                    { gt: 6, lte: 7, color: 'darkblue' },
                    { gt: 7, color: 'midnightblue' }
                ]
            },
            dark: {
                axis: 'gainsboro',
                grid: 'rgba(69, 69, 69, 1)',
                tooltipBg: 'black',
                tooltipText: 'whitesmoke',
                tooltipBorder: 'slategray',
                legendText: 'whitesmoke',
                markLineLabel: 'white',
                markLineLine: 'gainsboro',
                barColor: 'lightgray',
                areaFill: 'rgba(30, 144, 255, 0.1)',
                outOfRange: 'darkgray',
                windLegend: 'dodgerblue',
                windVisualPieces: [
                    { lte: 1, color: 'red' },
                    { gt: 1, lte: 2, color: 'rgba(135, 206, 235, 1.0)' },
                    { gt: 2, lte: 3, color: 'rgba(108, 197, 255, 1.0)' },
                    { gt: 3, lte: 4, color: 'rgba(83, 181, 255, 1.0)' },
                    { gt: 4, lte: 5, color: 'rgba(61, 165, 255, 1.0)' },
                    { gt: 5, lte: 6, color: 'rgba(42, 148, 255, 1.0)' },
                    { gt: 6, lte: 7, color: 'rgba(32, 134, 255, 1.0)' },
                    { gt: 7, color: 'rgba(28, 132, 255, 1.0)' }
                ]
            }
        },
        calendar: {
            light: {
                axis: 'rgba(31, 35, 40, 0.72)',
                fallback: 'rgba(31, 35, 40, 0.12)',
                border: 'rgba(255, 255, 255, 1)',
                empty: 'rgba(255, 255, 255, 0)',
                emphasis: 'dodgerblue',
                legendText: 'rgba(31, 35, 40, 0.72)'
            },
            dark: {
                axis: 'gainsboro',
                fallback: 'dimgray',
                border: 'black',
                empty: 'black',
                emphasis: 'dodgerblue',
                legendText: 'whitesmoke'
            }
        },
        cheapest: {
            light: {
                text: 'rgba(51, 51, 51, 0.88)',
                header: 'rgba(0, 0, 0, 0.5)',
                divider: 'rgba(0, 0, 0, 0.08)',
                empty: 'rgba(0, 0, 0, 0.6)',
                dots: {
                    '3': '#87CEEB',
                    '6': '#00BFFF',
                    '12': '#1E90FF'
                }
            },
            dark: {
                text: 'whitesmoke',
                header: 'lightgray',
                divider: 'slategray',
                empty: 'silver',
                dots: {
                    '3': '#87CEEB',
                    '6': '#00BFFF',
                    '12': '#1E90FF'
                }
            }
        },
        featuresUmap: {
            light: {
                background: '#ffffff',
                scenePlane: 'rgba(235, 240, 248, 0.7)',
                grid: 'dimgray',
                legendText: '#666666',
                hoverBg: '#ffffff',
                hoverText: 'rgba(51, 51, 51, 0.9)'
            },
            dark: {
                background: 'black',
                scenePlane: 'rgba(28, 28, 28, 1)',
                grid: 'rgba(64, 64, 64, 1)',
                legendText: 'whitesmoke',
                hoverBg: 'black',
                hoverText: 'whitesmoke'
            }
        }
    };

    function detectSystemDark() {
        if (typeof window.matchMedia !== 'function') {
            return false;
        }
        return window.matchMedia(MEDIA_QUERY).matches;
    }

    function resolveEffectiveMode(preference) {
        if (preference === 'light' || preference === 'dark') {
            return preference;
        }
        return detectSystemDark() ? 'dark' : 'light';
    }

    function applyPageVariables(mode) {
        const root = document.documentElement;
        root.setAttribute('data-theme', mode);
        const pagePalette = palettes.page[mode] || palettes.page.light;
        const vars = (pagePalette && pagePalette.vars) || {};
        Object.keys(vars).forEach(key => {
            root.style.setProperty(key, vars[key]);
        });
        root.style.setProperty('color-scheme', mode === 'dark' ? 'dark' : 'light');
        const meta = document.querySelector('meta[name="theme-color"]');
        if (meta && pagePalette && pagePalette.metaColor) {
            meta.setAttribute('content', pagePalette.metaColor);
        }
    }

    const listeners = new Set();
    let preferredMode = DEFAULT_MODE;
    let effectiveMode = resolveEffectiveMode(preferredMode);

    applyPageVariables(effectiveMode);

    function notify() {
        const payload = {
            mode: preferredMode,
            effectiveMode,
            palettes
        };
        listeners.forEach(listener => {
            try {
                listener(payload);
            } catch (error) {
                console.warn('Theme listener failed', error);
            }
        });
    }

    function handleSystemChange(event) {
        if (preferredMode !== 'auto') {
            return;
        }
        effectiveMode = event.matches ? 'dark' : 'light';
        applyPageVariables(effectiveMode);
        notify();
    }

    if (typeof window.matchMedia === 'function') {
        const query = window.matchMedia(MEDIA_QUERY);
        if (typeof query.addEventListener === 'function') {
            query.addEventListener('change', handleSystemChange);
        } else if (typeof query.addListener === 'function') {
            query.addListener(handleSystemChange);
        }
    }

    window.__NP_THEME__ = {
        palettes,
        getMode() {
            return preferredMode;
        },
        getEffectiveMode() {
            return effectiveMode;
        },
        setMode(nextMode) {
            const normalized = nextMode === 'light' || nextMode === 'dark' ? nextMode : DEFAULT_MODE;
            preferredMode = normalized;
            effectiveMode = resolveEffectiveMode(preferredMode);
            applyPageVariables(effectiveMode);
            notify();
        },
        getPalette(scope) {
            const group = palettes[scope];
            if (!group) {
                return null;
            }
            return group[effectiveMode] || group.light;
        },
        subscribe(listener) {
            if (typeof listener !== 'function') {
                return () => {};
            }
            listeners.add(listener);
            listener({
                mode: preferredMode,
                effectiveMode,
                palettes
            });
            return () => listeners.delete(listener);
        }
    };
})();
