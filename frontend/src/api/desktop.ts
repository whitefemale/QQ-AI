/**
 * 桌面版桥接：仅当页面运行在 Electron 窗口内时由 preload 注入。
 * 浏览器模式不会注入该对象，所有桌面能力必须显式判断后再调用。
 */

export type DesktopBackendStatus =
  | 'stopped'
  | 'starting'
  | 'running'
  | 'stopping'
  | 'external'
  | 'error'

export interface DesktopBackendInfo {
  status: DesktopBackendStatus
  port: number | null
  pid: number | null
  managed: boolean
  version: string
  error: string
}

export interface DesktopSettings {
  autoStartBackend: boolean
  closeToTray: boolean
  showWindowOnStart: boolean
  firstRunCompleted: boolean
  dataDir: string
}

export interface DesktopSetupStep {
  id: string
  label: string
  status: 'pending' | 'running' | 'ok' | 'skipped' | 'error'
  detail: string
}

export interface DesktopSetupState {
  running: boolean
  error: string
  warning: string
  steps: DesktopSetupStep[]
}

export interface DesktopLogEntry {
  source: 'backend' | 'setup'
  line: string
  at: string
}

export interface DesktopInfo {
  isDesktop: true
  desktopVersion: string
  backend: DesktopBackendInfo
  settings: DesktopSettings
  dataDir: string
  logPath: string
  desktopLogPath: string
  setup: DesktopSetupState
  logs: DesktopLogEntry[]
}

export interface DesktopSettingsResult {
  settings: DesktopSettings
  restartRequired: boolean
}

export type DesktopFolderKind = 'data' | 'logs' | 'backups'

interface DesktopBridge {
  isDesktop: true
  getInfo(): Promise<DesktopInfo>
  getSettings(): Promise<DesktopSettings>
  updateSettings(patch: Partial<DesktopSettings>): Promise<DesktopSettingsResult>
  startBackend(options?: { demo?: boolean }): Promise<DesktopInfo>
  stopBackend(): Promise<DesktopInfo>
  restartBackend(): Promise<DesktopInfo>
  openFolder(kind: DesktopFolderKind): Promise<void>
  openReleases(): Promise<void>
  openConsole(): Promise<DesktopInfo>
  quit(): Promise<void>
  onState(listener: (info: DesktopInfo) => void): () => void
  onSetupProgress(listener: (setup: DesktopSetupState) => void): () => void
  onLog(listener: (entry: DesktopLogEntry) => void): () => void
}

declare global {
  interface Window {
    aiGroupFriendDesktop?: DesktopBridge
  }
}

export function desktopBridge(): DesktopBridge | null {
  return typeof window !== 'undefined' ? (window.aiGroupFriendDesktop ?? null) : null
}

export function isDesktop(): boolean {
  return Boolean(desktopBridge()?.isDesktop)
}

function bridge(): DesktopBridge {
  const current = desktopBridge()
  if (!current) throw new Error('当前不在桌面版中运行，桌面功能不可用。')
  return current
}

/** Electron IPC 会把错误包装成 “Error invoking remote method …”；去掉前缀便于展示。 */
export function desktopErrorMessage(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error)
  return raw.replace(/^Error invoking remote method '[^']+': (?:Error: )?/u, '')
}

export function getDesktopInfo(): Promise<DesktopInfo> {
  return bridge().getInfo()
}

export function getDesktopSettings(): Promise<DesktopSettings> {
  return bridge().getSettings()
}

export function updateDesktopSettings(patch: Partial<DesktopSettings>): Promise<DesktopSettingsResult> {
  return bridge().updateSettings(patch)
}

export function restartDesktopBackend(): Promise<DesktopInfo> {
  return bridge().restartBackend()
}

export function openDesktopFolder(kind: DesktopFolderKind): Promise<void> {
  return bridge().openFolder(kind)
}

export function openDesktopReleases(): Promise<void> {
  return bridge().openReleases()
}

export function subscribeDesktopState(listener: (info: DesktopInfo) => void): () => void {
  const current = desktopBridge()
  if (!current) return () => undefined
  return current.onState(listener)
}
