/*
 *  Copyright 2026  Qianyun, Inc., www.cloudchef.io, All rights reserved.
 */

let userProviderPayloads = []

beforeEach(() => {
  jest.resetModules()
  document.body.innerHTML = '<div id="page-root"></div>'
  userProviderPayloads = []

  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      getItem: jest.fn(() => null),
      setItem: jest.fn(),
      removeItem: jest.fn(),
      clear: jest.fn()
    }
  })

  window.requestAnimationFrame = jest.fn((callback) => callback())
  window.history.replaceState({}, '', '/channels')

  global.fetch = jest.fn((url, options = {}) => {
    const target = String(url)
    const method = String(options.method || 'GET').toUpperCase()

    if (target.endsWith('/api/channels')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([
          { type: 'websocket', name: 'WebSocket', mode: 'bidirectional', connection_count: 1 },
          { type: 'rest', name: 'REST', mode: 'request-response', connection_count: 0 },
          { type: 'sse', name: 'SSE', mode: 'stream', connection_count: 0 }
        ])
      })
    }

    if (target.endsWith('/api/channels/websocket/connections')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          channel_type: 'websocket',
          connections: []
        })
      })
    }

    if (target === '/api/service-providers/available-instances') {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          providers: [
            {
              provider_type: 'smartcmp',
              instance_name: 'default',
              auth_type: ['provider_token', 'user_token'],
              base_url: 'https://console.smartcmp.example'
            },
            {
              provider_type: 'smartcmp',
              instance_name: 'system',
              auth_type: ['provider_token'],
              base_url: 'https://system.smartcmp.example'
            }
          ]
        })
      })
    }

    if (target === '/api/service-providers/definitions') {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          providers: [
            {
              provider_type: 'smartcmp',
              display_name: 'SmartCMP',
              schema: {
                fields: [
                  {
                    name: 'user_token',
                    label: 'User Token',
                    placeholder: 'Enter user token',
                    type: 'password',
                    required: true,
                    sensitive: true,
                    auth_types: ['user_token']
                  },
                  {
                    name: 'provider_token',
                    label: 'Provider Token',
                    type: 'password',
                    sensitive: true,
                    auth_types: ['provider_token']
                  }
                ]
              }
            }
          ]
        })
      })
    }

    if (target === '/api/users/me/provider-settings' && method === 'GET') {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          providers: {
            smartcmp: {
              default: {
                configured: false,
                config: {},
                updated_at: null
              }
            }
          }
        })
      })
    }

    if (target === '/api/users/me/provider-settings' && method === 'PUT') {
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

    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({})
    })
  })
})

