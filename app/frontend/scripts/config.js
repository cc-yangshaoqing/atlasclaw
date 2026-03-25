/**
 * Configuration Management Module
 * Responsible for loading and providing runtime configuration
 */

const DEFAULT_CONFIG = {
    apiBaseUrl: ''
};

let config = { ...DEFAULT_CONFIG };
let configLoaded = false;

/**
 * Load runtime configuration
 * @returns {Promise<object>} Configuration object
 */
export async function loadConfig() {
    if (configLoaded) {
        return config;
    }
    
    try {
        const response = await fetch('/config.json');
        if (response.ok) {
            const loaded = await response.json();
            config = { ...DEFAULT_CONFIG, ...loaded };
            console.log('[Config] Loaded:', config);
        }
    } catch (e) {
        console.warn('[Config] Using default config:', e.message);
    }
    
    configLoaded = true;
    return config;
}

/**
 * Get current configuration
 * @returns {object} Configuration object
 */
export function getConfig() {
    return { ...config };
}

/**
 * Get API base URL
 * @returns {string} API base URL
 */
export function getApiBaseUrl() {
    return config.apiBaseUrl;
}

/**
 * Build full API URL
 * @param {string} path - API path
 * @returns {string} Full URL
 */
export function buildApiUrl(path) {
    const cleanPath = path.startsWith('/') ? path : `/${path}`;
    const baseRaw = String(config.apiBaseUrl || '').trim();
    if (!baseRaw) {
        return cleanPath;
    }

    try {
        const target = new URL(baseRaw, window.location.origin);
        if (target.origin !== window.location.origin) {
            console.warn('[Config] Cross-origin apiBaseUrl detected, fallback to same-origin:', target.origin);
            return cleanPath;
        }
    } catch (_error) {
        return cleanPath;
    }

    const base = baseRaw.replace(/\/$/, '');
    return `${base}${cleanPath}`;
}


export default {
    loadConfig,
    getConfig,
    getApiBaseUrl,
    buildApiUrl
};
