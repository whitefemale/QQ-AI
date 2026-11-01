import { describe, expect, it } from 'vitest'

import type { Account, AccountStatusSnapshot, AdapterInstance, ConnectionDiagnostics } from '@/api/types'
import {
  accountStatusCopy,
  checkStateLabel,
  checkStateTag,
  connectionDiagnosticsCopy,
  diagnosticsSummary,
  instanceActions,
  instanceStatusNextStep,
  sanitizeDiagnosticText,
} from '@/utils/diagnostics'

function report(overrides: Partial<ConnectionDiagnostics> = {}): ConnectionDiagnostics {
  return {
    ok: true,
    state: 'identity_verified',
    connection_mode: 'onebot11',
    is_mock: false,
    tested_at: '2026-10-31T00:00:00Z',
    latency_ms: 120,
    checks: [],
    login: { user_id: '10000', nickname: '测试机器人' },
    groups: [],
    group_count: 0,
    identity_verified: true,
    action_path_verified: true,
    group_list_verified: true,
    real_inbound_verified: false,
    real_outbound_verified: false,
    message_send_attempted: false,
    verified_scope: ['config', 'websocket', 'auth', 'identity', 'action'],
    unverified_scope: ['connector_runtime', 'real_inbound', 'real_outbound'],
    error_code: null,
    error_message: null,
    next_step: '在真实环境中完成受控消息收发验收。',
    note: '连接与身份检查不等于真实 QQ 群消息收发验证；本测试不发送任何消息。',
    ...overrides,
  }
}

describe('diagnostic check states', () => {
  it('never treats not_verified or skipped as passing', () => {
    expect(checkStateTag('ok')).toBe('success')
    expect(checkStateTag('warning')).toBe('warning')
    expect(checkStateTag('not_verified')).toBe('warning')
    expect(checkStateTag('failed')).toBe('danger')
    expect(checkStateTag('skipped')).toBe('info')
    expect(checkStateLabel('not_verified')).toBe('未验证')
    expect(checkStateLabel('skipped')).toBe('已跳过')
  })
})

describe('diagnostics summary', () => {
  it('does not claim real send/receive after identity verification', () => {
    const summary = diagnosticsSummary(report())
    expect(summary.type).toBe('warning')
    expect(summary.title).toContain('真实群收发尚未验证')
    expect(summary.description).toContain('不发送任何消息')
  })

  it('labels mock diagnostics as not connecting to real QQ', () => {
    const summary = diagnosticsSummary(report({ state: 'mock_only', is_mock: true, ok: true }))
    expect(summary.type).toBe('info')
    expect(summary.title).toContain('Mock 连接通过')
    expect(summary.title).toContain('不连接真实 QQ')
  })

  it('shows the failure reason for failed diagnostics', () => {
    const summary = diagnosticsSummary(
      report({ state: 'failed', ok: false, error_message: '连接器拒绝鉴权。' }),
    )
    expect(summary.type).toBe('error')
    expect(summary.title).toBe('连接失败')
    expect(summary.description).toBe('连接器拒绝鉴权。')
  })
})

describe('instance status guidance', () => {
  it('gives actionable next steps for unverified and failed instances', () => {
    expect(instanceStatusNextStep('connected_unverified', 'onebot11')).toContain('登录 QQ')
    expect(instanceStatusNextStep('error', 'onebot11', '连接被拒绝')).toContain('连接被拒绝')
    expect(instanceStatusNextStep('reconnecting', 'onebot11')).toContain('自动重连')
    expect(instanceStatusNextStep('unconfigured', 'onebot11')).toContain('WebSocket 地址')
    expect(instanceStatusNextStep('online', 'mock')).toContain('不代表真实 QQ')
    expect(instanceStatusNextStep('online', 'onebot11')).toContain('人工验收')
  })

  it('enables only the actions that match the runtime state', () => {
    expect(instanceActions('connected_unverified')).toEqual({
      canConnect: true,
      canDisconnect: true,
      canFetchGroups: false,
    })
    expect(instanceActions('online')).toEqual({
      canConnect: false,
      canDisconnect: true,
      canFetchGroups: true,
    })
    expect(instanceActions('disconnected').canFetchGroups).toBe(false)
    expect(instanceActions('error').canConnect).toBe(true)
  })
})

