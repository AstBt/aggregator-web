<template>
  <div>
    <div class="callout blue">👥 系统<b>不开放注册、不提供第三方登录</b>；账号仅能由管理员在此创建。用户禁用后其登录态将在 60 秒内失效。</div>

    <div class="card">
      <div class="card-hd">
        <h3>用户</h3>
        <div style="display:flex;gap:8px">
          <a-select v-model:value="roleFilter" style="width:120px" placeholder="全部角色" allowClear @change="load" size="small">
            <a-select-option value="admin">管理员</a-select-option><a-select-option value="operator">操作员</a-select-option><a-select-option value="viewer">只读</a-select-option>
          </a-select>
          <a-button type="primary" size="small" @click="openCreate">＋ 创建用户</a-button>
        </div>
      </div>
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr><th>用户</th><th>角色</th><th>状态</th><th>最近登录</th><th>创建时间</th><th style="width:170px">操作</th></tr></thead>
          <tbody>
            <tr v-for="u in rows" :key="u.id">
              <td>
                <div class="u-name">
                  <span class="avatar" :class="u.role === 'admin' ? '' : u.role === 'operator' ? 'op' : 'vw'">{{ u.username[0].toUpperCase() }}</span>
                  <div><b>{{ u.username }}</b><span v-if="u.username === auth.user?.username" class="tag info plain" style="margin-left:4px">当前登录</span></div>
                </div>
              </td>
              <td><span class="role-tag" :class="u.role">{{ roleLabel(u.role) }}</span></td>
              <td><span class="switch" :class="{ on: u.enable }" @click="onToggle(u)"></span></td>
              <td class="muted">{{ fmt(u.last_login_at) }}</td>
              <td class="muted">{{ fmt(u.created_at) }}</td>
              <td class="acts">
                <a class="btn link" @click="openReset(u)">重置密码</a>
                <a v-if="u.username !== auth.user?.username" class="btn link" style="color:var(--error)" @click="onRemove(u)">删除</a>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <div class="card-hd"><h3>角色权限矩阵</h3><span class="extra">服务端按此矩阵强校验，前端仅做展示优化</span></div>
      <div class="tbl-wrap">
        <table class="tbl perm-matrix">
          <thead><tr><th>功能模块</th><th>👑 管理员 admin</th><th>🛠 操作员 operator</th><th>👁 只读 viewer</th></tr></thead>
          <tbody>
            <tr><td>仪表盘 / 查看结果</td><td class="yes">✓</td><td class="yes">✓</td><td class="yes">✓</td></tr>
            <tr><td>爬取源配置（增删改）</td><td class="yes">✓</td><td class="yes">✓</td><td class="no">—</td></tr>
            <tr><td>爬取 / 验活参数</td><td class="yes">✓</td><td class="yes">✓</td><td class="no">—</td></tr>
            <tr><td>任务创建 / 取消</td><td class="yes">✓</td><td class="yes">✓</td><td class="no">—</td></tr>
            <tr><td>节点导出 / 产物下载</td><td class="yes">✓</td><td class="yes">✓</td><td class="yes">✓</td></tr>
            <tr><td>存储目标编辑 / 启停</td><td class="yes">✓</td><td class="no">—</td><td class="no">—</td></tr>
            <tr><td>用户管理</td><td class="yes">✓</td><td class="no">—</td><td class="no">—</td></tr>
            <tr><td>系统设置 / 密码</td><td class="yes">✓</td><td class="yes">✓</td><td class="yes">✓</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <a-modal v-model:open="modalOpen" title="创建用户" width="520px" @ok="onCreate" ok-text="创建">
      <div class="callout gray">账号创建后首次登录无需改密；建议为不同岗位分配<b>操作员 / 只读</b>角色，遵循最小权限原则。</div>
      <div class="form-item"><label><span style="color:var(--error)">*</span>用户名</label><a-input v-model:value="form.username" placeholder="3-32 位字母、数字或下划线" /></div>
      <div class="form-item"><label><span style="color:var(--error)">*</span>初始密码</label><a-input-password v-model:value="form.password" placeholder="至少 8 位" /></div>
      <div class="form-item"><label>角色</label>
        <div class="radio-cards c3">
          <div class="radio-card" :class="{ sel: form.role === 'admin' }" @click="form.role = 'admin'"><h5>👑 管理员</h5><p>全部权限</p></div>
          <div class="radio-card" :class="{ sel: form.role === 'operator' }" @click="form.role = 'operator'"><h5>🛠 操作员</h5><p>源/参数/任务</p></div>
          <div class="radio-card" :class="{ sel: form.role === 'viewer' }" @click="form.role = 'viewer'"><h5>👁 只读</h5><p>仅查看</p></div>
        </div>
      </div>
      <div class="sw-row" style="margin-top:6px"><a-switch v-model:checked="form.enable" /><span style="font-size:13px">创建后立即启用</span></div>
    </a-modal>

    <a-modal v-model:open="resetOpen" title="重置密码" width="440px" @ok="onReset" ok-text="重置">
      <div class="form-item"><label>新密码</label><a-input-password v-model:value="resetPassword" placeholder="至少 8 位" /></div>
    </a-modal>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { Modal, message } from 'ant-design-vue';

import { users as usersApi } from '../api';
import { useAuthStore } from '../stores/auth';

const auth = useAuthStore();
const rows = ref([]);
const roleFilter = ref(undefined);
const modalOpen = ref(false);
const resetOpen = ref(false);
const resetPassword = ref('');
const resetTarget = ref(null);
const form = reactive({ username: '', password: '', role: 'viewer', enable: true });

const roleLabel = (r) => ({ admin: '管理员', operator: '操作员', viewer: '只读' }[r] || r);
const fmt = (iso) => (iso ? iso.replace('T', ' ').slice(0, 16) : '—');

async function load() {
  const data = await usersApi.list(roleFilter.value ? { role: roleFilter.value } : {});
  rows.value = data.items;
}
onMounted(load);

function openCreate() { Object.assign(form, { username: '', password: '', role: 'viewer', enable: true }); modalOpen.value = true; }
async function onCreate() {
  try { await usersApi.create(form); message.success('用户创建成功'); modalOpen.value = false; await load(); }
  catch (error) { message.error(error.message); }
}
async function onToggle(u) {
  try { await usersApi.update(u.id, { enable: !u.enable }); await load(); }
  catch (error) { message.error(error.message); }
}
async function onRemove(u) {
  Modal.confirm({ title: `确认删除用户 ${u.username}？`, content: '删除后该用户立即无法登录，操作不可恢复。', okType: 'danger',
    onOk: async () => { await usersApi.remove(u.id); message.success('已删除'); await load(); } });
}
function openReset(u) { resetTarget.value = u; resetPassword.value = ''; resetOpen.value = true; }
async function onReset() {
  try { await usersApi.update(resetTarget.value.id, { password: resetPassword.value }); message.success('密码已重置'); resetOpen.value = false; }
  catch (error) { message.error(error.message); }
}
</script>
