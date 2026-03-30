/**
 * header.js - Header Component
 *
 * Provides:
 * - renderHeader(container, { authInfo }) - Render centered title + user dropdown menu
 * - updateHeaderTitle(titleKey) - Update page title using i18n key
 */
import { t } from '../i18n.js'
import { logout } from '../auth.js'

// Store reference to header element for updates
let headerElement = null
let titleElement = null
let dropdownAbortController = null

// SVG Icons
const ICONS = {
  models: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>',
  channels: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.32 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
  users: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
  logout: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>'
}

/**
 * Cleanup dropdown event listeners
 */
function cleanupDropdownListeners() {
  if (dropdownAbortController) {
    dropdownAbortController.abort()
    dropdownAbortController = null
  }
}

/**
 * Render header into container
 * @param {HTMLElement} container - Container element
 */
export function renderHeader(container, { authInfo } = {}) {
  if (!container) {
    console.warn('[Header] No container provided')
    return
  }

  // Cleanup previous listeners
  cleanupDropdownListeners()

  headerElement = container

  // Get user info
  const displayName = authInfo?.display_name || authInfo?.username || 'User'
  const initial = displayName.trim().charAt(0).toUpperCase() || 'U'
  const isAdmin = authInfo?.is_admin === true
  const roleText = isAdmin ? t('user.roleAdmin') || '管理员' : t('user.roleUser') || '用户'

  // Render header HTML with dropdown menu
  container.innerHTML = `
    <div class="chat-header-spacer" aria-hidden="true"></div>
    <h1 id="page-title" class="chat-header-title" data-i18n="app.title">AtlasClaw</h1>
    <div class="header-actions">
      <div class="user-menu-container">
        <button class="user-avatar-btn" id="userAvatarBtn" title="${escapeHtml(displayName)}">
          <span class="user-avatar">${escapeHtml(initial)}</span>
        </button>
        <div class="user-dropdown hidden" id="userDropdown">
          <div class="dropdown-header">
            <span class="dropdown-username">${escapeHtml(displayName)}</span>
            <span class="dropdown-role">${escapeHtml(roleText)}</span>
          </div>
          <div class="dropdown-divider"></div>
          ${isAdmin ? `
          <a href="/admin/users" class="dropdown-item" data-admin-only data-nav-link>
            ${ICONS.users} ${t('nav.users') || '用户管理'}
          </a>
          <a href="/models" class="dropdown-item" data-admin-only data-nav-link>
            ${ICONS.models} ${t('nav.models') || '模型管理'}
          </a>
          <a href="/channels" class="dropdown-item" data-admin-only data-nav-link>
            ${ICONS.channels} ${t('nav.channels') || '频道管理'}
          </a>
          <div class="dropdown-divider" data-admin-only></div>
          ` : ''}
          <a class="dropdown-item dropdown-item-danger" id="btnLogout">
            ${ICONS.logout} ${t('auth.logout') || '退出登录'}
          </a>
        </div>
      </div>
    </div>
  `

  titleElement = container.querySelector('#page-title')

  // Setup dropdown interactions
  setupDropdownListeners()
}

/**
 * Setup dropdown menu event listeners
 */
function setupDropdownListeners() {
  const avatarBtn = document.getElementById('userAvatarBtn')
  const dropdown = document.getElementById('userDropdown')
  const logoutBtn = document.getElementById('btnLogout')

  if (!avatarBtn || !dropdown) return

  // Create AbortController for cleanup
  dropdownAbortController = new AbortController()
  const signal = dropdownAbortController.signal

  // Toggle dropdown on avatar click
  avatarBtn.addEventListener('click', (e) => {
    e.stopPropagation()
    dropdown.classList.toggle('hidden')
  }, { signal })

  // Close dropdown on outside click
  document.addEventListener('click', (e) => {
    const container = document.querySelector('.user-menu-container')
    if (container && !container.contains(e.target)) {
      dropdown.classList.add('hidden')
    }
  }, { signal })

  // Close dropdown on Escape key
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      dropdown.classList.add('hidden')
    }
  }, { signal })

  // Handle navigation link clicks
  dropdown.querySelectorAll('[data-nav-link]').forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault()
      const href = link.getAttribute('href')
      dropdown.classList.add('hidden')
      if (window.__spaRouter && typeof window.__spaRouter.navigate === 'function') {
        window.__spaRouter.navigate(href)
      } else {
        window.location.href = href
      }
    }, { signal })
  })

  // Handle logout
  if (logoutBtn) {
    logoutBtn.addEventListener('click', async (e) => {
      e.preventDefault()
      dropdown.classList.add('hidden')
      await logout()
    }, { signal })
  }
}

export function updateHeaderTitleText(titleText) {
  if (!titleElement) {
    titleElement = document.getElementById('page-title')
  }

  if (!titleElement) {
    return
  }

  titleElement.removeAttribute('data-i18n')
  titleElement.textContent = titleText || 'AtlasClaw'
  document.title = titleElement.textContent
}

/**
 * Update header title
 * @param {string} titleKey - i18n key for title
 */
export function updateHeaderTitle(titleKey) {
  if (!titleElement) {
    titleElement = document.getElementById('page-title')
  }

  if (titleElement) {
    // Update the data-i18n attribute
    titleElement.setAttribute('data-i18n', titleKey)

    // Try to get translated text
    const translated = t(titleKey)
    if (translated && translated !== titleKey) {
      titleElement.textContent = translated
    } else {
      // Fallback to key's last part
      titleElement.textContent = getDefaultTitle(titleKey)
    }

    // Also update document title
    document.title = titleElement.textContent + ' - AtlasClaw'
  }
}

/**
 * Get default title for i18n key (fallback before translations load)
 * @param {string} key - i18n key
 * @returns {string}
 */
function getDefaultTitle(key) {
  const defaults = {
    'app.title': 'AtlasClaw',
    'app.chatTitle': 'Chat',
    'channel.title': 'Channel Management',
    'model.pageTitle': 'Model Management',
    'admin.title': 'User Management',
    'app.channels': 'Channels',
    'app.models': 'Models'
  }
  return defaults[key] || key.split('.').pop()
}

/**
 * Get header element
 * @returns {HTMLElement|null}
 */
export function getHeaderElement() {
  return headerElement
}

/**
 * Cleanup header resources
 */
export function cleanupHeader() {
  cleanupDropdownListeners()
}

export default {
  renderHeader,
  updateHeaderTitle,
  updateHeaderTitleText,
  getHeaderElement,
  cleanupHeader
}

function escapeHtml(text) {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}
