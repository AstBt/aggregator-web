import { createRouter, createWebHistory } from 'vue-router';

import { getToken } from '../api/http';
import { useAuthStore } from '../stores/auth';

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('../layouts/AdminLayout.vue'),
    redirect: '/dashboard',
    children: [
      { path: 'dashboard', name: 'dashboard', component: () => import('../views/DashboardView.vue'), meta: { icon: '📊', title: '仪表盘' } },
      { path: 'sources', name: 'sources', component: () => import('../views/SourcesView.vue'), meta: { icon: '🧩', title: '爬取源配置' } },
      { path: 'crawl-params', name: 'crawl-params', component: () => import('../views/CrawlParamsView.vue'), meta: { icon: '📐', title: '爬取参数' } },
      { path: 'alive-params', name: 'alive-params', component: () => import('../views/AliveParamsView.vue'), meta: { icon: '💓', title: '验活参数' } },
      { path: 'storage', name: 'storage', component: () => import('../views/StorageView.vue'), meta: { icon: '💾', title: '结果存储' } },
      { path: 'tasks', name: 'tasks', component: () => import('../views/TasksView.vue'), meta: { icon: '⚙️', title: '任务管理' } },
      { path: 'subscriptions', name: 'subscriptions', component: () => import('../views/SubscriptionsView.vue'), meta: { icon: '📡', title: '订阅结果' } },
      { path: 'nodes', name: 'nodes', component: () => import('../views/NodesView.vue'), meta: { icon: '🌐', title: '节点浏览' } },
      { path: 'users', name: 'users', component: () => import('../views/UsersView.vue'), meta: { icon: '👥', title: '用户管理', role: 'admin' } },
      { path: 'settings', name: 'settings', component: () => import('../views/SettingsView.vue'), meta: { icon: '🔧', title: '系统设置' } },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
];

const router = createRouter({ history: createWebHistory(), routes });

router.beforeEach(async (to) => {
  const store = useAuthStore();
  if (to.meta.public) return true;
  if (!getToken()) return { path: '/login', query: { redirect: to.fullPath } };
  if (!store.loaded) {
    try {
      await store.loadMe();
    } catch {
      return { path: '/login' };
    }
  }
  if (to.meta.role && !store.atLeast(to.meta.role)) return { path: '/dashboard' };
  return true;
});

export default router;
