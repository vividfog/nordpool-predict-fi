(function () {
    const DEFAULT_REQUEST_INIT = Object.freeze({ cache: 'no-cache' });

    function cloneDefaultInit() {
        return Object.assign({}, DEFAULT_REQUEST_INIT);
    }

    function applyRequestInit(overrides) {
        if (!overrides) {
            return cloneDefaultInit();
        }
        return Object.assign({}, DEFAULT_REQUEST_INIT, overrides);
    }

    function createCacheBustedUrl(url, token) {
        if (!url) {
            return url;
        }
        const suffix = typeof token === 'undefined' ? Date.now() : token;
        const separator = url.includes('?') ? '&' : '?';
        return `${url}${separator}cb=${suffix}`;
    }

    function applyCacheToken(url, token) {
        if (!Number.isFinite(token)) {
            return url;
        }
        return createCacheBustedUrl(url, token);
    }

    window.fetchUtils = Object.freeze({
        DEFAULT_REQUEST_INIT,
        applyRequestInit,
        createCacheBustedUrl,
        applyCacheToken,
    });

    window.createCacheBustedUrl = createCacheBustedUrl;
    window.applyCacheToken = applyCacheToken;
})();
