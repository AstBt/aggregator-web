<template>
  <div class="vben-auth">
    <!-- 顶部 Logo 与应用名 -->
    <div class="auth-logo">
      <span class="mark">🛰️</span>
      <p>Aggregator</p>
    </div>

    <!-- 左侧：登录表单面板 -->
    <div class="auth-form-side">
      <div class="auth-form-box">
        <div class="auth-title">
          <h1>欢迎回来 👋🏻</h1>
          <p class="auth-subtitle">管理员账号登录 · 不开放注册 · 未接入第三方登录</p>
        </div>
        <a-form layout="vertical" :model="form" @finish="onLogin">
          <a-form-item>
            <a-input v-model:value="form.username" size="large" placeholder="请输入管理员用户名" autocomplete="username" />
          </a-form-item>
          <a-form-item>
            <a-input-password v-model:value="form.password" size="large" placeholder="请输入密码" autocomplete="current-password" />
          </a-form-item>
        </a-form>
        <div class="auth-row">
          <a-checkbox v-model:checked="remember">记住我</a-checkbox>
          <span class="vben-link">忘记密码？</span>
        </div>
        <a-button type="primary" size="large" block :loading="loading" @click="onLogin">登录</a-button>
        <div class="auth-tip">
          <div>演示环境：默认账号 <b>admin / admin123</b>（初始化命令可改）。</div>
          <div><b>安全策略：</b>bcrypt 哈希 · 5 次失败锁 15 分钟 · 会话 12 小时 · 无注册。</div>
        </div>
      </div>
      <div class="auth-copyright">Aggregator Web 管理平台 v2.4 · Vue Vben 设计语言 + FastAPI</div>
    </div>

    <!-- 右侧：系统介绍（渐变光晕背景） -->
    <div class="auth-intro-side">
      <div class="login-background"></div>
      <div class="intro-content">
        <svg class="slogan" viewBox="0 0 480 320" fill="none" xmlns="http://www.w3.org/2000/svg">
          <!-- 信号塔与聚合节点主题插图 -->
          <defs>
            <linearGradient id="lg1" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stop-color="#1677ff" stop-opacity=".9"/>
              <stop offset="1" stop-color="#69b4ff" stop-opacity=".5"/>
            </linearGradient>
            <linearGradient id="lg2" x1="0" y1="1" x2="1" y2="0">
              <stop offset="0" stop-color="#52c41a" stop-opacity=".85"/>
              <stop offset="1" stop-color="#95de64" stop-opacity=".45"/>
            </linearGradient>
          </defs>
          <!-- 中心雷达 -->
          <circle cx="240" cy="160" r="96" stroke="#1677ff" stroke-opacity=".25" stroke-width="1.5" stroke-dasharray="4 6"/>
          <circle cx="240" cy="160" r="64" stroke="#1677ff" stroke-opacity=".35" stroke-width="1.5"/>
          <circle cx="240" cy="160" r="32" fill="url(#lg1)" fill-opacity=".18" stroke="#1677ff" stroke-width="2"/>
          <circle cx="240" cy="160" r="10" fill="#1677ff"/>
          <!-- 环绕节点 -->
          <g font-family="sans-serif" font-size="13" fill="rgba(0,0,0,.65)">
            <g><rect x="88" y="72" width="86" height="34" rx="8" fill="#fff" stroke="#e5e6eb"/><text x="104" y="94">📨 TG</text>
              <path d="M174 89 L208 112" stroke="#1677ff" stroke-opacity=".5" stroke-width="1.5"/></g>
            <g><rect x="306" y="72" width="86" height="34" rx="8" fill="#fff" stroke="#e5e6eb"/><text x="322" y="94">🐙 GitHub</text>
              <path d="M306 89 L272 112" stroke="#1677ff" stroke-opacity=".5" stroke-width="1.5"/></g>
            <g><rect x="60" y="214" width="86" height="34" rx="8" fill="#fff" stroke="#e5e6eb"/><text x="76" y="236">📄 Gist</text>
              <path d="M146 231 L208 202" stroke="#1677ff" stroke-opacity=".5" stroke-width="1.5"/></g>
            <g><rect x="334" y="214" width="86" height="34" rx="8" fill="#fff" stroke="#e5e6eb"/><text x="350" y="236">🌐 网页</text>
              <path d="M334 231 L272 202" stroke="#1677ff" stroke-opacity=".5" stroke-width="1.5"/></g>
            <g><rect x="196" y="272" width="88" height="34" rx="8" fill="url(#lg2)" fill-opacity=".12" stroke="#b7eb8f"/><text x="212" y="294">✅ 本地化</text>
              <path d="M240 272 L240 202" stroke="#52c41a" stroke-opacity=".55" stroke-width="1.5"/></g>
          </g>
        </svg>
        <h2>订阅聚合 · 本地化管理</h2>
        <p>爬取源配置、任务编排、订阅与节点结果全部本地化管理，存储目标自由绑定。</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { message } from 'ant-design-vue';

