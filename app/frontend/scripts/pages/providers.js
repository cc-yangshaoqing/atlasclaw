/*
 *  Copyright 2021  Qianyun, Inc. All rights reserved.
 */

/**
 * providers.js - Service Provider Configuration Page
 *
 * Keep the existing page entry, but bind users to existing provider instances
 * and let them manage only their own credentials.
 */

import { showToast } from '../components/toast.js'
import { translateIfExists } from '../i18n.js'

const PROVIDER_ORDER = ['smartcmp', 'dingtalk']

const ACTION_ICONS = {
  eye: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="16" height="16" aria-hidden="true">
    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
    <circle cx="12" cy="12" r="3"></circle>
  </svg>`,
  eyeOff: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="16" height="16" aria-hidden="true">
    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
    <line x1="1" y1="1" x2="23" y2="23"></line>
  </svg>`
}

let pageContainer = null
let clickHandler = null
let changeHandler = null
let submitHandler = null
let state = createInitialState()
let isSaving = false

function createInitialState() {
  return {
    serviceProviders: [],
    providerDefinitions: {},
    userProviderConfigs: {},
    selectedProviderType: '',
    loading: false,
    error: '',
    modal: null
  }
}

function tr(key, fallback, params = {}) {
  return translateIfExists(key, params) || fallback
}

export async function mount(container) {
  pageContainer = container
  bindEvents()
  await refreshData()
}

export async function unmount() {
  if (pageContainer && clickHandler) {
    pageContainer.removeEventListener('click', clickHandler)
    pageContainer.removeEventListener('change', changeHandler)
    pageContainer.removeEventListener('submit', submitHandler)
  }

  pageContainer = null
  clickHandler = null
  changeHandler = null
  submitHandler = null
  state = createInitialState()
  isSaving = false
}

function bindEvents() {
  clickHandler = async (event) => {
    const providerCard = event.target.closest('[data-provider-card]')
    if (providerCard) {
      state.selectedProviderType = providerCard.dataset.type || ''
      render()
      return
    }

    const configureButton = event.target.closest('[data-configure-template]')
    if (configureButton) {
      openConfigureModal(
        configureButton.dataset.providerType || '',
        configureButton.dataset.instanceName || ''
      )
      return
    }

    if (event.target.closest('[data-close-modal]')) {
      closeModal()
      return
    }

    const secretToggle = event.target.closest('[data-toggle-secret]')
    if (secretToggle) {
      toggleSecretField(secretToggle.dataset.toggleSecret || '', secretToggle)
      return
    }

    const overlay = event.target.closest('#providerModal')
    if (overlay && event.target === overlay) {
      closeModal()
    }
  }

  changeHandler = (event) => {
    if (!state.modal || !event.target.matches('#providerModalForm select[name="instance_name"]')) {
      return
    }

    state.modal.instanceName = event.target.value
    state.modal.values = getInitialCredentialValues(state.modal.providerType, state.modal.instanceName)
    state.modal.error = ''
    render()
  }

  submitHandler = async (event) => {
    if (!event.target.matches('#providerModalForm')) {
      return
    }

    event.preventDefault()
    await saveModal()
  }

  pageContainer.addEventListener('click', clickHandler)
  pageContainer.addEventListener('change', changeHandler)
  pageContainer.addEventListener('submit', submitHandler)
}

