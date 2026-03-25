/**
 * DeepChat UI Configuration and Interaction
 * Configure DeepChat component integration with AtlasClaw API
 */

import { getSessionKey, initSession } from './session-manager.js';
import { createStreamHandler } from './stream-handler.js';
import { buildApiUrl } from './config.js';
import { t, isLocaleLoaded } from './i18n.js';
import { getAuthToken } from './auth.js';


let chatElement = null;
let currentStreamHandler = null;

/**
 * Initialize DeepChat component
 * @param {HTMLElement} element - DeepChat DOM element
 */
export async function initChat(element) {
    chatElement = element;

    await initSession();
    
    // Load agent info and set welcome message
    await loadAgentInfo(element);
    
    configureChatConnection(element);
    configureInterceptors(element);
    configureI18nAttributes(element);

    console.log('[ChatUI] Initialized');
}

/**
 * Load agent information and set welcome message
 * @param {HTMLElement} element - DeepChat DOM element
 */
async function loadAgentInfo(element) {
    try {
        const response = await fetch('/api/agent/info');
        if (response.ok) {
            const agentInfo = await response.json();
            console.log('[ChatUI] Agent info loaded:', agentInfo);
            
            // Set welcome message
            if (agentInfo.welcome_message) {
                element.introMessage = {
                    text: agentInfo.welcome_message,
                    role: 'ai'
                };
            }
        }
    } catch (error) {
        console.error('[ChatUI] Failed to load agent info:', error);
    }
}

function configureChatConnection(element) {
    const token = getAuthToken();
    const headers = {
        'Content-Type': 'application/json'
    };
    if (token) {
        headers['AtlasClaw-Authenticate'] = token;
    }

    element.connect = {
        url: buildApiUrl('/api/agent/run'),
        method: 'POST',
        headers
    };


    if (typeof element.render === 'function') {
        element.render();
    }
}

function configureInterceptors(element) {
    element.requestInterceptor = async (request) => {
        console.log('[ChatUI] Request intercepted:', request);

        const body = parseRequestBody(request.body);
        const messageText = extractMessageText(body);

        let sessionKey = getSessionKey();
        if (!sessionKey) {
            sessionKey = await initSession();
        }

        request.body = {
            session_key: sessionKey || '',
            message: messageText || '',
            timeout_seconds: 600
        };

        return request;
    };

    element.responseInterceptor = (response) => {
        const payload = parseResponseBody(response);
        const runId = payload?.run_id || payload?.runId || payload?.id;

        if (!runId || typeof runId !== 'string') {
            console.warn('[ChatUI] Missing run_id in /api/agent/run response:', response);
            if (payload?.detail) {
                console.warn('[ChatUI] /api/agent/run validation detail:', payload.detail);
            }
            return response;
        }

        handleStreamingResponse(runId).catch((err) => {
            console.error('[ChatUI] Streaming failed:', err);
        });

        return { text: '' };
    };
}

function parseRequestBody(raw) {
    if (!raw) return {};
    if (typeof raw === 'object') return raw;
    if (typeof raw !== 'string') return { text: String(raw) };
    try {
        return JSON.parse(raw);
    } catch {
        return { text: raw };
    }
}

function parseResponseBody(raw) {
    if (!raw) return {};
    if (typeof raw === 'object') return raw;
    if (typeof raw !== 'string') return {};
    try {
        return JSON.parse(raw);
    } catch {
        return {};
    }
}

function configureI18nAttributes(element) {
    if (!isLocaleLoaded()) {
        console.warn('[ChatUI] Locale not loaded, skipping i18n config');
        return;
    }

    const introMessage = t('chat.introMessage');
    element.introMessage = { text: introMessage };

    const placeholder = t('chat.placeholder');
    element.textInput = {
        placeholder: {
            text: placeholder,
            style: { color: '#999' }
        },
        styles: {
            container: {
                borderRadius: '24px',
                border: '1px solid #ddd',
                padding: '12px 20px',
                backgroundColor: '#ffffff',
                boxShadow: '0 2px 6px rgba(0,0,0,0.05)'
            },
            text: { fontSize: '15px' }
        }
    };
}

