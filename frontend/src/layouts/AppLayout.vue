<template>
  <el-container class="layout">
    <el-aside width="232px" class="sidebar">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 64 64">
            <path
              d="M18 21h28a6 6 0 0 1 6 6v12a6 6 0 0 1-6 6H31l-9 7v-7h-4a6 6 0 0 1-6-6V27a6 6 0 0 1 6-6Z"
              fill="#ffffff"
            />
            <circle cx="25" cy="33" r="3.2" fill="#f97316" />
            <circle cx="32" cy="33" r="3.2" fill="#f97316" />
            <circle cx="39" cy="33" r="3.2" fill="#f97316" />
          </svg>
        </div>
        <div>
          <div class="brand-name">AI 群友</div>
          <div class="brand-sub">QQ 管理控制台</div>
        </div>
      </div>

      <el-menu :default-active="activePath" router class="nav" background-color="transparent" text-color="#cfe0ff" active-text-color="#ffffff">
        <el-menu-item v-for="item in navItems" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.title }}</span>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-footer">
        <div class="sidebar-version">
          <span>v{{ appStore.appVersion }}</span>
          <span v-if="desktopMode" class="desktop-badge">桌面版</span>
        </div>
        <div class="sidebar-note">本地优先 · 不收集 QQ 密码</div>
      </div>
    </el-aside>

    <el-container>
      <el-header height="64px" class="topbar">
        <div class="topbar-title">{{ currentTitle }}</div>
        <div class="top-actions">
          <el-tooltip :content="streamHint" placement="bottom">
            <el-tag :type="streamTag" size="small" effect="plain">
              实时事件：{{ streamText }}
            </el-tag>
          </el-tooltip>
          <el-tag v-if="appStore.paused" type="danger" effect="dark" size="small">全局紧急暂停中</el-tag>
          <el-button v-if="!appStore.paused" type="danger" plain size="small" @click="openPauseDialog">
            紧急暂停
          </el-button>
          <el-button v-else type="success" size="small" @click="resume">恢复运行</el-button>
        </div>
      </el-header>

      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>

  <el-dialog v-model="pauseDialog" title="启用全局紧急暂停" width="420px">
    <p class="muted">
      暂停后所有账号立即停止自动回复，发送队列不会发送任何消息。请填写原因以便审计。
    </p>
    <el-input v-model="pauseReason" type="textarea" :rows="3" maxlength="500" placeholder="例如：群内出现争议，需要人工确认" />
    <template #footer>
      <el-button @click="pauseDialog = false">取消</el-button>
      <el-button type="danger" :loading="acting" @click="confirmPause">确认暂停</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { errorMessage } from '@/api/client'
import { isDesktop } from '@/api/desktop'
import { useAppStore } from '@/stores/app'
import { useEventsStore } from '@/stores/events'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute } from 'vue-router'

const route = useRoute()
const appStore = useAppStore()
const eventsStore = useEventsStore()

const pauseDialog = ref(false)
const pauseReason = ref('管理员手动暂停')
const acting = ref(false)
const desktopMode = isDesktop()

const navItems = [
  { path: '/', title: '仪表盘', icon: 'Odometer' },
  { path: '/accounts', title: 'QQ 接入', icon: 'Connection' },
  { path: '/providers', title: '模型 API', icon: 'Cpu' },
  { path: '/capabilities', title: '能力中心', icon: 'MagicStick' },
  { path: '/personas', title: '人格工作台', icon: 'UserFilled' },
  { path: '/groups', title: '群聊管理', icon: 'ChatDotRound' },
  { path: '/memories', title: '长期记忆', icon: 'Collection' },
  { path: '/messages', title: '消息与用量', icon: 'Document' },
  { path: '/playground', title: '模拟测试', icon: 'VideoPlay' },
  { path: '/extensions', title: '扩展管理', icon: 'Grid' },
  { path: '/settings', title: '系统设置', icon: 'Setting' },
]

const activePath = computed(() => (route.path === '/' ? '/' : route.path))
const currentTitle = computed(() => (typeof route.meta.title === 'string' ? route.meta.title : ''))