async function refreshData() {
  state.loading = true
  state.error = ''
  render()

  try {
    const [serviceData, definitionData, userProviderData] = await Promise.all([
      requestJson('/api/service-providers/available-instances'),
      requestJson('/api/service-providers/definitions'),
      requestJson('/api/users/me/provider-settings')
    ])

    state.serviceProviders = Array.isArray(serviceData?.providers) ? serviceData.providers : []
    state.providerDefinitions = indexProviderDefinitions(definitionData?.providers)
    state.userProviderConfigs = typeof userProviderData?.providers === 'object' && userProviderData.providers
      ? userProviderData.providers
      : {}

    const availableTypes = getProviderTypes()
    if (!availableTypes.includes(state.selectedProviderType)) {
      state.selectedProviderType = availableTypes[0] || ''
    }
  } catch (error) {
    state.error = error?.message || tr('provider.loadError', 'Failed to load providers')
  } finally {
    state.loading = false
    render()
  }
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {})
    },
    ...options
  })

  if (!response.ok) {
    let message = `Request failed: ${response.status}`
    try {
      const payload = await response.json()
      if (typeof payload?.detail === 'string' && payload.detail.trim()) {
        message = payload.detail
      } else if (typeof payload?.message === 'string' && payload.message.trim()) {
        message = payload.message
      } else if (typeof payload?.error === 'string' && payload.error.trim()) {
        message = payload.error
      }
    } catch (_error) {
      // Keep status fallback for non-JSON responses.
    }
    throw new Error(message)
  }

  if (response.status === 204) {
    return {}
  }

  return response.json()
}

function render() {
  if (!pageContainer) {
    return
  }

  pageContainer.innerHTML = `
    <div class="pv-page">
      <div class="pv-page-header">
        <h1 data-i18n="provider.pageTitle">${tr('provider.pageTitle', 'Authentication Configuration')}</h1>
        <p data-i18n="provider.subtitle">${tr('provider.subtitle', 'Choose a built-in instance for authentication configuration here.')}</p>
      </div>
      ${renderProviderBand()}
      ${renderSelectedProvider()}
      ${renderModal()}
    </div>
  `
}

function renderProviderBand() {
  const providerTypes = getProviderTypes()

  if (!providerTypes.length) {
    return `
      <div class="pv-empty">
        <strong data-i18n="provider.emptyTitle">${tr('provider.emptyTitle', 'No service providers found')}</strong>
        ${tr('provider.emptyDescription', 'Define provider instances in')} <code>atlasclaw.json</code>.
      </div>
    `
  }

  return `
    <div class="pv-type-band-shell">
      <div class="pv-type-band">
        ${providerTypes.map(renderProviderCard).join('')}
      </div>
    </div>
  `
}

function renderProviderCard(providerType) {
  const meta = getProviderMeta(providerType)
  const selectedClass = providerType === state.selectedProviderType ? 'selected' : ''

  return `
    <button
      type="button"
      class="pv-type-card pv-type-card-compact ${selectedClass}"
      data-provider-card
      data-type="${escapeHtml(providerType)}"
      style="--pv-accent: ${escapeHtml(meta.accent)}"
    >
      <div class="pv-card-header">
        <span class="pv-card-icon">${escapeHtml(meta.icon)}</span>
        <div class="pv-card-title-group">
          <strong>${escapeHtml(meta.name)}</strong>
          <span class="pv-card-badge">${escapeHtml(meta.badge)}</span>
        </div>
      </div>
      <p class="pv-card-copy">${escapeHtml(meta.description)}</p>
    </button>
  `
}

function renderSelectedProvider() {
  const providerType = state.selectedProviderType
  if (!providerType) {
    return ''
  }

  const meta = getProviderMeta(providerType)
  const rows = getTemplateRows(providerType)

  return `
    <section class="pv-panel">
      <div class="pv-panel-header compact">
        <div>
          <h2 class="pv-panel-title">${tr('provider.inventoryTitle', `${meta.name} Authentication Configuration`, { provider: meta.name })}</h2>
          <p data-i18n="provider.inventoryDescription">${tr('provider.inventoryDescription', 'Choose a built-in instance for authentication configuration here.')}</p>
        </div>
      </div>
      ${renderTemplatesTable(rows)}
      ${state.error ? `<div class="pv-inline-note"><span class="pv-inline-note-label" data-i18n="provider.errorLabel">${tr('provider.errorLabel', 'Error')}</span>${escapeHtml(state.error)}</div>` : ''}
    </section>
  `
}

