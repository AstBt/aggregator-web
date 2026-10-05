<template>
  <div>
    <div class="callout blue">🔧 系统设置。爬取规则前往<a href="#" @click.prevent="$router.push('/crawl-params')">「爬取参数」</a>，验活参数前往<a href="#" @click.prevent="$router.push('/alive-params')">「验活参数」</a>，结果写入目标前往<a href="#" @click.prevent="$router.push('/storage')">「结果存储」</a>，账号权限前往<a href="#" @click.prevent="$router.push('/users')">「用户管理」</a>。</div>

    <div class="card">
      <div class="card-hd"><h3>我的账号</h3></div>
      <div class="form-grid">
        <div class="form-item"><label>用户名</label><a-input :value="auth.user?.username" disabled /></div>
        <div class="form-item"><label>角色</label><a-input :value="roleLabel" disabled /></div>
      </div>
    </div>

    <div class="card" v-if="auth.atLeast('admin')">
      <div class="card-hd"><h3>公告提醒</h3><span class="extra">启用后展示在页面右上角铃铛左侧，滚动展现</span></div>
      <div class="callout gray" style="margin-bottom:14px">向所有登录用户展示一条滚动公告（如维护通知）；点击顶栏公告可暂停滚动。</div>
      <div class="form-item full">
        <label>公告内容 <span class="hint">最多 500 字，留空并停用时 hides</span></label>
        <a-textarea v-model:value="annForm.text" :rows="3" :maxlength="500" show-count placeholder="例：系统将于今晚 23:00 升级维护，届时任务将暂停执行" />
      </div>
      <div class="sw-row" style="margin-bottom:14px">
        <a-switch v-model:checked="annForm.enable" />
        <span style="font-size:13px">启用公告</span>
      </div>
      <a-button type="primary" :loading="annSaving" @click="onSaveAnnouncement">保存公告</a-button>
    </div>

    <div class="card">
      <div class="card-hd"><h3>修改密码</h3></div>
      <div class="callout warn">🔒 密码采用 bcrypt 哈希存储；修改后当前账号在其他设备的登录会话将全部失效。</div>
      <div class="form-grid">
        <div class="form-item"><label>原密码</label><a-input-password v-model:value="form.old_password" /></div>
        <div class="form-item"></div>
        <div class="form-item"><label>新密码</label><a-input-password v-model:value="form.new_password" placeholder="至少 8 位" /></div>
        <div class="form-item"><label>确认新密码</label><a-input-password v-model:value="form.confirm" /></div>
      </div>
      <a-button type="primary" @click="onSubmit">修改密码</a-button>
    </div>

    <div class="card">
      <div class="card-hd"><h3>关于</h3></div>
      <div class="form-grid">
        <div class="kv-row"><span class="k" style="width:130px">产品名称</span><span>Aggregator Web 管理平台</span></div>
        <div class="kv-row"><span class="k" style="width:130px">版本</span><span>v2.4-web</span></div>
        <div class="kv-row"><span class="k" style="width:130px">前端</span><span>Vue 3 + Vue Vben 设计语言</span></div>
        <div class="kv-row"><span class="k" style="width:130px">后端</span><span>FastAPI + SQLAlchemy 2.x</span></div>
        <div class="kv-row"><span class="k" style="width:130px">聚合引擎</span><span>subscribe/（复用现有 Python 实现）</span></div>
        <div class="kv-row"><span class="k" style="width:130px">需求文档</span><span><a href="/docs/2026-10-04/PRD.md" target="_blank">PRD.md</a> · <a href="/docs/2026-10-04/prototypes/index.html" target="_blank">原型索引</a></span></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { message } from 'ant-design-vue';

import { announcement as announcementApi, auth as authApi } from '../api';
import { useAuthStore } from '../stores/auth';

const auth = useAuthStore();
const router = useRouter();
const roleLabel = computed(() => ({ admin: '管理员（admin）', operator: '操作员（operator）', viewer: '只读（viewer）' }[auth.role]));
const form = reactive({ old_password: '', new_password: '', confirm: '' });
const annForm = reactive({ text: '', enable: false });
const annSaving = ref(false);

onMounted(async () => {
  if (!auth.atLeast('admin')) return;
  try {
    const data = await announcementApi.read();
    Object.assign(annForm, data);
  } catch { /* ignore */ }
});

async function onSaveAnnouncement() {
  annSaving.value = true;
  try {
    await announcementApi.save({ text: annForm.text, enable: annForm.enable });
    message.success('公告已保存');
  } catch (error) {
    message.error(error.message);
  } finally {
    annSaving.value = false;
  }
}

const onSubmit = async () => {
  if (form.new_password !== form.confirm) return message.error('两次输入的新密码不一致');
  if (form.new_password.length < 8) return message.error('新密码至少 8 位');
  try {
    await authApi.changePassword({ old_password: form.old_password, new_password: form.new_password });
    message.success('密码已修改，请重新登录');
    await auth.logout();
    router.push('/login');
  } catch (error) {
    message.error(error.message);
  }
};
</script>