describe('channels page', () => {
  test('renders provider user-token readiness panel instead of connection health', async () => {
    const channelsPage = await import('../../app/frontend/scripts/pages/channels.js')
    const container = document.getElementById('page-root')

    await channelsPage.mount(container)

    expect(container.querySelector('#providerTokenReadinessPanel').style.display).toBe('block')
    expect(container.textContent).toContain('Provider User Tokens')
    expect(container.textContent).toContain('IM messages can ask the agent to work with configured providers')
    expect(container.textContent).toContain('SmartCMP')
    expect(container.textContent).toContain('default')
    expect([...container.querySelectorAll('#channelProviderTokenPanel tbody tr')].map(row => row.children[1].textContent.trim())).toEqual(['default'])
    expect(container.textContent).not.toContain('Connection Health')
    expect(container.textContent).not.toContain('Average Latency')
    expect(container.textContent).not.toContain('Uptime (24h)')

    await channelsPage.unmount()
  })

  test('channel provider token modal saves only the current user token', async () => {
    const channelsPage = await import('../../app/frontend/scripts/pages/channels.js')
    const container = document.getElementById('page-root')

    await channelsPage.mount(container)

    document.querySelector('[data-channel-provider-token-configure]').click()

    expect(document.getElementById('channelProviderTokenModal')).not.toBeNull()
    expect(document.querySelector('#channelProviderTokenForm input[name="user_token"]')).not.toBeNull()
    expect(document.querySelector('#channelProviderTokenForm input[name="provider_token"]')).toBeNull()

    document.querySelector('#channelProviderTokenForm input[name="user_token"]').value = 'channel-user-secret'
    document.getElementById('channelProviderTokenForm').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await new Promise(resolve => setTimeout(resolve, 0))
    await new Promise(resolve => setTimeout(resolve, 0))

    expect(userProviderPayloads).toEqual([
      {
        provider_type: 'smartcmp',
        instance_name: 'default',
        config: {
          user_token: 'channel-user-secret'
        }
      }
    ])

    await channelsPage.unmount()
  })

  test('mount keeps built-in channel types visible and shows planned placeholders', async () => {
    const channelsPage = await import('../../app/frontend/scripts/pages/channels.js')
    const container = document.getElementById('page-root')

    await channelsPage.mount(container)

    const cardTypes = [...container.querySelectorAll('.ch-type-card')].map((card) => card.dataset.type)

    expect(cardTypes).toEqual(['websocket', 'rest', 'sse', 'slack', 'discord'])

    container.querySelector('.ch-type-card[data-type="slack"]').click()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(container.querySelector('#btnCreateConnection').disabled).toBe(true)
    expect(container.querySelector('#providerTokenReadinessPanel').style.display).toBe('none')
    expect(
      global.fetch.mock.calls.some(([url]) => String(url).includes('/api/channels/slack/connections'))
    ).toBe(false)

    await channelsPage.unmount()
  })

  test('planned placeholders do not enter edit mode from a direct URL', async () => {
    window.history.replaceState({}, '', '/channels?type=slack&edit=new')

    const channelsPage = await import('../../app/frontend/scripts/pages/channels.js')
    const container = document.getElementById('page-root')

    await channelsPage.mount(container)

    expect(window.location.search).toBe('?type=slack')
    expect(container.querySelector('#channelListView').style.display).toBe('block')
    expect(container.querySelector('#channelEditView').style.display).toBe('none')
    expect(container.querySelector('#btnCreateConnection').disabled).toBe(true)

    await channelsPage.unmount()
  })

  test('enterprise channel edit form omits provider configuration controls', async () => {
    window.history.replaceState({}, '', '/channels?type=feishu&edit=new')

    global.fetch = jest.fn((url) => {
      const target = String(url)

      if (target.endsWith('/api/channels')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([
            { type: 'feishu', name: 'Feishu', mode: 'bidirectional', connection_count: 0 },
            { type: 'websocket', name: 'WebSocket', mode: 'bidirectional', connection_count: 1 }
          ])
        })
      }

      if (target.endsWith('/api/channels/feishu/schema')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            type: 'object',
            properties: {
              connection_mode: {
                type: 'string',
                title: 'Connection Mode',
                enum: ['longconnection', 'webhook'],
                enumLabels: {
                  longconnection: 'Long Connection',
                  webhook: 'Webhook'
                },
                default: 'longconnection'
              },
              app_id: {
                type: 'string',
                title: 'App ID',
                showWhen: { connection_mode: 'longconnection' }
              }
            },
            required_by_mode: {
              longconnection: ['app_id'],
              webhook: []
            }
          })
        })
      }

      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({})
      })
    })

    const channelsPage = await import('../../app/frontend/scripts/pages/channels.js')
    const container = document.getElementById('page-root')

    await channelsPage.mount(container)

    const labels = [...container.querySelectorAll('.ch-form-label')].map((item) => item.textContent.trim())

    expect(container.querySelector('#channelEditView').style.display).toBe('block')
    expect(labels).toContain('CONNECTION MODE')
    expect(labels.some((label) => label.startsWith('APP ID'))).toBe(true)
    expect(labels).not.toContain('AUTHENTICATION METHOD')
    expect(labels).not.toContain('AUTHENTICATION INSTANCE')
    expect(container.querySelector('select[name="provider_type"]')).toBeNull()
    expect(container.querySelector('select[name="provider_binding"]')).toBeNull()
    expect(container.querySelector('button[data-clear-target="provider_type"]')).toBeNull()
    expect(container.querySelector('button[data-clear-target="provider_binding"]')).toBeNull()
    expect(container.querySelector('.ch-aurora-banner')).toBeNull()

    await channelsPage.unmount()
  })
})