function renderTemplatesTable(rows) {
  if (state.loading) {
    return `
      <div class="pv-empty compact">
        <strong data-i18n="provider.loadingTitle">${tr('provider.loadingTitle', 'Loading provider inventory')}</strong>
        <span data-i18n="provider.loadingDescription">${tr('provider.loadingDescription', 'Syncing provider instances and personal credential status.')}</span>
      </div>
    `
  }

  if (!rows.length) {
    return `
      <div class="pv-empty compact">
        <strong data-i18n="provider.noInstancesTitle">${tr('provider.noInstancesTitle', 'No instances for this provider')}</strong>
        ${tr('provider.noInstancesDescription', 'Add a provider instance in')} <code>atlasclaw.json</code>.
      </div>
    `
  }

  return `
    <div class="pv-table-wrap">
      <table class="pv-table">
        <thead>
          <tr>
            <th>${tr('provider.tableInstance', 'Instance')}</th>
            <th>${tr('provider.tableBaseUrl', 'Base URL')}</th>
            <th>${tr('provider.tableToken', 'Token')}</th>
            <th>${tr('provider.tableUpdated', 'Updated')}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(renderTemplateRow).join('')}
        </tbody>
      </table>
    </div>
  `
}

function renderTemplateRow(row) {
  const actionLabel = tr('provider.configureCredentialsShort', 'Configure')

  return `
    <tr>
      <td>
        <div class="pv-instance-cell">
          <div class="pv-instance-heading">
            <strong>${escapeHtml(row.instanceName)}</strong>
          </div>
          <span>${escapeHtml(getProviderMeta(row.providerType).name)}</span>
        </div>
      </td>
      <td>${escapeHtml(row.baseUrl || tr('provider.notConfigured', 'Not configured'))}</td>
      <td><span class="pv-token-value">${escapeHtml(row.tokenValue)}</span></td>
      <td><span class="${row.updatedLabel === '--' ? 'pv-cell-muted' : ''}">${escapeHtml(row.updatedLabel)}</span></td>
      <td class="pv-table-action-cell">
        <div class="pv-actions">
          <button
            class="btn-small pv-row-action-btn"
            type="button"
            data-configure-template
            data-provider-type="${escapeHtml(row.providerType)}"
            data-instance-name="${escapeHtml(row.instanceName)}"
          >${escapeHtml(actionLabel)}</button>
        </div>
      </td>
    </tr>
  `
}

function renderModal() {
  if (!state.modal?.open) {
    return ''
  }

  const modal = state.modal
  const meta = getProviderMeta(modal.providerType)
  const template = getTemplateByInstance(modal.providerType, modal.instanceName)
  const credentialFields = getProviderCredentialFields(modal.providerType, modal.values)
  const hiddenFields = credentialFields.filter((field) => field.type === 'hidden')
  const visibleFields = credentialFields.filter((field) => field.type !== 'hidden')
  const modalTitle = tr('provider.modalConfigureTitleSpecific', `Configure ${meta.name}`, { provider: meta.name })
  const modalDescription = tr(
    'provider.modalConfigureDescription',
    'Configure your personal credentials for the selected system instance.'
  )

  return `
    <div class="pv-modal-overlay" id="providerModal">
      <div class="pv-modal">
        <div class="pv-modal-header">
          <div>
            <span class="pv-modal-kicker">${tr('provider.modalKicker', 'Authentication Configuration')}</span>
            <h2>${escapeHtml(modalTitle)}</h2>
            <p class="pv-modal-description">${escapeHtml(modalDescription)}</p>
          </div>
          <button class="pv-modal-close" type="button" data-close-modal aria-label="${tr('provider.close', 'Close')}">x</button>
        </div>
        <form id="providerModalForm">
          <div class="pv-modal-body">
            ${hiddenFields.map((field) => renderSchemaField(field, modal.values[field.name] || '')).join('')}
            <div class="pv-modal-primary-fields">
              <div class="pv-modal-grid">
                ${renderReadonlyField(tr('provider.providerType', 'Provider Type'), meta.name)}
                ${renderInstanceSelect(modal.providerType, modal.instanceName)}
                ${renderTextField(
                  tr('provider.baseUrl', 'Base URL'),
                  template?.baseUrl || tr('provider.notConfigured', 'Not configured')
                )}
              </div>
            </div>
            <div class="pv-form-section-title">${tr('provider.connectionParameters', 'Access Configuration')}</div>
            ${visibleFields.length
              ? `<div class="pv-modal-stack">${visibleFields.map((field) => renderSchemaField(field, modal.values[field.name] || '')).join('')}</div>`
              : `<div class="pv-inline-note"><span class="pv-inline-note-label">${tr('provider.noExtraSecret', 'No credential field')}</span>${tr('provider.noExtraSecretDescription', 'This provider instance does not expose additional personal credential fields.')}</div>`
            }
            ${modal.error ? `<div class="pv-inline-note is-error"><span class="pv-inline-note-label">${tr('provider.saveFailedLabel', 'Save failed')}</span>${escapeHtml(modal.error)}</div>` : ''}
          </div>
          <div class="pv-modal-footer">
            <button class="pv-btn-secondary" type="button" data-close-modal>${tr('provider.cancel', 'Cancel')}</button>
            <button class="pv-btn-primary" type="submit">${tr('provider.saveCredentials', 'Save')}</button>
          </div>
        </form>
      </div>
    </div>
  `
}