const streamText = computed(() => {
  if (eventsStore.status === 'open') return '已连接'
  if (eventsStore.status === 'connecting') return '连接中'
  if (eventsStore.status === 'closed') return '已断开'
  return '未连接'
})
const streamTag = computed<'success' | 'warning' | 'danger' | 'info'>(() => {
  if (eventsStore.status === 'open') return 'success'
  if (eventsStore.status === 'connecting') return 'warning'
  if (eventsStore.status === 'closed') return 'danger'
  return 'info'
})
const streamHint = computed(() =>
  eventsStore.status === 'closed'
    ? '浏览器会自动重连；若长时间断开，请检查后端是否运行。'
    : '服务器推送的实时事件流（SSE）。',
)

function openPauseDialog(): void {
  pauseReason.value = '管理员手动暂停'
  pauseDialog.value = true
}

async function confirmPause(): Promise<void> {
  acting.value = true
  try {
    await appStore.pauseAll(pauseReason.value)
    pauseDialog.value = false
    ElMessage.success('已启用全局紧急暂停。')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    acting.value = false
  }
}

async function resume(): Promise<void> {
  try {
    await ElMessageBox.confirm('恢复后将重新允许自动回复与发送队列。请确认群配置与额度。', '恢复运行', {
      confirmButtonText: '恢复',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await appStore.resumeAll()
    ElMessage.success('已恢复运行。')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  }
}

onMounted(async () => {
  eventsStore.connect()
  try {
    await appStore.refresh()
  } catch {
    // 网络错误已存入 store，页面仍可渲染
  }
})

onBeforeUnmount(() => {
  eventsStore.disconnect()
})
</script>

<style scoped>
.layout {
  min-height: 100vh;
}

.sidebar {
  display: flex;
  flex-direction: column;
  background:
    radial-gradient(circle at 12% 0%, rgba(249, 115, 22, 0.16), transparent 32%),
    linear-gradient(180deg, var(--app-sidebar), var(--app-sidebar-deep));
  color: var(--app-sidebar-text);
  position: sticky;
  top: 0;
  height: 100vh;
  box-shadow: 6px 0 24px rgba(11, 42, 91, 0.08);
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 22px 18px 16px;
}

.brand-mark {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, var(--app-accent), var(--app-orange));
  box-shadow: 0 8px 18px rgba(3, 18, 43, 0.35);
}

.brand-mark svg {
  width: 30px;
  height: 30px;
  display: block;
}

.brand-name {
  font-weight: 700;
  font-size: 16px;
  letter-spacing: 0.01em;
}

.brand-sub {
  margin-top: 2px;
  font-size: 11px;
  color: #9fbde8;
}

.nav {
  flex: 1;
  padding: 6px 10px;
  overflow-y: auto;
}

.nav :deep(.el-menu-item) {
  position: relative;
  height: 42px;
  border-radius: 9px;
  margin: 3px 0;
  color: var(--app-sidebar-text);
}

.nav :deep(.el-menu-item:hover) {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}

.nav :deep(.el-menu-item.is-active) {
  background: linear-gradient(90deg, rgba(255, 255, 255, 0.18), rgba(255, 255, 255, 0.08));
  color: #fff;
  font-weight: 600;
}

.nav :deep(.el-menu-item.is-active::before) {
  content: '';
  position: absolute;
  left: 0;
  top: 10px;
  bottom: 10px;
  width: 3px;
  border-radius: 3px;
  background: var(--app-orange);
}

.nav :deep(.el-menu-item.is-active .el-icon) {
  color: var(--app-orange);
}

.sidebar-footer {
  padding: 14px 18px 18px;
  font-size: 12px;
  color: #9fbde8;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.sidebar-version {
  display: flex;
  align-items: center;
  gap: 8px;
}

.desktop-badge {
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid rgba(249, 115, 22, 0.5);
  background: rgba(249, 115, 22, 0.14);
  color: #ffc28f;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.sidebar-note {
  margin-top: 5px;
  font-size: 11px;
  color: #7f9cc8;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--app-border);
  padding: 0 24px;
}

.topbar-title {
  position: relative;
  padding-left: 12px;
  font-size: 15px;
  font-weight: 650;
}

.topbar-title::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  width: 4px;
  height: 16px;
  border-radius: 2px;
  transform: translateY(-50%);
  background: linear-gradient(180deg, var(--app-accent), var(--app-orange));
}

.top-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.main {
  padding: 22px 24px 40px;
  background:
    radial-gradient(circle at 100% 0%, rgba(37, 99, 235, 0.06), transparent 340px),
    var(--app-bg);
}
</style>
