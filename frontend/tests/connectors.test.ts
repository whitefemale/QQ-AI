import { describe, expect, it } from 'vitest'

import type { ConnectorInstallation, ConnectorJob, ConnectorStateName } from '@/api/types'
import {
  CONNECTOR_STATE_LABELS,
  CONNECTOR_STATE_NOTES,
  confirmationMatches,
  connectorInstallerText,
  connectorProcessText,
  connectorStateLabel,
  connectorStateNextSteps,
  connectorStateNote,
  connectorStateTag,
  desktopConnectorDirHint,
  isRealTrafficVerified,
  jobCanCancel,
  jobProgressText,
  licenseText,
} from '@/utils/connectors'

const STATES: ConnectorStateName[] = [
  'not_installed',
  'installing',
  'installer_ready',
  'installer_running',
  'installed_not_started',
  'starting',
  'waiting_login',
  'logged_in_not_connected',
  'connected_traffic_unverified',
  'traffic_verified',
  'interrupted',
  'running_unmanaged',
  'auth_failed',
  'incompatible',
  'external_readonly',
  'unknown_error',
]

function installation(overrides: Partial<ConnectorInstallation> = {}): ConnectorInstallation {
  return {
    id: 'inst-1',
    kind: 'napcat',
    display_name: 'NapCat',
    version: 'v4.18.42',
    source: 'managed_release',
    managed: true,
    active: true,
    layout_confidence: 'detected_shell',
    shell_installed: true,
    installer_ready: false,
    version_compatibility: 'documented',
    auto_configure_allowed: true,
    documented_config_version: 'v4.18.42',
    root_path: 'D:/repo/connectors/napcat/v4.18.42',
    shell_path: 'D:/repo/connectors/napcat/v4.18.42/NapCat.Shell',
    config_files: [],
    license: { status: 'not_fetched' },
    installer_launched_at: null,
    last_seen_at: '2026-10-31T00:00:00Z',
    last_state: 'installed_not_started',
    state: {
      state: 'installed_not_started',
      severity: 'info',
      inferred: false,
      evidence: [],
      next_steps: ['启动连接器。'],
    },
    next_steps: [],
    can_start: true,
    can_stop: false,
    can_configure: true,
    can_run_installer: false,
    can_activate: false,
    can_diagnose: false,
    real_traffic_verified: false,
    process: { owned: false, alive: false, started_at: null },
    installer: { owned: false, alive: false, started_at: null },
    ports: [],
    port_listening: false,
    active_job: null,
    instance: null,
    ...overrides,
  }
}

function job(overrides: Partial<ConnectorJob> = {}): ConnectorJob {
  return {
    id: 'job-1',
    kind: 'install',
    version: 'v4.18.42',
    target_name: 'v4.18.42',
    state: 'running',
    stage: 'download',
    progress: 35,
    message: '正在下载',
    error_code: null,
    error_message: null,
    cancel_requested: false,
    log_tail: '',
    can_cancel: true,
    started_at: '2026-10-31T00:00:00Z',
    finished_at: null,
    created_at: '2026-10-31T00:00:00Z',
    updated_at: '2026-10-31T00:00:01Z',
    ...overrides,
  }
}

describe('connector state presentation', () => {
  it('只把真实双向收发标成成功，其余状态都不是绿色成功', () => {
    for (const state of STATES) {
      expect(connectorStateLabel(state)).not.toBe('')
      expect(connectorStateNote(state)).not.toBe('')
      expect(connectorStateNote(state)).not.toContain('已通过真实收发验证')
    }
    expect(connectorStateTag('traffic_verified')).toBe('success')
    expect(STATES.filter((state) => state !== 'traffic_verified').map(connectorStateTag)).not.toContain('success')
    expect(connectorStateTag('auth_failed')).toBe('danger')
    expect(connectorStateTag('incompatible')).toBe('danger')
    expect(connectorStateTag('installer_ready')).toBe('warning')
    expect(connectorStateTag('waiting_login')).toBe('warning')
  })

  it('为每个状态提供非空标签与说明，并标注推断状态', () => {
    expect(Object.keys(CONNECTOR_STATE_LABELS).sort()).toEqual([...STATES].sort())
    expect(Object.keys(CONNECTOR_STATE_NOTES).sort()).toEqual([...STATES].sort())
    expect(connectorStateLabel('waiting_login')).toContain('推断')
    expect(connectorStateLabel('logged_in_not_connected')).toContain('推断')
    expect(connectorStateLabel('installer_ready')).toContain('安装器未运行')
    expect(connectorStateLabel('connected_traffic_unverified')).toContain('未验证')
    expect(connectorStateLabel('external_readonly')).toContain('只读')
  })

  it('未知状态不冒充成功或可用', () => {
    expect(connectorStateLabel('something_new')).toBe('something_new')
    expect(connectorStateNote('something_new')).toContain('未识别')
    expect(connectorStateTag('something_new')).toBe('info')
    expect(connectorStateLabel(null)).toBe('状态未知')
  })

  it('优先使用安装卡片给出的下一步，其次才回退状态说明', () => {
    expect(connectorStateNextSteps(installation({ next_steps: ['运行官方安装器。'] }))).toEqual([
      '运行官方安装器。',
    ])
    expect(connectorStateNextSteps(installation())).toEqual(['启动连接器。'])
    expect(
      connectorStateNextSteps(
        installation({
          state: {
            state: 'unknown_error',
            severity: 'error',
            inferred: false,
            evidence: [],
            next_steps: [],
          },
        }),
      ),
    ).toEqual(['状态推导失败；请重新扫描并查看日志。'])
  })
})

