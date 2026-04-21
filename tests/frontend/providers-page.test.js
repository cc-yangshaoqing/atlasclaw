/*
 *  Copyright 2021  Qianyun, Inc. All rights reserved.
 */
const { readFileSync } = require('node:fs')
const { resolve } = require('node:path')

let userProviderPayloads = []

beforeEach(() => {
  jest.resetModules()
  document.body.innerHTML = '<div id="page-root"></div>'
  window.history.replaceState({}, '', '/providers')
  userProviderPayloads = []

  global.fetch = jest.fn((url, options = {}) => {
    const target = String(url)
    const method = String(options.method || 'GET').toUpperCase()

    if (target.endsWith('/api/service-providers/available-instances')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          count: 2,
          providers: [
            {
              provider_type: 'smartcmp',
              instance_name: 'default',
              base_url: 'https://console.smartcmp.cloud',
              auth_type: 'user_token',
              config_keys: []
            },
            {
              provider_type: 'smartcmp',
              instance_name: 'backup',
              base_url: 'https://backup.smartcmp.cloud',
              auth_type: 'cookie',
              config_keys: []
            },
            {
              provider_type: 'dingtalk',
              instance_name: 'ops',
              base_url: 'https://oapi.dingtalk.com',
              auth_type: 'app_credentials',
              config_keys: []
            }
          ]
        })
      })
    }

    if (target.endsWith('/api/service-providers/definitions')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          count: 2,
          providers: [
            {
              provider_type: 'smartcmp',
              name_i18n_key: 'provider.catalog.smartcmp.name',
              display_name: 'SmartCMP',
              description_i18n_key: 'provider.catalog.smartcmp.description',
              description: 'Enterprise CMP workflow provider for approvals, service catalog queries, and fulfillment actions.',
              badge: 'CMP',
              icon: 'SC',
              accent: '#0f766e',
              schema: {
                fields: [
                  {
                    name: 'base_url',
                    label_i18n_key: 'provider.baseUrl',
                    label: 'Base URL',
                    placeholder_i18n_key: 'provider.baseUrlPlaceholder',
                    placeholder: 'https://console.smartcmp.cloud',
                    type: 'text',
                    required: true,
                    default: 'https://console.smartcmp.cloud'
                  },
                  {
                    name: 'auth_type',
                    type: 'hidden',
                    default: 'user_token'
                  },
                  {
                    name: 'user_token',
                    label_i18n_key: 'provider.userToken',
                    label: 'User Token',
                    placeholder_i18n_key: 'provider.userTokenPlaceholder',
                    placeholder: 'Enter user token',
                    type: 'password',
                    required: true,
                    sensitive: true,
                    auth_types: ['user_token']
                  },
                  {
                    name: 'cookie',
                    label_i18n_key: 'provider.cookie',
                    label: 'Cookie',
                    placeholder_i18n_key: 'provider.cookiePlaceholder',
                    placeholder: 'session=...',
                    type: 'password',
                    required: true,
                    sensitive: true,
                    auth_types: ['cookie']
                  }
                ]
              }
            },
            {
              provider_type: 'dingtalk',
              name_i18n_key: 'provider.catalog.dingtalk.name',
              display_name: 'DingTalk',
              description_i18n_key: 'provider.catalog.dingtalk.description',
              description: 'Enterprise messaging provider for org bots, app credentials, and downstream work notifications.',
              badge: 'COLLAB',
              icon: 'DT',
              accent: '#2952cc',
              schema: {
                fields: [
                  {
                    name: 'base_url',
                    label_i18n_key: 'provider.baseUrl',
                    label: 'Base URL',
                    placeholder_i18n_key: 'provider.baseUrlPlaceholder',
                    placeholder: 'https://oapi.dingtalk.com',
                    type: 'text',
                    required: true,
                    default: 'https://oapi.dingtalk.com'
                  },
                  {
                    name: 'auth_type',
                    type: 'hidden',
                    default: 'app_credentials'
                  },
                  {
                    name: 'app_key',
                    label_i18n_key: 'provider.appKey',
                    label: 'App Key',
                    placeholder_i18n_key: 'provider.appKeyPlaceholder',
                    placeholder: 'dingxxxx',
                    type: 'text',
                    required: true
                  },
                  {
                    name: 'app_secret',
                    label_i18n_key: 'provider.appSecret',
                    label: 'App Secret',
                    placeholder_i18n_key: 'provider.appSecretPlaceholder',
                    placeholder: 'Enter app secret',
                    type: 'password',
                    required: true,
                    sensitive: true
                  },
                  {
                    name: 'agent_id',
                    label_i18n_key: 'provider.agentId',
                    label: 'Agent ID',
                    placeholder_i18n_key: 'provider.agentIdPlaceholder',
                    placeholder: '1000001',
                    type: 'text',
                    required: true
                  }
                ]
              }
            }
          ]
        })
      })
    }

    if (target.endsWith('/api/users/me/provider-settings') && method === 'GET') {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          providers: {
            smartcmp: {
              default: {
                configured: true,
                config: {
                  auth_type: 'user_token'
                },
                updated_at: '2026-04-13T10:00:00Z'
              },
              backup: {
                configured: true,
                config: {
                  auth_type: 'cookie'
                },
                updated_at: '2026-04-13T10:05:00Z'
              }
            },
            dingtalk: {
              ops: {
                configured: true,
                config: {
                  auth_type: 'app_credentials',
                  app_key: 'ding-app-key',
                  agent_id: '1000001'
                },
                updated_at: '2026-04-13T10:10:00Z'
              }
            }
          }
        })
      })
    }

    if (target.endsWith('/api/users/me/provider-settings') && method === 'PUT') {
      const payload = JSON.parse(options.body)
      userProviderPayloads.push(payload)
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          providers: {
            [payload.provider_type]: {
              [payload.instance_name]: {
                configured: true,
                config: payload.config,
                updated_at: '2026-04-13T10:30:00Z'
              }
            }
          }
        })
      })
    }

    if (target.includes('/api/provider-configs')) {
      return Promise.reject(new Error('providers page should not use /api/provider-configs for personal credentials'))
    }

    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({})
    })
  })
})

