// ==========================================================================
// 3D embedding of model features (UMAP + Plotly)
// ==========================================================================

(function () {
    //#region setup
    const AUTOROTATE_SPEED = 0.0015; // Radians per frame
    const AUTOROTATE_IDLE_DELAY_MS = 5000;
    const AUTOROTATE_PREFERS_REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';
    // Maintains a gentle autorotation that pauses while the user interacts.
    const autorotateState = {
        container: null,
        animationId: null,
        pausedUntil: 0,
        isProgrammatic: false,
        angleOffset: 0,
        baseAngle: null,
        radius: null,
        baseEyeZ: null,
        speed: AUTOROTATE_SPEED,
        skip: false,
        listenersAttached: false,
        handlers: {},
        lastCamera: null,
    };

    //#region utilities
    function isAutorotateDisabled() {
        if (autorotateState.skip) return true;
        if (typeof window === 'undefined') return true;
        const reducedMotion = Boolean(
            window.matchMedia
            && window.matchMedia(AUTOROTATE_PREFERS_REDUCED_MOTION_QUERY).matches
        );
        const disabledFlag = Boolean(window.disableFeatureEmbeddingSpin);
        autorotateState.skip = reducedMotion || disabledFlag;
        return autorotateState.skip;
    }

    function getCurrentCamera(container) {
        return container?._fullLayout?.scene?.camera;
    }

    function isFiniteVector(vector) {
        return vector
            && Number.isFinite(vector.x)
            && Number.isFinite(vector.y)
            && Number.isFinite(vector.z);
    }

    function getNow() {
        if (typeof performance !== 'undefined' && typeof performance.now === 'function') {
            return performance.now();
        }
        return Date.now();
    }

    function updateBaseCamera(camera) {
        const eye = camera?.eye;
        if (!isFiniteVector(eye)) {
            return false;
        }
        const radiusSq = (eye.x ** 2) + (eye.y ** 2);
        if (!Number.isFinite(radiusSq) || radiusSq <= 0) {
            return false;
        }
        autorotateState.radius = Math.sqrt(radiusSq);
        if (Number.isFinite(eye.z)) {
            autorotateState.baseEyeZ = eye.z;
        }
        if (!Number.isFinite(autorotateState.baseEyeZ)) {
            return false;
        }
        autorotateState.baseAngle = Math.atan2(eye.y, eye.x);
        autorotateState.angleOffset = 0;
        autorotateState.lastCamera = cloneCamera(camera);
        return true;
    }

    function computeNextEye() {
        if (
            !Number.isFinite(autorotateState.baseAngle)
            || !Number.isFinite(autorotateState.radius)
            || !Number.isFinite(autorotateState.baseEyeZ)
        ) {
            return null;
        }
        const angle = autorotateState.baseAngle + autorotateState.angleOffset;
        const cos = Math.cos(angle);
        const sin = Math.sin(angle);
        return {
            x: autorotateState.radius * cos,
            y: autorotateState.radius * sin,
            z: autorotateState.baseEyeZ,
        };
    }

    //#region runtime
    function pauseAutorotation() {
        if (!autorotateState.container) return;
        const now = getNow();
        autorotateState.pausedUntil = Math.max(
            autorotateState.pausedUntil,
            now + AUTOROTATE_IDLE_DELAY_MS,
        );
    }

    function autorotateLoop() {
        if (!autorotateState.container) {
            autorotateState.animationId = null;
            return;
        }
        const now = getNow();
        if (now < autorotateState.pausedUntil) {
            autorotateState.animationId = window.requestAnimationFrame(autorotateLoop);
            return;
        }
        if (!Number.isFinite(autorotateState.baseAngle)) {
            const camera = getCurrentCamera(autorotateState.container)
                || autorotateState.lastCamera;
            if (!updateBaseCamera(camera)) {
                autorotateState.animationId = window.requestAnimationFrame(autorotateLoop);
                return;
            }
        }
        autorotateState.angleOffset += autorotateState.speed;
        const nextEye = computeNextEye();
        if (!nextEye) {
            autorotateState.animationId = window.requestAnimationFrame(autorotateLoop);
            return;
        }
        const currentCamera = cloneCamera(
            autorotateState.lastCamera || getCurrentCamera(autorotateState.container),
        );
        currentCamera.eye = { ...nextEye };
        autorotateState.lastCamera = cloneCamera(currentCamera);
        const cameraPayload = { eye: currentCamera.eye };
        if (isFiniteVector(currentCamera.center)) {
            cameraPayload.center = currentCamera.center;
        }
        if (isFiniteVector(currentCamera.up)) {
            cameraPayload.up = currentCamera.up;
        }
        autorotateState.isProgrammatic = true;
        Promise.resolve(Plotly.relayout(autorotateState.container, {
            'scene.camera': cameraPayload,
        }))
            .catch((err) => {
                console.warn('Feature embedding autorotate relayout failed', err);
            })
            .finally(() => {
                autorotateState.isProgrammatic = false;
                if (autorotateState.container) {
                    autorotateState.animationId = window.requestAnimationFrame(autorotateLoop);
                } else {
                    autorotateState.animationId = null;
                }
            });
    }

    function startAutorotation() {
        if (!autorotateState.container) return;
        if (autorotateState.animationId !== null) return;
        autorotateState.animationId = window.requestAnimationFrame(autorotateLoop);
    }

    function detachAutorotateListeners() {
        if (!autorotateState.listenersAttached) {
            autorotateState.handlers = {};
            return;
        }
        const { container } = autorotateState;
        if (!container || typeof container.removeListener !== 'function') {
            autorotateState.listenersAttached = false;
            autorotateState.handlers = {};
            return;
        }
        const { relayouting, relayout, hover } = autorotateState.handlers;
        if (relayouting) container.removeListener('plotly_relayouting', relayouting);
        if (relayout) container.removeListener('plotly_relayout', relayout);
        if (hover) container.removeListener('plotly_hover', hover);
        autorotateState.listenersAttached = false;
        autorotateState.handlers = {};
    }

    function stopAutorotation(detach = false) {
        if (autorotateState.animationId !== null) {
            window.cancelAnimationFrame(autorotateState.animationId);
            autorotateState.animationId = null;
        }
        if (detach) {
            detachAutorotateListeners();
            autorotateState.container = null;
        }
        autorotateState.pausedUntil = 0;
        autorotateState.baseAngle = null;
        autorotateState.radius = null;
        autorotateState.baseEyeZ = null;
        autorotateState.lastCamera = null;
    }

    //#region camera_merge
    function cloneCamera(camera) {
        if (!camera) return { eye: {}, center: {}, up: {} };
        return {
            eye: camera.eye ? { ...camera.eye } : {},
            center: camera.center ? { ...camera.center } : {},
            up: camera.up ? { ...camera.up } : {},
            projection: camera.projection ? { ...camera.projection } : {},
        };
    }

    function mergeCameraComponent(camera, property, value) {
        if (!camera[property]) {
            camera[property] = {};
        }
        if (value && typeof value === 'object') {
            Object.keys(value).forEach((axis) => {
                camera[property][axis] = value[axis];
            });
            return property === 'eye';
        }
        return false;
    }

    function buildCameraFromEvent(eventData, fallbackCamera) {
        if (!eventData) return null;
        const camera = cloneCamera(fallbackCamera);
        let eyeTouched = false;

        const directCamera = eventData['scene.camera']
            || eventData.scene?.camera;
        if (directCamera) {
            eyeTouched = mergeCameraComponent(camera, 'eye', directCamera.eye) || eyeTouched;
            mergeCameraComponent(camera, 'center', directCamera.center);
            mergeCameraComponent(camera, 'up', directCamera.up);
            if (directCamera.projection) {
                camera.projection = { ...directCamera.projection };
            }
        }

        Object.keys(eventData).forEach((key) => {
            if (!key.startsWith('scene.camera')) return;
            const parts = key.split('.');
            if (parts.length < 3) return;
            const property = parts[2];
            const axis = parts[3];
            if (!property) return;
            if (property === 'projection' && axis === undefined) {
                camera.projection = eventData[key];
                return;
            }
            if (!axis) return;
            if (!camera[property]) camera[property] = {};
            camera[property][axis] = eventData[key];
            if (property === 'eye' && Number.isFinite(eventData[key])) {
                eyeTouched = true;
            }
        });

        if (!isFiniteVector(camera.eye)) {
            if (eyeTouched) {
                return null;
            }
            if (fallbackCamera) {
                return cloneCamera(fallbackCamera);
            }
            return null;
        }
        return camera;
    }

    function handleRelayout(eventData) {
        if (autorotateState.isProgrammatic) return;
        if (!eventData) return;
        const updatedCamera = Object.keys(eventData).some((key) => key.startsWith('scene.camera'));
        if (updatedCamera) {
            pauseAutorotation();
            const cameraFromEvent = buildCameraFromEvent(eventData, autorotateState.lastCamera)
                || getCurrentCamera(autorotateState.container);
            updateBaseCamera(cameraFromEvent);
        }
    }

    function attachAutorotateListeners(container) {
        if (autorotateState.listenersAttached) return;
        if (!container || typeof container.on !== 'function') return;
        autorotateState.handlers = {
            relayouting: () => {
                if (!autorotateState.isProgrammatic) pauseAutorotation();
            },
            relayout: handleRelayout,
            hover: () => {
                if (!autorotateState.isProgrammatic) pauseAutorotation();
            },
        };
        container.on('plotly_relayouting', autorotateState.handlers.relayouting);
        container.on('plotly_relayout', autorotateState.handlers.relayout);
        container.on('plotly_hover', autorotateState.handlers.hover);
        autorotateState.listenersAttached = true;
    }

    function refreshAutorotation(container) {
        if (!container) return;
        if (isAutorotateDisabled()) {
            stopAutorotation(true);
            return;
        }
        if (autorotateState.container && autorotateState.container !== container) {
            stopAutorotation(true);
        }
        autorotateState.container = container;
        attachAutorotateListeners(container);
        updateBaseCamera(getCurrentCamera(container));
        startAutorotation();
    }

    //#region embed_helpers
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

    //#region embed_fetch
    let featureEmbeddingPending = null;
    let lastEmbeddingToken = 0;
    let hasRenderedEmbedding = false;

    function buildFeatureEmbeddingUrl(token) {
        const base = `${baseUrl}/feature_embedding.json`;
        if (typeof window.applyCacheToken === 'function') {
            return window.applyCacheToken(base, token);
        }
        if (Number.isFinite(token) && typeof window.createCacheBustedUrl === 'function') {
            return window.createCacheBustedUrl(base, token);
        }
        return base;
    }

    /**
     * Fetches feature embedding payload and renders it into the provided container.
     * Skips duplicate requests by reusing the pending promise and applies cache-busting when a token is supplied.
     * @param {HTMLElement} container Target element for Plotly rendering.
     * @param {number} [token] Optional cache-busting token (typically a timestamp).
     * @returns {Promise<void>|null} Resolves once the embedding is processed; null if container invalid.
     */
    function loadFeatureEmbedding(container, token) {
        if (!container) {
            return;
        }

        if (featureEmbeddingPending) {
            return featureEmbeddingPending;
        }

        if (typeof Plotly === 'undefined') {
            container.textContent = isEnglish()
                ? 'Plotly library not loaded.'
                : 'Plotly-kirjastoa ei saatu ladattua.';
            hasRenderedEmbedding = false;
            return;
        }

        const effectiveToken = Number.isFinite(token) ? token : Date.now();
        const requestUrl = buildFeatureEmbeddingUrl(effectiveToken);
        featureEmbeddingPending = fetch(requestUrl, { cache: 'no-cache' })
            .then((response) => {
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                return response.json();
            })
            .then((payload) => {
                if (!payload.features || !payload.features.length) {
                    container.textContent = isEnglish()
                        ? 'Feature embedding will appear here after the next deployment.'
                        : 'Piirteiden upotus tulee näkyviin seuraavan ajon jälkeen.';
                    hasRenderedEmbedding = false;
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

                const config = {
                    displayModeBar: false,
                    responsive: true,
                };

                const renderPromise = hasRenderedEmbedding
                    ? Plotly.react(container, traces, layout, config)
                    : Plotly.newPlot(container, traces, layout, config);

                return renderPromise
                    .then(() => {
                        hasRenderedEmbedding = true;
                        lastEmbeddingToken = effectiveToken;
                        refreshAutorotation(container);
                    })
                    .catch((renderErr) => {
                        hasRenderedEmbedding = false;
                        stopAutorotation(true);
                        throw renderErr;
                    });
            })
            .catch((err) => {
                console.error('Feature embedding error', err);
                container.textContent = isEnglish()
                    ? 'Unable to load feature embedding.'
                    : 'Piirteiden upotusta ei voitu ladata.';
                hasRenderedEmbedding = false;
                stopAutorotation(true);
            })
            .finally(() => {
                featureEmbeddingPending = null;
            });

        return featureEmbeddingPending;
    }

    function init() {
        const container = document.getElementById('featureEmbeddingChart');
        if (!container) return;
        loadFeatureEmbedding(container);

        window.addEventListener('prediction-data-ready', event => {
            if (featureEmbeddingPending) {
                return;
            }
            const generatedAt = Number(event?.detail?.generatedAt);
            if (!Number.isFinite(generatedAt) || generatedAt <= lastEmbeddingToken) {
                return;
            }
            loadFeatureEmbedding(container, generatedAt);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
