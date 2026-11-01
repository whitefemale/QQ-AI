'use strict'

const { contextBridge, ipcRenderer } = require('electron')

function subscribe(channel, listener) {
  const wrapped = (_event, payload) => {
    try {
      listener(payload)
    } catch (error) {
      console.error(`桌面事件处理失败：${error instanceof Error ? error.message : String(error)}`)
    }
  }
  ipcRenderer.on(channel, wrapped)
  return () => ipcRenderer.removeListener(channel, wrapped)
}

/** 渲染进程只能访问这些固定方法，不能接触 ipcRenderer、child_process 或文件系统。 */
contextBridge.exposeInMainWorld('aiGroupFriendDesktop', {
  isDesktop: true,
  getInfo: () => ipcRenderer.invoke('desktop:get-info'),
  getSettings: () => ipcRenderer.invoke('desktop:get-settings'),
  updateSettings: (patch) => ipcRenderer.invoke('desktop:update-settings', patch),
  startBackend: (options) => ipcRenderer.invoke('desktop:start-backend', { demo: Boolean(options?.demo) }),
  stopBackend: () => ipcRenderer.invoke('desktop:stop-backend'),
  restartBackend: () => ipcRenderer.invoke('desktop:restart-backend'),
  chooseConnectorsDir: () => ipcRenderer.invoke('desktop:choose-connectors-dir'),
  openFolder: (kind) => ipcRenderer.invoke('desktop:open-folder', kind),
  openReleases: () => ipcRenderer.invoke('desktop:open-releases'),
  openConsole: () => ipcRenderer.invoke('desktop:open-console'),
  quit: () => ipcRenderer.invoke('desktop:quit'),
  onState: (listener) => subscribe('desktop:state', listener),
  onSetupProgress: (listener) => subscribe('desktop:setup', listener),
  onLog: (listener) => subscribe('desktop:log', listener),
})
