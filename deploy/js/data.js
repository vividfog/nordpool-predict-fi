// ==========================================================================
// Shared data fetching utilities
// ==========================================================================

(function () {
    const fetchUtils = window.fetchUtils || {};
    const FALLBACK_DEFAULT_INIT = Object.freeze({ cache: 'no-cache' });

    function getDefaultInit() {
        return fetchUtils.DEFAULT_REQUEST_INIT || FALLBACK_DEFAULT_INIT;
    }

    function applyRequestInit(overrides) {
        if (typeof fetchUtils.applyRequestInit === 'function') {
            return fetchUtils.applyRequestInit(overrides);
        }
        if (!overrides) {
            return Object.assign({}, getDefaultInit());
        }
        return Object.assign({}, getDefaultInit(), overrides);
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
        if (typeof fetchUtils.applyCacheToken === 'function') {
            return fetchUtils.applyCacheToken(url, token);
        }
        if (typeof fetchUtils.createCacheBustedUrl === 'function') {
            return fetchUtils.createCacheBustedUrl(url, token);
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
        DEFAULT_REQUEST_INIT: getDefaultInit(),
    });
})();