function renderReadonlyField(label, value, className = '') {
  const wrapperClass = ['pv-form-field', className].filter(Boolean).join(' ')
  return `
    <label class="${escapeHtml(wrapperClass)}">
      <span>${escapeHtml(label)}</span>
      <div class="pv-readonly-pill">${escapeHtml(value)}</div>
    </label>
  `
}

function renderTextField(label, value, className = '') {
  const wrapperClass = ['pv-form-field', className].filter(Boolean).join(' ')
  return `
    <div class="${escapeHtml(wrapperClass)}">
      <span>${escapeHtml(label)}</span>
      <div class="pv-text-value">${escapeHtml(value)}</div>
    </div>
  `
}

function renderInstanceSelect(providerType, selectedInstanceName) {
  const instances = getConfigFileTemplates(providerType)

  return `
    <label class="pv-form-field">
      <span>${tr('provider.instanceName', 'Instance')}</span>
      <select class="pv-form-input" name="instance_name">
        ${instances.map((instance) => `
          <option value="${escapeHtml(instance.instanceName)}" ${instance.instanceName === selectedInstanceName ? 'selected' : ''}>
            ${escapeHtml(instance.instanceName)}
          </option>
        `).join('')}
      </select>
    </label>
  `
}

function renderSchemaField(field, value) {
  const fieldName = String(field?.name || '')
  if (!fieldName) {
    return ''
  }

  if (field.type === 'hidden') {
    return `<input type="hidden" name="${escapeHtml(fieldName)}" value="${escapeHtml(value)}">`
  }

  const label = getSchemaFieldLabel(field)
  const placeholder = getSchemaFieldPlaceholder(field)
  const required = field.required ? 'required' : ''
  const normalizedFieldName = fieldName.trim().toLowerCase()
  const showPlainTextValue = normalizedFieldName.includes('token') && !normalizedFieldName.includes('secret')

  if (field.type === 'password' && !showPlainTextValue) {
    return `
      <label class="pv-form-field">
        <span>${escapeHtml(label)}</span>
        <div class="pv-secret-field">
          <input class="pv-form-input" type="password" name="${escapeHtml(fieldName)}" value="${escapeHtml(value)}" placeholder="${escapeHtml(placeholder)}" ${required}>
          <button class="pv-secret-toggle" type="button" data-toggle-secret="${escapeHtml(fieldName)}" aria-label="${tr('provider.toggleSecretVisibility', 'Show or hide secret')}">
            ${ACTION_ICONS.eye}
          </button>
        </div>
      </label>
    `
  }

  return `
    <label class="pv-form-field">
      <span>${escapeHtml(label)}</span>
      <input class="pv-form-input" type="${showPlainTextValue ? 'text' : escapeHtml(field.type || 'text')}" name="${escapeHtml(fieldName)}" value="${escapeHtml(value)}" placeholder="${escapeHtml(placeholder)}" ${required}>
    </label>
  `
}

