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
              auth_type: 'user_token',
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
                  auth_type: 'user_token',
                  user_token: 'secret-token'
                },
                updated_at: '2026-04-13T10:00:00Z'
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
  test('mount renders provider configuration with token values', async () => {
    const providersPage = await import('../../app/frontend/scripts/pages/providers.js')
    const container = document.getElementById('page-root')

    await providersPage.mount(container)

    const cardTypes = [...container.querySelectorAll('.pv-type-card')].map((card) => card.dataset.type)
    expect(cardTypes).toEqual(['smartcmp'])
    expect(
      [...container.querySelectorAll('.pv-type-card')].every((card) => card.classList.contains('pv-type-card-compact'))
    ).toBe(true)

    expect(container.textContent).toContain('default')
    expect(container.textContent).toContain('backup')
    expect(container.textContent).toContain('Authentication Configuration')
    expect(container.textContent).toContain('Choose a built-in instance for authentication configuration')
    expect(container.textContent).toContain('https://console.smartcmp.cloud')
    expect(container.textContent).toContain('SmartCMP Authentication Configuration')
    expect(container.textContent).toContain('secret-token')
    expect(container.querySelector('.pv-card-stats')).toBeNull()
    expect(container.querySelector('.pv-card-summary')).toBeNull()
    expect(container.querySelector('.pv-card-instance-list')).toBeNull()
    expect(container.querySelector('.pv-card-instance-chip')).toBeNull()
    expect(container.textContent).not.toContain('DingTalk')
    expect(container.textContent).toContain('Instance')
    expect(container.textContent).toContain('Token')
    expect(container.textContent).not.toContain('Templates')
    expect(container.textContent).not.toContain('Template')
    expect(container.textContent).not.toContain('Managed')
    expect(container.textContent).not.toContain('New Provider Instance')
    expect(container.querySelector('.pv-status')).toBeNull()
    expect(container.querySelector('#btnCreateProviderInstance')).toBeNull()
    expect(container.querySelector('.pv-panel-header .pv-eyebrow')).toBeNull()
    expect(container.querySelector('.pv-counter')).toBeNull()
    expect(container.querySelector('.pv-instance-readonly-badge')).toBeNull()
    expect(container.querySelectorAll('[data-configure-template]')).toHaveLength(2)
    expect(
      [...container.querySelectorAll('[data-configure-template]')].map((button) => button.textContent.trim())
    ).toEqual(['Configure', 'Configure'])

    await providersPage.unmount()
  })

  test('configure modal keeps base url inline with instance selection', async () => {
    const providersPage = await import('../../app/frontend/scripts/pages/providers.js')
    const container = document.getElementById('page-root')

    await providersPage.mount(container)

    container.querySelector('[data-configure-template]').click()
    expect(container.querySelector('#providerModal')).not.toBeNull()
    expect(container.querySelector('#providerModal').textContent).not.toContain('My Credentials')
    expect(container.querySelector('#providerModal .pv-modal-kicker').textContent).toBe('Authentication Configuration')
    expect(container.querySelector('#providerModal h2').textContent).toBe('Configure SmartCMP')
    expect(container.querySelector('#providerModal .pv-modal-description').textContent).toContain('personal credentials')
    expect(container.querySelector('#providerModal').textContent).toContain('Access Configuration')
    expect(container.querySelector('#providerModal button[type="submit"]').textContent).toBe('Save')
    expect(container.querySelector('#providerModal .pv-modal-meta-row')).toBeNull()

    const instanceSelect = container.querySelector('select[name="instance_name"]')
    const modalOverview = container.querySelector('.pv-modal-grid')
    const modalLabels = [...container.querySelectorAll('#providerModal .pv-form-field > span')].map((item) => item.textContent.trim())

    expect(instanceSelect).not.toBeNull()
    expect([...instanceSelect.options].map((option) => option.value)).toEqual(['default', 'backup'])
    expect(instanceSelect.value).toBe('default')
    expect(modalLabels).toContain('Instance')
    expect(container.querySelector('input[name="base_url"]')).toBeNull()
    expect(container.querySelector('.pv-modal-linked-field')).toBeNull()
    expect(container.querySelector('.pv-instance-meta')).toBeNull()
    expect(modalOverview).not.toBeNull()
    expect(modalOverview.textContent).toContain('Base URL')
    expect(modalOverview.textContent).toContain('https://console.smartcmp.cloud')
    expect(container.querySelector('.pv-text-value')).not.toBeNull()
    expect(container.querySelector('input[name="user_token"]')).not.toBeNull()
    expect(container.querySelector('input[name="user_token"]').type).toBe('text')
    expect(container.querySelector('[data-toggle-secret="user_token"]')).toBeNull()

    instanceSelect.value = 'backup'
    instanceSelect.dispatchEvent(new Event('change', { bubbles: true }))
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(container.querySelector('.pv-modal-grid').textContent).toContain('https://backup.smartcmp.cloud')

    const tokenInput = container.querySelector('input[name="user_token"]')
    tokenInput.value = 'next-secret-token'

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
        auth_type: 'user_token',
        user_token: 'next-secret-token'
      }
    })

    await providersPage.unmount()
  })
})