function extractMessageText(body) {
    if (!body) return '';

    if (typeof body === 'string') return body;

    if (body.messages && Array.isArray(body.messages) && body.messages.length > 0) {
        const lastMessage = body.messages[body.messages.length - 1] || {};
        if (typeof lastMessage === 'string') return lastMessage;
        if (lastMessage.text) return String(lastMessage.text);
        if (lastMessage.content) return String(lastMessage.content);
    }

    if (body.message) return String(body.message);
    if (body.text) return String(body.text);
    if (body.input) return String(body.input);

    return '';
}

async function handleStreamingResponse(runId) {
    console.log('[ChatUI] Handling streaming response for run:', runId);

    let aiMessageContent = '';
    const canUpdateMessage = !!(chatElement && typeof chatElement.updateMessage === 'function');
    let aiMessageIndex = null;
    let hasRenderedDelta = false;

    if (chatElement && canUpdateMessage) {
        chatElement.addMessage({ text: '', role: 'ai' });
        const messages = chatElement.getMessages ? chatElement.getMessages() : [];
        aiMessageIndex = messages.length - 1;
    }

    return new Promise((resolve, reject) => {
        currentStreamHandler = createStreamHandler(runId, {
            onStart: () => {
                console.log('[ChatUI] Stream started');
            },
            onDelta: (data) => {
                if (!data.content) return;

                aiMessageContent += data.content;
                updateAiMessage(aiMessageContent, aiMessageIndex);
                hasRenderedDelta = true;
            },
            onToolStart: (data) => {
                console.log('[ChatUI] Tool start:', data.tool_name);
                showToolIndicator(data.tool_name);
            },
            onToolEnd: (data) => {
                console.log('[ChatUI] Tool end:', data.tool_name);
                hideToolIndicator();
            },
            onEnd: () => {
                console.log('[ChatUI] Stream ended');
                finalizeAiMessage(aiMessageContent, aiMessageIndex, canUpdateMessage, hasRenderedDelta);
                currentStreamHandler = null;
                resolve({ text: aiMessageContent });
            },
            onError: (error) => {
                console.error('[ChatUI] Stream error:', error);
                appendErrorMessage(error?.message || 'Stream error');
                currentStreamHandler = null;
                reject(error);
            }
        });

        currentStreamHandler.start();
    });
}

function appendErrorMessage(message) {
    if (!chatElement) return;

    if (typeof chatElement.addErrorMessage === 'function') {
        chatElement.addErrorMessage(message);
        return;
    }

    chatElement.addMessage({ text: `Error: ${message}`, role: 'ai' });
}

function updateAiMessage(content, messageIndex) {
    if (!chatElement) return;

    if (messageIndex !== null) {
        try {
            chatElement.updateMessage({ text: content, role: 'ai' }, messageIndex);
            return;
        } catch {
            // fallback below
        }
    }

    // DeepChat versions without updateMessage can still stream via overwrite mode.
    try {
        chatElement.addMessage({ text: content, role: 'ai', overwrite: true });
    } catch {
        // fallback handled at finalize
    }
}

function finalizeAiMessage(content, messageIndex, canUpdateMessage, hasRenderedDelta) {
    if (!chatElement) return;

    if (canUpdateMessage && messageIndex !== null) {
        try {
            chatElement.updateMessage({ text: content, role: 'ai' }, messageIndex);
            return;
        } catch {
            // fallback below
        }
    }

    if (hasRenderedDelta) {
        return;
    }

    chatElement.addMessage({ text: content, role: 'ai' });
}

function showToolIndicator(toolName) {
    console.log('[ChatUI] Executing tool:', toolName);
}

function hideToolIndicator() {
    // Hide loading indicator
}

export function abortCurrentStream() {
    if (currentStreamHandler) {
        currentStreamHandler.abort();
        currentStreamHandler = null;
    }
}

export function getChatElement() {
    return chatElement;
}

export default {
    initChat,
    abortCurrentStream,
    getChatElement,
    configureI18nAttributes
};