function openConfigureModal(providerType, instanceName = '') {
  const targetType = providerType || getProviderTypes()[0] || ''
  const targetInstance = instanceName || getConfigFileTemplates(targetType)[0]?.instanceName || ''

  state.modal = {
    open: true,
    providerType: targetType,
    instanceName: targetInstance,
    values: getInitialCredentialValues(targetType, targetInstance),
    error: ''
  }

  render()
}

function closeModal() {
  state.modal = null
  render()
}

function syncModalStateFromDOM() {
  if (!state.modal || !pageContainer) {
    return
  }

  const form = pageContainer.querySelector('#providerModalForm')
  if (!form) {
    return
  }

  const formData = new FormData(form)
  state.modal.instanceName = String(formData.get('instance_name') || '')
  state.modal.values = Object.fromEntries(
    getProviderCredentialFields(state.modal.providerType, state.modal.values).map((field) => [
      field.name,
      String(formData.get(field.name) || '')
    ])
  )
}

async function saveModal() {
  if (isSaving || !state.modal) {
    return
  }

  isSaving = true
  try {
    syncModalStateFromDOM()

    const instanceName = state.modal.instanceName.trim()
    if (!instanceName) {
      state.modal.error = tr('provider.requiredFields', 'Please choose a provider instance.')
      render()
      return
    }

    const config = {}
    for (const field of getProviderCredentialFields(state.modal.providerType, state.modal.values)) {
      const normalizedValue = String(state.modal.values?.[field.name] ?? '').trim()
      if (normalizedValue || field.default != null) {
        config[field.name] = normalizedValue || String(field.default)
      }
    }

    const payload = {
      provider_type: state.modal.providerType,
      instance_name: instanceName,
      config
    }

    try {
      await requestJson('/api/users/me/provider-settings', {
        method: 'PUT',
        body: JSON.stringify(payload)
      })

      state.modal = null
      await refreshData()
      showToast(
        tr('provider.saveCredentialsSuccess', 'Authentication configuration saved successfully'),
        'success'
      )
    } catch (error) {
      state.modal.error = error?.message || tr('provider.saveError', 'Unable to save authentication configuration')
      showToast(state.modal.error, 'error')
      render()
    }
  } finally {
    isSaving = false
  }
}

function getProviderTypes() {
  const typeSet = new Set()

  for (const item of state.serviceProviders) {
    if (item?.provider_type) {
      typeSet.add(item.provider_type)
    }
  }

  return [...typeSet].sort((left, right) => {
    const leftRank = PROVIDER_ORDER.indexOf(left)
    const rightRank = PROVIDER_ORDER.indexOf(right)
    if (leftRank !== -1 || rightRank !== -1) {
      return (leftRank === -1 ? 999 : leftRank) - (rightRank === -1 ? 999 : rightRank)
    }
    return left.localeCompare(right)
  })
}

function getProviderMeta(providerType) {
  const fallbackName = String(providerType || 'provider')
    .replace(/[-_]+/g, ' ')
    .replace(/\b\w/g, (segment) => segment.toUpperCase())

  const definition = state.providerDefinitions[providerType]
  if (definition) {
    return {
      name: tr(definition.name_i18n_key || '', definition.display_name || fallbackName),
      badge: definition.badge || 'SERVICE',
      icon: definition.icon || fallbackName.slice(0, 2).toUpperCase(),
      accent: definition.accent || '#475569',
      description: tr(
        definition.description_i18n_key || '',
        definition.description || tr('provider.catalog.custom.description', 'Backend-defined service provider with instance-bound personal credentials.')
      )
    }
  }

  return {
    name: fallbackName,
    badge: 'SERVICE',
    icon: fallbackName.slice(0, 2).toUpperCase(),
    accent: '#475569',
    description: tr('provider.catalog.custom.description', 'Backend-defined service provider with instance-bound personal credentials.')
  }
}

function getProviderSummary(providerType) {
  const rows = getTemplateRows(providerType)

  return {
    totalTemplates: rows.length,
    configuredCount: rows.filter((row) => row.configured).length,
    pendingCount: rows.filter((row) => !row.configured).length
  }
}

