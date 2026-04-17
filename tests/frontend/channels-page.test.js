/*
 *  Copyright 2021  Qianyun, Inc. All rights reserved.
 */

beforeEach(() => {
  jest.resetModules()
  document.body.innerHTML = '<div id="page-root"></div>'

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

  global.fetch = jest.fn((url) => {
    const target = String(url)

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

    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({})
    })
  })
})

describe('channels page', () => {
  test('mount keeps built-in channel types visible and shows planned placeholders', async () => {
    const channelsPage = await import('../../app/frontend/scripts/pages/channels.js')
    const container = document.getElementById('page-root')

    await channelsPage.mount(container)

    const cardTypes = [...container.querySelectorAll('.ch-type-card')].map((card) => card.dataset.type)

    expect(cardTypes).toEqual(['websocket', 'rest', 'sse', 'slack', 'discord'])

    container.querySelector('.ch-type-card[data-type="slack"]').click()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(container.querySelector('#btnCreateConnection').disabled).toBe(true)
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

  test('enterprise channel edit form renders provider configuration select near the top', async () => {
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
              provider_type: {
                type: 'string',
                title: 'Authentication Method',
                description: 'Choose which authentication configuration this channel should use.',
                enum: ['dingtalk', 'smartcmp'],
                enumLabels: {
                  dingtalk: 'DingTalk',
                  smartcmp: 'SmartCMP'
                }
              },
              provider_binding: {
                type: 'string',
                title: 'Authentication Instance',
                description: 'Choose one configured authentication instance under the selected authentication method.',
                enum: ['dingtalk/default', 'smartcmp/default'],
                enumLabels: {
                  'dingtalk/default': 'default',
                  'smartcmp/default': 'default'
                },
                optionsByProvider: {
                  dingtalk: [
                    { value: 'dingtalk/default', label: 'default' }
                  ],
                  smartcmp: [
                    { value: 'smartcmp/default', label: 'default' }
                  ]
                }
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
    const providerSelect = container.querySelector('select[name="provider_type"]')
    const instanceSelect = container.querySelector('select[name="provider_binding"]')
    const clearProviderButton = container.querySelector('button[data-clear-target="provider_type"]')
    const clearInstanceButton = container.querySelector('button[data-clear-target="provider_binding"]')
    const providerControl = providerSelect.closest('.ch-select-control-clearable')
    const instanceControl = instanceSelect.closest('.ch-select-control-clearable')

    expect(container.querySelector('#channelEditView').style.display).toBe('block')
    expect(labels.slice(1, 4)).toEqual(['CONNECTION MODE', 'AUTHENTICATION METHOD', 'AUTHENTICATION INSTANCE'])
    expect(providerSelect).not.toBeNull()
    expect(instanceSelect).not.toBeNull()
    expect(clearProviderButton).not.toBeNull()
    expect(clearInstanceButton).not.toBeNull()
    expect(clearProviderButton.closest('.ch-select-control')).not.toBeNull()
    expect(clearInstanceButton.closest('.ch-select-control')).not.toBeNull()
    expect(providerControl.classList.contains('has-selection')).toBe(false)
    expect(instanceControl.classList.contains('has-selection')).toBe(false)
    expect(container.querySelector('.ch-aurora-banner')).toBeNull()
    expect(clearProviderButton.hidden).toBe(true)
    expect(clearInstanceButton.hidden).toBe(true)
    expect([...providerSelect.options].map((item) => item.value)).toEqual([
      'dingtalk',
      'smartcmp'
    ])
    expect(providerSelect.value).toBe('')
    expect(providerSelect.selectedIndex).toBe(-1)
    providerSelect.value = 'smartcmp'
    providerSelect.dispatchEvent(new Event('change', { bubbles: true }))
    expect(clearProviderButton.hidden).toBe(false)
    expect(providerControl.classList.contains('has-selection')).toBe(true)
    expect([...instanceSelect.options].map((item) => item.value)).toEqual([
      'smartcmp/default'
    ])
    expect(instanceSelect.value).toBe('')
    expect(instanceSelect.selectedIndex).toBe(-1)
    instanceSelect.value = 'smartcmp/default'
    instanceSelect.dispatchEvent(new Event('change', { bubbles: true }))
    expect(clearInstanceButton.hidden).toBe(false)
    expect(instanceControl.classList.contains('has-selection')).toBe(true)
    expect([...instanceSelect.options].map((item) => item.textContent.trim())).toEqual([
      'default'
    ])

    clearInstanceButton.click()
    expect(instanceSelect.value).toBe('')
    expect(instanceSelect.selectedIndex).toBe(-1)
    expect(clearInstanceButton.hidden).toBe(true)
    expect(instanceControl.classList.contains('has-selection')).toBe(false)

    clearProviderButton.click()
    expect(providerSelect.value).toBe('')
    expect(providerSelect.selectedIndex).toBe(-1)
    expect(instanceSelect.disabled).toBe(true)
    expect([...instanceSelect.options].map((item) => item.value)).toEqual([])
    expect(clearProviderButton.hidden).toBe(true)
    expect(providerControl.classList.contains('has-selection')).toBe(false)

    await channelsPage.unmount()
  })

  test('optional provider selects stay blank even when only one option exists', async () => {
    window.history.replaceState({}, '', '/channels?type=feishu&edit=new')

    global.fetch = jest.fn((url) => {
      const target = String(url)

      if (target.endsWith('/api/channels')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([
            { type: 'feishu', name: 'Feishu', mode: 'bidirectional', connection_count: 0 }
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
                enum: ['longconnection'],
                enumLabels: {
                  longconnection: 'Long Connection'
                },
                default: 'longconnection'
              },
              provider_type: {
                type: 'string',
                title: 'Authentication Method',
                description: 'Choose which authentication configuration this channel should use.',
                enum: ['smartcmp'],
                enumLabels: {
                  smartcmp: 'SmartCMP'
                }
              },
              provider_binding: {
                type: 'string',
                title: 'Authentication Instance',
                description: 'Choose one configured authentication instance under the selected authentication method.',
                enum: ['smartcmp/default'],
                enumLabels: {
                  'smartcmp/default': 'default'
                },
                optionsByProvider: {
                  smartcmp: [
                    { value: 'smartcmp/default', label: 'default' }
                  ]
                }
              },
              app_id: {
                type: 'string',
                title: 'App ID'
              }
            },
            required_by_mode: {
              longconnection: ['app_id']
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

    const providerSelect = container.querySelector('select[name="provider_type"]')
    const instanceSelect = container.querySelector('select[name="provider_binding"]')

    expect(providerSelect).not.toBeNull()
    expect(instanceSelect).not.toBeNull()
    expect(providerSelect.value).toBe('')
    expect(instanceSelect.value).toBe('')
    expect(instanceSelect.disabled).toBe(true)
    expect(providerSelect.selectedIndex).toBe(-1)
    expect([...providerSelect.options].map((item) => item.value)).toEqual(['smartcmp'])
    expect([...instanceSelect.options].map((item) => item.value)).toEqual([])

    providerSelect.value = 'smartcmp'
    providerSelect.dispatchEvent(new Event('change', { bubbles: true }))

    expect(instanceSelect.value).toBe('')
    expect(instanceSelect.disabled).toBe(false)
    expect(instanceSelect.selectedIndex).toBe(-1)
    expect([...instanceSelect.options].map((item) => item.value)).toEqual(['smartcmp/default'])

    await channelsPage.unmount()
  })
})
