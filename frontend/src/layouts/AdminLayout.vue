<template>
  <div class="app">
    <aside class="sidebar">
      <div class="side-logo"><span class="mark">🛰️</span>Aggregator<span class="ver">v2.4</span></div>
      <nav class="side-nav">
        <div class="nav-group">控制台</div>
        <router-link class="nav-item" to="/dashboard"><span class="ico">📊</span>仪表盘</router-link>
        <div class="nav-group">配置</div>
        <router-link class="nav-item" to="/sources"><span class="ico">🧩</span>爬取源配置</router-link>
        <router-link class="nav-item" to="/crawl-params"><span class="ico">📐</span>爬取参数</router-link>
        <router-link class="nav-item" to="/alive-params"><span class="ico">💓</span>验活参数</router-link>
        <router-link class="nav-item" to="/storage"><span class="ico">💾</span>结果存储</router-link>
        <div class="nav-group">运行</div>
        <router-link class="nav-item" to="/tasks"><span class="ico">⚙️</span>任务管理</router-link>
        <div class="nav-group">结果</div>
        <router-link class="nav-item" to="/subscriptions"><span class="ico">📡</span>订阅结果</router-link>
        <router-link class="nav-item" to="/nodes"><span class="ico">🌐</span>节点浏览</router-link>
        <div class="nav-group">系统</div>
        <router-link v-if="auth.atLeast('admin')" class="nav-item" to="/users"><span class="ico">👥</span>用户管理</router-link>
        <router-link class="nav-item" to="/settings"><span class="ico">🔧</span>系统设置</router-link>
      </nav>
    </aside>
    <div class="main">
      <header class="topbar">
        <div class="crumb">{{ title }}</div>
        <div class="topbar-right">
          <div v-if="announcement.enable && announcement.text" class="ann-bar" @click="annPaused = !annPaused">
            <div class="ann-track" :class="{ pause: annPaused }">
              <span class="ann-text">{{ announcement.text }}</span>
              <span class="ann-text ann-ghost">{{ announcement.text }}</span>
            </div>
          </div>
          <div class="icon-btn">🔔</div>
          <a-dropdown>
            <div class="user-chip">
              <span class="avatar" :class="auth.role === 'admin' ? '' : auth.role === 'operator' ? 'op' : 'vw'">{{ auth.user?.username?.[0]?.toUpperCase() }}</span>
              <span><span class="nm">{{ auth.user?.username }}</span><br><span class="rl">{{ roleLabel }}</span></span>
            </div>
            <template #overlay>
              <a-menu>
                <a-menu-item @click="go('/settings')">系统设置</a-menu-item>
                <a-menu-item @click="logout">退出登录</a-menu-item>
              </a-menu>
            </template>
          </a-dropdown>
        </div>
      </header>
      <main class="content"><router-view /></main>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { message } from 'ant-design-vue';

import { announcement as announcementApi } from '../api';
import { useAuthStore } from '../stores/auth';

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const title = computed(() => route.meta.title || '控制台');
const roleLabel = computed(() => ({ admin: '管理员', operator: '操作员', viewer: '只读' }[auth.role] || auth.role));

const announcement = ref({ text: '', enable: false });
const annPaused = ref(false);
let annTimer = null;

const loadAnnouncement = async () => {
  try {
    announcement.value = await announcementApi.read();
  } catch {
    /* 忽略公告加载失败 */
  }
};

const go = (path) => router.push(path);
const logout = async () => {
  await auth.logout();
  message.success('已退出登录');
  router.push('/login');
};

onMounted(() => {
  loadAnnouncement();
  annTimer = setInterval(loadAnnouncement, 5 * 60 * 1000);
});
onBeforeUnmount(() => clearInterval(annTimer));
</script>

<style scoped>
.ann-bar{max-width:340px;overflow:hidden;position:relative;height:34px;display:flex;align-items:center;cursor:pointer;border-radius:8px;background:#fffbe6;border:1px solid #ffe58f;padding:0 12px}
.ann-track{position:relative;display:flex;gap:36px;white-space:nowrap;animation:ann-scroll 18s linear infinite}
.ann-track.pause{animation-play-state:paused}
.ann-text{font-size:12.5px;color:#d48806;white-space:nowrap}
.ann-ghost{position:absolute;left:100%;top:0}
@keyframes ann-scroll{from{transform:translateX(0)}to{transform:translateX(-100%)}}
.ann-bar:hover{background:#fff7d6}
</style>
