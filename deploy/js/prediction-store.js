(function () {
    const listeners = new Set();
    let latestPayload = null;

    function getLatest() {
        return latestPayload;
    }

    function notify(detail) {
        listeners.forEach(listener => {
            try {
                listener(detail);
            } catch (error) {
                console.error('predictionStore subscriber failed', error);
            }
        });
    }

    function setLatest(payload, options = {}) {
        latestPayload = payload || null;
        window.latestPredictionData = latestPayload;
        if (options.silent) {
            return;
        }
        const detail = latestPayload;
        if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
            window.dispatchEvent(new CustomEvent('prediction-data-ready', { detail }));
        }
        notify(detail);
    }

    function subscribe(handler, options = {}) {
        if (typeof handler !== 'function') {
            return () => {};
        }
        listeners.add(handler);
        if (options.immediate && latestPayload) {
            try {
                handler(latestPayload);
            } catch (error) {
                console.error('predictionStore immediate subscriber failed', error);
            }
        }
        return () => {
            listeners.delete(handler);
        };
    }

    window.predictionStore = Object.freeze({
        getLatest,
        setLatest,
        subscribe
    });
})();
