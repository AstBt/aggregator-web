<template>
  <div class="login-wrap">
    <section class="brand">
      <div class="brand-logo"><span class="mark">🛰️</span><span>Aggregator 管理平台</span></div>
      <div class="brand-hero">
        <h1>订阅聚合 · <em>本地化管理</em></h1>
        <p>爬取源配置、任务编排、订阅与节点结果全部本地化管理，结果存储目标自由绑定。</p>
      </div>
      <div class="brand-foot">
        <span>Aggregator v2.4</span><span>前端: Vue Vben 设计语言</span><span>后端: FastAPI</span>
      </div>
    </section>
    <section class="login-panel">
      <h2>欢迎登录</h2>
      <p class="sub">管理员账号登录 · 不开放注册 · 未接入第三方登录</p>
      <a-form :model="form" layout="vertical" @finish="onLogin">
        <div class="form-item">
          <label><span style="color:var(--error)">*</span>用户名</label>
          <a-input v-model:value="form.username" size="large" placeholder="请输入管理员用户名" />
        </div>
        <div class="form-item">
          <label><span style="color:var(--error)">*</span>密码</label>
          <a-input-password v-model:value="form.password" size="large" placeholder="请输入密码" />
        </div>
        <div class="login-row">
          <a-checkbox v-model:checked="remember">记住我</a-checkbox>
        </div>
        <a-button type="primary" size="large" block html-type="submit" :loading="loading">登 录</a-button>
      </a-form>
      <div class="login-tip">
        演示环境：默认账号 <b>admin / admin123</b>（初始化命令可改）。<br>
        <b>安全策略：</b>密码 bcrypt 哈希存储；连续 5 次失败锁定 15 分钟；会话有效期 12 小时；系统<b>无注册功能</b>。
      </div>
    </section>
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
.login-wrap{display:flex;min-height:100vh}
</style>