describe('sanitized copy', () => {
  it('redacts endpoints, local paths and QQ-like numbers', () => {
    const text = sanitizeDiagnosticText(
      '连接 ws://127.0.0.1:3001/ws?token=SECRET 失败；日志 C:\\Users\\secret\\app.log；登录 QQ 123456789。',
    )
    expect(text).not.toContain('ws://')
    expect(text).not.toContain('SECRET')
    expect(text).not.toContain('C:\\Users')
    expect(text).not.toContain('123456789')
    expect(text).toContain('端点已隐藏')
    expect(text).toContain('路径已隐藏')
    expect(text).toContain('数字标识已隐藏')
  })

  it('copies connection diagnostics without login identity or endpoints', () => {
    const copy = connectionDiagnosticsCopy(
      report({
        login: { user_id: '123456789', nickname: '敏感昵称' },
        groups: [{ group_id: '987654321', group_name: '敏感群名' }],
        group_count: 1,
        checks: [
          {
            id: 'config',
            label: '连接配置',
            state: 'failed',
            detail: '无法连接 ws://secret.invalid:3001/ws，账号 123456789',
            error_code: 'AUTH_FAILED',
            next_step: '检查 C:\\secret\\napcat\\config.json 与 Token。',
          },
        ],
      }),
    )
    expect(copy).toContain('连接配置')
    expect(copy).toContain('失败')
    expect(copy).toContain('AUTH_FAILED')
    expect(copy).toContain('测试发送消息：否')
    for (const secret of ['123456789', '敏感昵称', '987654321', '敏感群名', 'ws://', 'C:\\secret']) {
      expect(copy).not.toContain(secret)
    }
  })

  it('copies account status without names, QQ ids, endpoints or errors', () => {
    const instance = {
      id: 'instance-secret',
      account_id: 'account-secret',
      name: '敏感实例名',
      connection_mode: 'onebot11',
      endpoint: 'ws://secret.invalid:3001/ws',
      api_endpoint: null,
      token_configured: true,
      token_masked: 'secr****',
      allow_remote: false,
      auto_connect: false,
      enabled: true,
      capabilities: {},
      status: 'online',
      last_heartbeat_at: null,
      last_received_at: null,
      last_sent_at: null,
      heartbeat_age_seconds: 4,
      last_error_code: 'SECRET_CODE',
      last_error_message: '连接 ws://secret.invalid 失败',
      live_health: {
        status: 'connected_unverified',
        identity_verified: false,
        observed_at: '2026-10-31T00:00:00Z',
        heartbeat_age_seconds: 4,
        self_platform_user_id: '123456789',
      },
      created_at: '2026-10-31T00:00:00Z',
      updated_at: '2026-10-31T00:00:00Z',
    } as unknown as AdapterInstance
    const account = {
      id: 'account-secret',
      display_name: '敏感账号名',
      platform: 'qq',
      adapter_type: 'onebot11',
      self_platform_user_id: '123456789',
      enabled: true,
      allow_private: false,
      status: 'online',
      notes: 'SECRET_NOTE',
      instances: [instance],
      created_at: '2026-10-31T00:00:00Z',
      updated_at: '2026-10-31T00:00:00Z',
    } as Account
    const snapshot: AccountStatusSnapshot = {
      account,
      global_pause: { paused: false, reason: '', updated_at: null, actor: null },
      note: '状态来自进程内实时适配器。',
    }
    const copy = accountStatusCopy(snapshot)
    expect(copy).toContain('实例数量：1')
    expect(copy).toContain('已连接 · 身份未验证')
    expect(copy).toContain('身份验证：未验证')
    for (const secret of [
      '敏感账号名',
      '敏感实例名',
      '123456789',
      'ws://',
      'secr****',
      'SECRET_CODE',
      'SECRET_NOTE',
    ]) {
      expect(copy).not.toContain(secret)
    }
  })
})