describe('providers page', () => {
  test('list typography uses one body text style across table cells', () => {
    const styles = readFileSync(
      resolve(__dirname, '../../app/frontend/styles/providers.css'),
      'utf-8'
    )

    expect(styles).toMatch(/\.pv-instance-cell strong\s*\{[^}]*font-size:\s*14px;[^}]*font-weight:\s*400;[^}]*line-height:\s*1\.5;[^}]*\}/s)
    expect(styles).toMatch(/\.pv-cell-muted\s*\{[^}]*font-size:\s*14px;[^}]*line-height:\s*1\.5;[^}]*\}/s)
    expect(styles).toMatch(/\.pv-config-key\s*\{[^}]*font-size:\s*14px;[^}]*font-weight:\s*400;[^}]*letter-spacing:\s*normal;[^}]*text-transform:\s*none;[^}]*\}/s)
    expect(styles).toMatch(/\.pv-config-value\s*\{[^}]*font-size:\s*14px;[^}]*font-weight:\s*400;[^}]*line-height:\s*1\.5;[^}]*\}/s)
  })

  test('mount renders one configuration table per provider without exposing sensitive values', async () => {
    const providersPage = await import('../../app/frontend/scripts/pages/providers.js')
    const container = document.getElementById('page-root')

    await providersPage.mount(container)

    const sectionTitles = [...container.querySelectorAll('[data-provider-section] .pv-panel-title')]
      .map((title) => title.textContent.trim())

    expect(sectionTitles).toEqual(['SmartCMP', 'DingTalk'])
    expect(container.textContent).toContain('Authentication Configuration')
    expect(container.textContent).toContain('default')
    expect(container.textContent).toContain('backup')
    expect(container.textContent).toContain('https://console.smartcmp.cloud')
    expect(container.textContent).toContain('User Token')
    expect(container.textContent).toContain('Cookie')
    expect(container.textContent).toContain('App Key')
    expect(container.textContent).toContain('App Secret')
    expect(container.textContent).toContain('Agent ID')
    expect(container.textContent).toContain('Configured')
    expect(container.textContent).toContain('ding-app-key')
    expect(container.textContent).toContain('1000001')
    expect(container.textContent).not.toContain('secret-token')
    expect(container.textContent).not.toContain('session=backup-cookie')
    expect(container.textContent).not.toContain('ding-app-secret')
    expect(container.querySelectorAll('[data-provider-section] .pv-table')).toHaveLength(2)
    expect(container.querySelector('.pv-card-stats')).toBeNull()
    expect(container.querySelector('.pv-card-summary')).toBeNull()
    expect(container.querySelector('.pv-card-instance-list')).toBeNull()
    expect(container.querySelector('.pv-card-instance-chip')).toBeNull()
    expect(container.querySelector('.pv-type-band')).toBeNull()
    expect(container.querySelector('.pv-type-card')).toBeNull()
    expect(container.textContent).toContain('Instance')
    expect(container.textContent).toContain('Access Configuration')
    expect(container.textContent).not.toContain('Templates')
    expect(container.textContent).not.toContain('Template')
    expect(container.textContent).not.toContain('Managed')
    expect(container.textContent).not.toContain('New Provider Instance')
    expect(container.querySelector('.pv-status')).toBeNull()
    expect(container.querySelector('#btnCreateProviderInstance')).toBeNull()
    expect(container.querySelector('.pv-panel-header .pv-eyebrow')).toBeNull()
    expect(container.querySelector('.pv-counter')).toBeNull()
    expect(container.querySelector('.pv-instance-readonly-badge')).toBeNull()
    expect(container.querySelectorAll('[data-configure-template]')).toHaveLength(3)
    expect(
      [...container.querySelectorAll('[data-configure-template]')].map((button) => button.textContent.trim())
    ).toEqual(['Configure', 'Configure', 'Configure'])

    const defaultSmartCmpRow = container.querySelector(
      '[data-configure-template][data-provider-type="smartcmp"][data-instance-name="default"]'
    ).closest('tr')
    expect(defaultSmartCmpRow.querySelector('.pv-instance-cell').textContent.trim()).toBe('default')
    expect(defaultSmartCmpRow.querySelector('.pv-instance-cell > span')).toBeNull()

    await providersPage.unmount()
  })

  test('configure modal leaves saved sensitive values blank and removes the reveal toggle', async () => {
    const providersPage = await import('../../app/frontend/scripts/pages/providers.js')
    const container = document.getElementById('page-root')

    await providersPage.mount(container)

    container.querySelector('[data-configure-template][data-provider-type="smartcmp"][data-instance-name="backup"]').click()
    expect(container.querySelector('#providerModal')).not.toBeNull()
    expect(container.querySelector('#providerModal').textContent).not.toContain('My Credentials')
    expect(container.querySelector('#providerModal .pv-modal-kicker').textContent).toBe('Authentication Configuration')
    expect(container.querySelector('#providerModal h2').textContent).toBe('Configure SmartCMP')
    expect(container.querySelector('#providerModal .pv-modal-description').textContent).toContain('personal credentials')
    expect(container.querySelector('#providerModal').textContent).toContain('Access Configuration')
    expect(container.querySelector('#providerModal button[type="submit"]').textContent).toBe('Save')
    expect(container.querySelector('#providerModal .pv-modal-meta-row')).toBeNull()

    const modalOverview = container.querySelector('.pv-modal-grid')
    const modalLabels = [
      ...container.querySelectorAll('#providerModal .pv-static-label, #providerModal .pv-form-field > span')
    ].map((item) => item.textContent.trim())
    const staticValues = [...container.querySelectorAll('#providerModal .pv-static-value')].map((item) => item.textContent.trim())

    expect(container.querySelector('select[name="instance_name"]')).toBeNull()
    expect(modalLabels).toContain('Instance')
    expect(staticValues).toContain('backup')
    expect(container.querySelector('input[name="base_url"]')).toBeNull()
    expect(container.querySelector('.pv-modal-linked-field')).toBeNull()
    expect(container.querySelector('.pv-instance-meta')).toBeNull()
    expect(modalOverview).not.toBeNull()
    expect(modalOverview.textContent).toContain('Base URL')
    expect(modalOverview.textContent).toContain('https://backup.smartcmp.cloud')
    expect(staticValues).toContain('https://backup.smartcmp.cloud')
    expect(container.querySelector('.pv-readonly-pill')).toBeNull()
    expect(container.querySelector('.pv-text-value')).toBeNull()
    expect(container.querySelector('input[name="user_token"]')).toBeNull()
    expect(container.querySelector('input[name="cookie"]')).not.toBeNull()
    expect(container.querySelector('input[name="cookie"]').type).toBe('text')
    expect(container.querySelector('input[name="cookie"]').required).toBe(false)
    expect(container.querySelector('input[name="cookie"]').value).toBe('')
    expect(container.querySelector('[data-toggle-secret="cookie"]')).toBeNull()

    const cookieInput = container.querySelector('input[name="cookie"]')
    cookieInput.value = 'session=next-cookie'

    container.querySelector('#providerModalForm').dispatchEvent(new Event('submit', {
      bubbles: true,
      cancelable: true
    }))

    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(userProviderPayloads).toHaveLength(1)
    expect(userProviderPayloads[0]).toEqual({
      provider_type: 'smartcmp',
      instance_name: 'backup',
      config: {
        auth_type: 'cookie',
        cookie: 'session=next-cookie'
      }
    })

    await providersPage.unmount()
  })
})
