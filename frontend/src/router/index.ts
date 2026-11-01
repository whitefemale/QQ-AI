import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import AppLayout from '@/layouts/AppLayout.vue'

export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: AppLayout,
    children: [
      {
        path: '',
        name: 'dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { title: '仪表盘', icon: 'Odometer' },
      },
      {
        path: 'onboarding',
        name: 'onboarding',
        component: () => import('@/views/OnboardingView.vue'),
        meta: { title: '接入向导', icon: 'Guide' },
      },
      {
        path: 'diagnostics',
        name: 'diagnostics',
        component: () => import('@/views/DiagnosticsView.vue'),
        meta: { title: '诊断与日志', icon: 'DocumentChecked' },
      },
      {
        path: 'accounts',
        name: 'accounts',
        component: () => import('@/views/AccountsView.vue'),
        meta: { title: 'QQ 接入', icon: 'Connection' },
      },
      {
        path: 'connectors',
        name: 'connectors',
        component: () => import('@/views/ConnectorsView.vue'),
        meta: { title: '连接器', icon: 'Link' },
      },
      {
        path: 'providers',
        name: 'providers',
        component: () => import('@/views/ProvidersView.vue'),
        meta: { title: '模型 API', icon: 'Cpu' },
      },
      {
        path: 'capabilities',
        name: 'capabilities',
        component: () => import('@/views/CapabilitiesView.vue'),
        meta: { title: '能力中心', icon: 'MagicStick' },
      },
      {
        path: 'personas',
        name: 'personas',
        component: () => import('@/views/PersonasView.vue'),
        meta: { title: '人格工作台', icon: 'UserFilled' },
      },
      {
        path: 'groups',
        name: 'groups',
        component: () => import('@/views/GroupsView.vue'),
        meta: { title: '群聊管理', icon: 'ChatDotRound' },
      },
      {
        path: 'memories',
        name: 'memories',
        component: () => import('@/views/MemoriesView.vue'),
        meta: { title: '长期记忆', icon: 'Collection' },
      },
      {
        path: 'messages',
        name: 'messages',
        component: () => import('@/views/MessagesView.vue'),
        meta: { title: '消息与用量', icon: 'Document' },
      },
      {
        path: 'playground',
        name: 'playground',
        component: () => import('@/views/PlaygroundView.vue'),
        meta: { title: '模拟测试', icon: 'VideoPlay' },
      },
      {
        path: 'extensions',
        name: 'extensions',
        component: () => import('@/views/ExtensionsView.vue'),
        meta: { title: '扩展管理', icon: 'Grid' },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/SettingsView.vue'),
        meta: { title: '系统设置', icon: 'Setting' },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : ''
  document.title = title ? `${title} · AI 群友管理控制台` : 'AI 群友管理控制台'
})

export default router