import { useAuthStore } from '../stores/auth';

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const form = reactive({ username: 'admin', password: '' });
const remember = ref(true);
const loading = ref(false);

const onLogin = async () => {
  loading.value = true;
  try {
    await auth.login(form.username, form.password);
    message.success('登录成功');
    router.push(route.query.redirect || '/dashboard');
  } catch (error) {
    message.error(error.message || '登录失败');
  } finally {
    loading.value = false;
  }
};
</script>

<style scoped>
.vben-auth {
  display: flex;
  min-height: 100vh;
  position: relative;
  background: #fff;
  user-select: none;
}
/* 顶部 Logo */
.auth-logo {
  position: absolute;
  top: 0; left: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 24px;
}
.auth-logo .mark {
  width: 36px; height: 36px;
  border-radius: 9px;
  background: var(--primary);
  display: flex; align-items: center; justify-content: center;
  font-size: 18px;
}
.auth-logo p { margin: 0; font-size: 18px; font-weight: 600; color: var(--text-1); }
/* 左侧表单 */
.auth-form-side {
  width: min(460px, 42%);
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 48px 48px 24px;
  position: relative;
}
.auth-form-box { width: 100%; max-width: 340px; margin: 0 auto; }
.auth-title h1 { font-size: 26px; font-weight: 600; margin: 0 0 6px; letter-spacing: .2px; }
.auth-subtitle { font-size: 13px; color: var(--text-3); margin: 0 0 28px; }
.auth-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.vben-link { font-size: 13px; color: var(--primary); cursor: pointer; }
.vben-link:hover { color: var(--primary-hover); }
.auth-tip {
  margin-top: 22px;
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.9;
}
.auth-tip b { color: var(--text-2); }
.auth-copyright {
  position: absolute;
  bottom: 16px; left: 0; right: 0;
  text-align: center;
  font-size: 11px;
  color: rgba(0,0,0,.35);
}
/* 右侧介绍区 */
.auth-intro-side { flex: 1; position: relative; overflow: hidden; background: #f7f9fc; }
.login-background {
  position: absolute; inset: 0;
  background: linear-gradient(154deg, rgba(7,7,9,.08) 30%, rgba(22,119,255,.28) 48%, rgba(7,7,9,.08) 64%);
  filter: blur(100px);
}
.intro-content {
  position: relative;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  text-align: center;
}
.slogan { width: min(420px, 70%); height: auto; animation: float 5s ease-in-out infinite; }
@keyframes float { 0%,100% { transform: translateY(0) } 50% { transform: translateY(-10px) } }
.intro-content h2 { font-size: 24px; font-weight: 600; margin: 20px 0 10px; color: var(--text-1); }
.intro-content p { font-size: 14px; color: var(--text-2); max-width: 420px; margin: 0; line-height: 1.8; }
@media (max-width: 900px) {
  .auth-intro-side { display: none; }
  .auth-form-side { width: 100%; }
}
</style>