function getConfigFileTemplates(providerType) {
  return state.serviceProviders
    .filter((entry) => entry.provider_type === providerType)
    .map((entry) => ({
      providerType,
      instanceName: String(entry.instance_name || ''),
      baseUrl: String(entry.base_url || ''),
      authType: String(entry.auth_type || ''),
      configKeys: Array.isArray(entry.config_keys) ? entry.config_keys : []
    }))
}

function getTemplateByInstance(providerType, instanceName) {
  return getConfigFileTemplates(providerType).find((entry) => entry.instanceName === instanceName) || null
}

function getUserProviderEntry(providerType, instanceName) {
  const providerBucket = state.userProviderConfigs?.[providerType]
  if (!providerBucket || typeof providerBucket !== 'object') {
    return null
  }
  const entry = providerBucket[instanceName]
  return entry && typeof entry === 'object' ? entry : null
}

function getTemplateRows(providerType) {
  return getConfigFileTemplates(providerType).map((template) => {
    const userEntry = getUserProviderEntry(providerType, template.instanceName)
    return {
      providerType,
      instanceName: template.instanceName,
      baseUrl: template.baseUrl,
      configured: Boolean(userEntry?.configured),
      tokenValue: getCredentialValue(providerType, userEntry?.config || {}),
      updatedLabel: formatTimestamp(userEntry?.updated_at),
      config: userEntry?.config || {}
    }
  })
}

function indexProviderDefinitions(definitions) {
  if (!Array.isArray(definitions)) {
    return {}
  }

  return Object.fromEntries(
    definitions
      .filter((item) => item?.provider_type)
      .map((item) => [item.provider_type, item])
  )
}

function getProviderCredentialFields(providerType, values = {}) {
  const fields = state.providerDefinitions[providerType]?.schema?.fields
  if (!Array.isArray(fields) || !fields.length) {
    return []
  }

  const authTypeField = fields.find((field) => field?.name === 'auth_type')
  const authType = String(values?.auth_type || authTypeField?.default || '').trim().toLowerCase()

  return fields.filter((field) => {
    if (field?.name === 'base_url') {
      return false
    }
    const authTypes = Array.isArray(field?.auth_types) ? field.auth_types : []
    return !authTypes.length || authTypes.includes(authType)
  })
}

function getInitialCredentialValues(providerType, instanceName) {
  const savedConfig = getUserProviderEntry(providerType, instanceName)?.config || {}
  return Object.fromEntries(
    getProviderCredentialFields(providerType, savedConfig).map((field) => {
      const currentValue = savedConfig?.[field.name]
      if (currentValue !== undefined && currentValue !== null && String(currentValue) !== '') {
        return [field.name, String(currentValue)]
      }
      if (field.default != null) {
        return [field.name, String(field.default)]
      }
      return [field.name, '']
    })
  )
}

function getCredentialValue(providerType, config) {
  const definitionFields = state.providerDefinitions[providerType]?.schema?.fields
  const sensitiveFieldNames = Array.isArray(definitionFields)
    ? definitionFields
      .filter((field) => field?.sensitive && field?.name)
      .map((field) => String(field.name))
    : []

  for (const fieldName of sensitiveFieldNames) {
    const rawValue = String(config?.[fieldName] || '').trim()
    if (rawValue) {
      return rawValue
    }
  }

  return '--'
}

function getSchemaFieldLabel(field) {
  return tr(field.label_i18n_key || '', field.label || field.name || '')
}

function getSchemaFieldPlaceholder(field) {
  return tr(field.placeholder_i18n_key || '', field.placeholder || '')
}

function toggleSecretField(fieldName, button) {
  if (!pageContainer || !fieldName) {
    return
  }

  const input = pageContainer.querySelector(`#providerModalForm input[name="${fieldName}"]`)
  if (!input) {
    return
  }

  const isPassword = input.type === 'password'
  input.type = isPassword ? 'text' : 'password'
  button.innerHTML = isPassword ? ACTION_ICONS.eyeOff : ACTION_ICONS.eye
}

function formatTimestamp(value) {
  if (!value) {
    return '--'
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return String(value)
  }

  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  return `${year}-${month}-${day} ${hours}:${minutes}`
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}
