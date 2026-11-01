/** 连接器管理 API 客户端。所有端点在浏览器外仍会被后端本机守卫拒绝。 */

import { api } from '@/api/client'
import type {
  ConnectorCapabilities,
  ConnectorConfigFileSummary,
  ConnectorConfigPreview,
  ConnectorInstallation,
  ConnectorJob,
  ConnectorRelease,
  ConnectorSnapshot,
  ConnectorSummary,
  ConnectionDiagnostics,
} from '@/api/types'

export const CONNECTOR_CONFIRMATIONS = {
  install: 'INSTALL',
  cancel: 'CANCEL',
  runInstaller: 'RUN INSTALLER',
  start: 'START NAPCAT',
  stop: 'STOP NAPCAT',
  applyConfig: 'WRITE CONFIG',
  autoConfigure: 'AUTO CONFIG',
  restoreConfig: 'RESTORE CONFIG',
  switchVersion: 'SWITCH VERSION',
  confirmIdentity: 'CONFIRM IDENTITY',
  importConfig: 'IMPORT CONFIG',
} as const

export type ConnectorConfirmation = (typeof CONNECTOR_CONFIRMATIONS)[keyof typeof CONNECTOR_CONFIRMATIONS]

export function connectorSummary(): Promise<ConnectorSummary> {
  return api<ConnectorSummary>('/connectors')
}

export function connectorCapabilities(): Promise<ConnectorCapabilities> {
  return api<ConnectorCapabilities>('/connectors/capabilities')
}

export function scanConnectors(): Promise<{ items: ConnectorInstallation[]; count: number }> {
  return api<{ items: ConnectorInstallation[]; count: number }>('/connectors/scan', { method: 'POST' })
}

export function getConnectorInstallation(installationId: string): Promise<ConnectorInstallation> {
  return api<ConnectorInstallation>(`/connectors/installations/${encodeURIComponent(installationId)}`)
}

export function listConnectorReleases(): Promise<{ items: ConnectorRelease[]; note: string }> {
  return api<{ items: ConnectorRelease[]; note: string }>('/connectors/releases', { timeoutMs: 60_000 })
}

export function checkConnectorRelease(version?: string): Promise<ConnectorRelease> {
  return api<ConnectorRelease>('/connectors/check-release', {
    query: { version },
    timeoutMs: 60_000,
  })
}

export function startConnectorInstall(version: string | null, confirmText: string): Promise<ConnectorJob> {
  return api<ConnectorJob>('/connectors/install', {
    method: 'POST',
    body: { version: version || undefined, confirm_text: confirmText },
  })
}

export function getConnectorJob(jobId: string): Promise<ConnectorJob> {
  return api<ConnectorJob>(`/connectors/jobs/${encodeURIComponent(jobId)}`)
}

export function cancelConnectorJob(jobId: string, confirmText: string): Promise<ConnectorJob> {
  return api<ConnectorJob>(`/connectors/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: 'POST',
    body: { confirm_text: confirmText },
  })
}

export function runConnectorInstaller(installationId: string, confirmText: string): Promise<Record<string, unknown>> {
  return api(`/connectors/installations/${encodeURIComponent(installationId)}/run-installer`, {
    method: 'POST',
    body: { confirm_text: confirmText },
  })
}

export function startManagedConnector(installationId: string, confirmText: string): Promise<Record<string, unknown>> {
  return api(`/connectors/installations/${encodeURIComponent(installationId)}/start`, {
    method: 'POST',
    body: { confirm_text: confirmText },
  })
}

export function stopManagedConnector(installationId: string, confirmText: string): Promise<Record<string, unknown>> {
  return api(`/connectors/installations/${encodeURIComponent(installationId)}/stop`, {
    method: 'POST',
    body: { confirm_text: confirmText },
  })
}

export function previewConnectorConfig(
  installationId: string,
  requestedRelative?: string | null,
): Promise<ConnectorConfigPreview> {
  return api<ConnectorConfigPreview>(
    `/connectors/installations/${encodeURIComponent(installationId)}/config/preview`,
    { query: { requested_relative: requestedRelative ?? undefined } },
  )
}

export function applyConnectorConfig(
  installationId: string,
  requestedRelative: string | null,
  confirmText: string,
): Promise<Record<string, unknown>> {
  return api(`/connectors/installations/${encodeURIComponent(installationId)}/config/apply`, {
    method: 'POST',
    body: { requested_relative: requestedRelative || undefined, confirm_text: confirmText },
  })
}

/** 向导专用：为受管连接器自动分配本地端口与 Token 并创建受管账号；不会启动连接器或登录 QQ。 */
export function autoConfigureManagedConnector(
  installationId: string | null,
  confirmText: string,
): Promise<Record<string, unknown>> {
  return api('/onboarding/actions/auto-configure-connector', {
    method: 'POST',
    body: { installation_id: installationId || undefined, confirm_text: confirmText },
  })
}

export function connectorSnapshots(installationId: string): Promise<{ items: ConnectorSnapshot[]; note: string }> {
  return api<{ items: ConnectorSnapshot[]; note: string }>(
    `/connectors/installations/${encodeURIComponent(installationId)}/snapshots`,
  )
}

export function rollbackConnectorConfig(
  installationId: string,
  snapshotGroup: string | null,
  confirmText: string,
): Promise<Record<string, unknown>> {
  return api(`/connectors/installations/${encodeURIComponent(installationId)}/config/rollback`, {
    method: 'POST',
    body: { snapshot_group: snapshotGroup || undefined, confirm_text: confirmText },
  })
}

export function activateConnectorVersion(
  installationId: string,
  confirmText: string,
): Promise<Record<string, unknown>> {
  return api(`/connectors/installations/${encodeURIComponent(installationId)}/activate`, {
    method: 'POST',
    body: { confirm_text: confirmText },
  })
}

export function diagnoseConnector(installationId: string): Promise<ConnectionDiagnostics> {
  return api<ConnectionDiagnostics>(`/connectors/installations/${encodeURIComponent(installationId)}/diagnose`, {
    method: 'POST',
    timeoutMs: 60_000,
  })
}

export function confirmConnectorIdentity(
  accountId: string,
  userId: string,
  confirmText: string,
): Promise<Record<string, unknown>> {
  return api(`/connectors/accounts/${encodeURIComponent(accountId)}/confirm-identity`, {
    method: 'POST',
    body: { user_id: userId, confirm_text: confirmText },
  })
}

export function importConnectorConfig(
  text: string,
  displayName: string,
  confirmText: string,
): Promise<Record<string, unknown>> {
  return api('/connectors/import-config', {
    method: 'POST',
    body: { text, display_name: displayName || undefined, confirm_text: confirmText },
  })
}

/** 配置预览对话框需要展示的文件摘要；只读，不包含配置正文。 */
export type ConnectorConfigFile = ConnectorConfigFileSummary
