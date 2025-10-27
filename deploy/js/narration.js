const narrationFile = window.location.pathname.includes('index_en') ? 'narration_en.md' : 'narration.md';
let narrationPending = null;
let lastNarrationToken = 0;

function buildNarrationUrl(token) {
    const baseUrlPath = `${baseUrl}/${narrationFile}`;
    if (typeof window.applyCacheToken === 'function') {
        return window.applyCacheToken(baseUrlPath, token);
    }
    if (Number.isFinite(token) && typeof window.createCacheBustedUrl === 'function') {
        return window.createCacheBustedUrl(baseUrlPath, token);
    }
    return baseUrlPath;
}

/**
 * Fetches narration markdown, avoiding duplicate outstanding requests.
 * Applies cache-busting when a token is supplied and updates the rendered content.
 * @param {number} [token] Optional cache-busting token (typically a timestamp).
 * @returns {Promise<void>} Resolves after narration is updated or logs an error.
 */
function loadNarration(token) {
    if (narrationPending) {
        return narrationPending;
    }
    const effectiveToken = Number.isFinite(token) ? token : Date.now();
    const requestUrl = buildNarrationUrl(effectiveToken);
    narrationPending = fetch(requestUrl, { cache: 'no-cache' })
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.text();
        })
        .then(text => {
            const narrationElement = document.getElementById('narration');
            if (narrationElement) {
                narrationElement.innerHTML = marked.parse(text);
            }
            lastNarrationToken = effectiveToken;
        })
        .catch(error => console.error('Fetching Markdown failed:', error))
        .finally(() => {
            narrationPending = null;
        });
    return narrationPending;
}

loadNarration();

window.addEventListener('prediction-data-ready', event => {
    if (narrationPending) {
        return;
    }
    const generatedAt = Number(event?.detail?.generatedAt);
    if (!Number.isFinite(generatedAt) || generatedAt <= lastNarrationToken) {
        return;
    }
    loadNarration(generatedAt);
});