describe('connector evidence honesty', () => {
  it('进程存活与端口监听都不能推导为已登录或真实收发', () => {
    const owned = installation({ process: { owned: true, alive: true, started_at: '2026-10-31T00:00:00Z' } })
    expect(connectorProcessText(owned)).toContain('受管进程运行中')
    expect(connectorProcessText(owned)).not.toContain('在线')
    const external = installation({ port_listening: true })
    expect(connectorProcessText(external)).toContain('归属未知')
    expect(connectorProcessText(external)).toContain('手动确认')
  })

  it('安装器运行也不是安装完成', () => {
    const running = installation({ installer: { owned: true, alive: true, started_at: null } })
    expect(connectorInstallerText(running)).toContain('仍在运行')
    const exited = installation({ installer_launched_at: '2026-10-31T00:00:00Z' })
    expect(connectorInstallerText(exited)).toContain('已无受管安装器进程')
    expect(connectorInstallerText(installation())).toContain('尚未启动')
  })

  it('只有状态与后端证据同时成立才显示真实双向收发', () => {
    const verified = installation({
      state: {
        state: 'traffic_verified',
        severity: 'success',
        inferred: false,
        evidence: [],
        next_steps: [],
      },
      real_traffic_verified: true,
    })
    expect(isRealTrafficVerified(verified)).toBe(true)
    expect(isRealTrafficVerified({ ...verified, real_traffic_verified: false })).toBe(false)
    expect(isRealTrafficVerified(installation({ real_traffic_verified: true }))).toBe(false)
  })

  it('许可证未获取时明确要求人工审查', () => {
    expect(licenseText({ status: 'not_fetched' })).toContain('需人工审查')
    expect(licenseText({ status: 'reviewed', spdx_id: 'MIT' })).toBe('MIT')
  })
})

describe('connector confirmations and jobs', () => {
  it('确认词必须精确匹配（仅忽略首尾空白）', () => {
    expect(confirmationMatches(' INSTALL ', 'INSTALL')).toBe(true)
    expect(confirmationMatches('install', 'INSTALL')).toBe(false)
    expect(confirmationMatches('INSTALL NOW', 'INSTALL')).toBe(false)
    expect(confirmationMatches('', 'INSTALL')).toBe(false)
    expect(confirmationMatches(null, 'INSTALL')).toBe(false)
  })

  it('任务进度不会隐藏失败原因，取消按钮按状态启用', () => {
    expect(jobProgressText(job())).toContain('下载')
    expect(jobProgressText(job({ progress: 60, stage: 'verified', message: '' }))).toContain('60%')
    expect(
      jobProgressText(job({ state: 'failed', error_code: 'HASH_MISMATCH', error_message: '摘要不匹配' })),
    ).toBe('失败（HASH_MISMATCH）：摘要不匹配')
    expect(jobCanCancel(job())).toBe(true)
    expect(jobCanCancel(job({ cancel_requested: true }))).toBe(false)
    expect(jobCanCancel(job({ state: 'succeeded' }))).toBe(false)
    expect(jobCanCancel(null)).toBe(false)
  })
})

describe('desktop connector directory hint', () => {
  it('浏览器模式不伪造目录选择能力', () => {
    expect(desktopConnectorDirHint(false)).toContain('无法选择服务器目录')
    expect(desktopConnectorDirHint(true)).toContain('重启后端')
  })
})
