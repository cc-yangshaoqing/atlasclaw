/*
 *  Copyright 2021  Qianyun, Inc. All rights reserved.
 */

/**
 * Session State Management
 * Manage session lifecycle and persistence
 */

import { createThreadSession } from './api-client.js';

const SESSION_KEY_STORAGE = 'atlasclaw_session_key';
const SESSION_HAS_MESSAGES_STORAGE = 'atlasclaw_session_has_messages';

let currentSessionKey = null;
let currentSessionHasMessages = null;

function readStoredSessionHasMessages() {
    const value = sessionStorage.getItem(SESSION_HAS_MESSAGES_STORAGE);
    if (value === '1') return true;
    if (value === '0') return false;
    return null;
}

function persistSessionHasMessages(value) {
    if (value === true) {
        sessionStorage.setItem(SESSION_HAS_MESSAGES_STORAGE, '1');
        return;
    }
    if (value === false) {
        sessionStorage.setItem(SESSION_HAS_MESSAGES_STORAGE, '0');
        return;
    }
    sessionStorage.removeItem(SESSION_HAS_MESSAGES_STORAGE);
}

/**
 * Initialize session
 * Restore from sessionStorage or create new session
 * @param {object} params - Session parameters
 * @returns {Promise<string>} Session key
 */
export async function initSession(params = {}) {
    // Try to restore from sessionStorage
    const storedKey = sessionStorage.getItem(SESSION_KEY_STORAGE);
    
    if (storedKey) {
        currentSessionKey = storedKey;
        currentSessionHasMessages = readStoredSessionHasMessages();
        console.log('[Session] Restored:', currentSessionKey);
        return currentSessionKey;
    }
    
    // Create new session
    const session = await createThreadSession(params);
    currentSessionKey = session.session_key;
    sessionStorage.setItem(SESSION_KEY_STORAGE, currentSessionKey);
    setSessionHasMessages(false);
    console.log('[Session] Created:', currentSessionKey);
    
    return currentSessionKey;
}

/**
 * Get current session key
 * @returns {string|null} Session key
 */
export function getSessionKey() {
    if (!currentSessionKey) {
        currentSessionKey = sessionStorage.getItem(SESSION_KEY_STORAGE);
    }
    return currentSessionKey;
}

/**
 * Set session key (for session restoration)
 * @param {string} key - Session key
 */
export function setSessionKey(key) {
    const previousKey = currentSessionKey;
    currentSessionKey = key;
    if (key) {
        sessionStorage.setItem(SESSION_KEY_STORAGE, key);
        if (key !== previousKey) {
            setSessionHasMessages(null);
        }
    } else {
        sessionStorage.removeItem(SESSION_KEY_STORAGE);
        setSessionHasMessages(null);
    }
}

export function setSessionHasMessages(hasMessages) {
    currentSessionHasMessages = typeof hasMessages === 'boolean' ? hasMessages : null;
    persistSessionHasMessages(currentSessionHasMessages);
}

export function getSessionHasMessages() {
    if (currentSessionHasMessages === null) {
        currentSessionHasMessages = readStoredSessionHasMessages();
    }
    return currentSessionHasMessages;
}

/**
 * Check if there is an active session
 * @returns {boolean}
 */
export function hasSession() {
    return !!getSessionKey();
}

/**
 * Clear current session and create a new independent thread
 * @param {boolean} archive - Unused compatibility argument
 * @param {object} params - New session parameters
 * @returns {Promise<string>} New session key
 */
export async function startNewSession(archive = true, params = {}) {
    // Clear storage and create a brand-new thread while preserving history entries
    void archive;
    const activeSessionKey = currentSessionKey || sessionStorage.getItem(SESSION_KEY_STORAGE);
    if (activeSessionKey && getSessionHasMessages() === false) {
        currentSessionKey = activeSessionKey;
        return activeSessionKey;
    }
    sessionStorage.removeItem(SESSION_KEY_STORAGE);
    sessionStorage.removeItem(SESSION_HAS_MESSAGES_STORAGE);
    currentSessionKey = null;
    currentSessionHasMessages = null;

    return initSession(params);
}

/**
 * Clear session (local only)
 */
export function clearSession() {
    sessionStorage.removeItem(SESSION_KEY_STORAGE);
    sessionStorage.removeItem(SESSION_HAS_MESSAGES_STORAGE);
    currentSessionKey = null;
    currentSessionHasMessages = null;
    console.log('[Session] Cleared');
}

export default {
    initSession,
    getSessionKey,
    setSessionKey,
    setSessionHasMessages,
    getSessionHasMessages,
    hasSession,
    startNewSession,
    clearSession
};
