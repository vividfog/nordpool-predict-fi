// ==========================================================================
// Shared data fetching utilities
// ==========================================================================

(function () {
    const DEFAULT_REQUEST_INIT = Object.freeze({ cache: 'no-cache' });

    function applyRequestInit(overrides) {
        if (!overrides) {
            return { ...DEFAULT_REQUEST_INIT };
        }
        return Object.assign({}, DEFAULT_REQUEST_INIT, overrides);
    }

    function ensureOk(response, url) {
        if (!response || !response.ok) {
            const status = response ? response.status : 'unknown';
            throw new Error(`Request failed (${status}) for ${url}`);
        }
        return response;
    }

    function fetchJson(url, init) {
        return fetch(url, applyRequestInit(init))
            .then((response) => ensureOk(response, url))
            .then((response) => response.json());
    }

    function fetchText(url, init) {
        return fetch(url, applyRequestInit(init))
            .then((response) => ensureOk(response, url))
            .then((response) => response.text());
    }

    function withCacheBusting(url, token) {
        if (!url) {
            return url;
        }
        if (typeof window.applyCacheToken === 'function') {
            return window.applyCacheToken(url, token);
        }
        if (typeof window.createCacheBustedUrl === 'function') {
            return window.createCacheBustedUrl(url, token);
        }
        return url;
    }

    function buildRequestUrl(url, token, shouldBust) {
        if (!shouldBust) {
            return url;
        }
        return withCacheBusting(url, token);
    }

    window.dataClient = Object.freeze({
        fetchJson,
        fetchText,
        withCacheBusting,
        buildRequestUrl,
        applyRequestInit,
        DEFAULT_REQUEST_INIT,
    });
})();
