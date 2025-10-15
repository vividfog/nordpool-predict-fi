//#region feature_umap
// ==========================================================================
// 3D embedding of model features (UMAP + Plotly)
// ==========================================================================

(function () {
    function isEnglish() {
        return window.location.pathname.includes('index_en');
    }

    function formatNumber(value) {
        if (value === null || value === undefined || Number.isNaN(value)) {
            return isEnglish() ? '—' : '–';
        }
        const abs = Math.abs(value);
        if (abs >= 1000) return value.toFixed(0);
        if (abs >= 100) return value.toFixed(1);
        if (abs >= 10) return value.toFixed(2);
        return value.toFixed(3);
    }

    function toHoverText(feature, groups) {
        const locale = isEnglish() ? 'en' : 'fi';
        const groupMeta = groups?.[feature.group] || {};
        const groupLabel = groupMeta[locale] || feature.group;
        const corrLabel = isEnglish() ? 'Corr. with price' : 'Korrelaatio hintaan';
        const latestLabel = isEnglish() ? 'Latest' : 'Tuorein arvo';
        const meanLabel = isEnglish() ? 'Mean' : 'Keskiarvo';
        const stdLabel = isEnglish() ? 'Std dev' : 'Keskihajonta';
        return `<b>${feature.label}</b><br>${groupLabel}<br>${corrLabel}: ${formatNumber(feature.corr_price)}
<br>${latestLabel}: ${formatNumber(feature.latest)}<br>${meanLabel}: ${formatNumber(feature.mean)} (${stdLabel}: ${formatNumber(feature.std)})`;
    }

    function buildTraces(payload) {
        const locale = isEnglish() ? 'en' : 'fi';
        const groups = payload.groups || {};
        const grouping = {};
        (payload.features || []).forEach((feature) => {
            if (!grouping[feature.group]) grouping[feature.group] = [];
            grouping[feature.group].push(feature);
        });

        const defaultColors = [
            '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728',
            '#9467bd', '#8c564b', '#e377c2', '#7f7f7f',
            '#bcbd22', '#17becf',
        ];

        return Object.keys(grouping).map((groupKey, idx) => {
            const items = grouping[groupKey];
            items.sort((a, b) => a.label.localeCompare(b.label, locale === 'fi' ? 'fi-FI' : 'en-US'));
            const meta = groups[groupKey] || {};
            const color = meta.color || defaultColors[idx % defaultColors.length];
            const markerSizes = items.map((item) => 7 + Math.min(18, Math.abs(item.corr_price || 0) * 18));
            return {
                type: 'scatter3d',
                mode: 'markers',
                name: meta[locale] || groupKey,
                x: items.map((item) => item.x),
                y: items.map((item) => item.y),
                z: items.map((item) => item.z),
                hoverinfo: 'text',
                text: items.map((item) => toHoverText(item, groups)),
                marker: {
                    size: markerSizes,
                    color,
                    opacity: 0.9,
                    line: { color: 'rgba(255,255,255,0.6)', width: 0.5 },
                },
            };
        });
    }

    function init() {
        const container = document.getElementById('featureEmbeddingChart');
        if (!container) return;
        if (typeof Plotly === 'undefined') {
            container.textContent = isEnglish()
                ? 'Plotly library not loaded.'
                : 'Plotly-kirjastoa ei saatu ladattua.';
            return;
        }

        const url = `${baseUrl}/feature_embedding.json`;
        fetch(url)
            .then((response) => {
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                return response.json();
            })
            .then((payload) => {
                if (!payload.features || !payload.features.length) {
                    container.textContent = isEnglish()
                        ? 'Feature embedding will appear here after the next deployment.'
                        : 'Piirteiden upotus tulee näkyviin seuraavan ajon jälkeen.';
                    return;
                }

                const traces = buildTraces(payload);
                const layout = {
                    margin: { l: 0, r: 0, b: 0, t: 10 },
                    scene: {
                        aspectmode: 'cube',
                        xaxis: {
                            showbackground: true,
                            backgroundcolor: 'rgba(235,240,248,0.7)',
                            showgrid: true,
                            zeroline: false,
                            ticks: '',
                            title: '',
                        },
                        yaxis: {
                            showbackground: true,
                            backgroundcolor: 'rgba(235,240,248,0.7)',
                            showgrid: true,
                            zeroline: false,
                            ticks: '',
                            title: '',
                        },
                        zaxis: {
                            showbackground: true,
                            backgroundcolor: 'rgba(235,240,248,0.7)',
                            showgrid: true,
                            zeroline: false,
                            ticks: '',
                            title: '',
                        },
                    },
                    legend: {
                        orientation: 'h',
                        x: 0,
                        y: 1.05,
                    },
                    hovermode: 'closest',
                };

                Plotly.newPlot(container, traces, layout, {
                    displayModeBar: false,
                    responsive: true,
                });
            })
            .catch((err) => {
                console.error('Feature embedding error', err);
                container.textContent = isEnglish()
                    ? 'Unable to load feature embedding.'
                    : 'Piirteiden upotusta ei voitu ladata.';
            });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
