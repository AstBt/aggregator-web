<template>
  <div>
    <div class="callout blue">
      💾 管理所有<b>存储目标</b>（本地目录与 Gist 等远端后端一视同仁，可创建多个、自由启停）。目标是纯发布出口——每轮任务往哪写，由<b>创建任务时绑定的目标</b>决定；旧数据（订阅池 / remains）只从系统库读取，与目标无关。token 类凭证加密保存，界面仅显示掩码。
    </div>

    <div class="card">
      <div class="card-hd">
        <h3>存储目标</h3>
        <a-button v-if="auth.atLeast('admin')" type="primary" size="small" @click="openCreate">＋ 添加存储目标</a-button>
        <span v-else class="muted" style="font-size:12px">只读（仅管理员可管理）</span>
      </div>
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr><th>名称</th><th>类型</th><th>目标摘要</th><th>凭证</th><th>启用</th><th>最近写入</th><th style="width:230px">操作</th></tr></thead>
          <tbody>
            <tr v-for="t in rows" :key="t.id">
              <td><b>{{ t.name }}</b></td>
              <td><span class="tgt-type"><span class="tgt-ico" :style="{ background: t.type === 'local' ? '#e6f4ff' : '#f6ffed' }">{{ t.type === 'local' ? '📁' : '🐙' }}</span>{{ t.type_name }}</span></td>
              <td class="mono" style="font-size:11.5px;max-width:280px;overflow:hidden;text-overflow:ellipsis">{{ summary(t) }}</td>
              <td><span v-if="t.token_masked" class="mask">{{ t.token_masked }}</span><span v-else class="muted">无需凭证</span></td>
              <td><span class="switch" :class="{ on: t.enable }" @click="onToggle(t)"></span></td>
              <td><span class="tag" :class="t.last_write_ok ? 'ok' : t.last_write_ok === false ? 'err' : 'gray'">{{ writeLabel(t) }}</span></td>
              <td class="acts">
                <TestConnButton :on-run="() => test(t.id)" />
                <a v-if="auth.atLeast('admin')" class="btn link" @click="openEdit(t)">编辑</a>
                <a v-if="auth.atLeast('admin')" class="btn link" style="color:var(--error)" @click="onRemove(t)">删除</a>
              </td>
            </tr>
            <tr v-if="!rows.length"><td colspan="7" class="empty-tip">暂无存储目标</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <div class="card-hd"><h3>数据如何流转</h3><router-link class="btn link" to="/tasks">去创建任务 →</router-link></div>
      <div class="bars" style="gap:14px">
        <div class="bar-row" style="grid-template-columns:170px 1fr"><span class="muted">🗄 系统库（权威源）</span><div style="font-size:12.5px;color:var(--text-2);line-height:1.7">订阅与存活节点记录的唯一权威源。订阅池 = 上轮 full/回测存活节点的来源订阅（实时派生）；remains = 上轮存活节点。</div></div>
        <div class="bar-row" style="grid-template-columns:170px 1fr"><span class="muted">🕷️ 仅爬取</span><div style="font-size:12.5px;color:var(--text-2);line-height:1.7">爬取并验证订阅 → 只入系统库供浏览；<b>不绑定</b>存储目标，不发布、不改变订阅池与 remains。</div></div>
        <div class="bar-row" style="grid-template-columns:170px 1fr"><span class="muted">🧬 回测</span><div style="font-size:12.5px;color:var(--text-2);line-height:1.7">不爬取；从<b>系统库</b>读上轮订阅池与 remains → 重新拉取 → 验活 → 产物写入绑定目标。</div></div>
        <div class="bar-row" style="grid-template-columns:170px 1fr"><span class="muted">⚡ 爬取+聚合</span><div style="font-size:12.5px;color:var(--text-2);line-height:1.7">爬取新订阅 → 与系统库订阅池、remains 合并 → 验活 → 转换 → 写入绑定目标。</div></div>
        <div class="bar-row" style="grid-template-columns:170px 1fr"><span class="muted">📤 绑定目标（发布）</span><div style="font-size:12.5px;color:var(--text-2);line-height:1.7">纯发布出口，不作数据源。绑定多目标时产物分别完整写入每个目标；发布<b>准原子</b>——全部写成功任务才置成功，中断/部分失败后可在任务详情「重试发布」补偿重放。</div></div>
      </div>
    </div>

    <!-- 新建/编辑弹窗 -->
    <a-modal v-model:open="modalOpen" :title="editing ? `编辑存储目标 · ${form.name}` : '添加存储目标'" width="640px" @ok="onSave" ok-text="保存">
      <div v-if="!editing">
        <label style="font-size:13px;color:var(--text-2)">目标类型</label>
        <div class="radio-cards c3" style="margin:8px 0 16px">
          <div v-for="(meta, key) in TYPES" :key="key" class="radio-card" :class="{ sel: form.type === key }" @click="form.type = key">
            <h5>{{ key === 'local' ? '📁' : '📋' }} {{ meta.name }}</h5><p>{{ key === 'local' ? '可创建多个，与其他目标同等管理' : '远端分享平台' }}</p>
          </div>
        </div>
      </div>
      <div class="form-grid">
        <div class="form-item" v-if="!editing"><label><span style="color:var(--error)">*</span>名称</label><a-input v-model:value="form.name" /></div>
        <template v-if="form.type === 'local'">
          <div class="form-item full"><label><span style="color:var(--error)">*</span>数据目录</label><a-input v-model:value="form.dir" placeholder="例如 D:\data\local" /></div>
          <div class="form-item"><label>快照保留份数</label><a-input-number v-model:value="form.keep" :min="1" style="width:100%" /></div>
        </template>
        <template v-else>
          <div class="form-item"><label><span style="color:var(--error)">*</span>{{ form.type === 'gist' ? 'Gist ID' : '服务地址' }}</label><a-input v-model:value="form.key" /></div>
          <div class="form-item"><label><span style="color:var(--error)">*</span>访问令牌</label><a-input-password v-model:value="form.token" placeholder="加密保存，不回显" /></div>
        </template>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { Modal, message } from 'ant-design-vue';

import { storage as storageApi } from '../api';
import { useAuthStore } from '../stores/auth';
import TestConnButton from '../components/TestConnButton.vue';

const auth = useAuthStore();
const TYPES = { local: { name: '本地目录' }, gist: { name: 'GitHub Gist' }, pastegg: { name: 'PasteGG' }, pastefy: { name: 'Pastefy' }, imperial: { name: 'Imperial' }, qbin: { name: 'QBin' } };
const rows = ref([]);
const modalOpen = ref(false);
const editing = ref(null);
const form = reactive(blank());

function blank() { return { type: 'local', name: '', dir: '', keep: 5, key: '', token: '' }; }

const summary = (t) => (t.type === 'local' ? t.config?.dir : `${t.config?.gist_id || t.config?.base || ''}`);
const writeLabel = (t) => (t.last_write_at ? `${t.last_write_at.replace('T', ' ').slice(5, 16)} · ${t.last_write_ok ? '成功' : '失败'}` : '未写入');

async function load() { rows.value = (await storageApi.list()).items; }
onMounted(load);

function openCreate() { Object.assign(form, blank()); editing.value = null; modalOpen.value = true; }
function openEdit(t) {
  Object.assign(form, blank(), { type: t.type, name: t.name, dir: t.config?.dir || '', keep: t.config?.keep ?? 5, key: t.config?.gist_id || t.config?.base || '', token: '' });
  editing.value = t;
  modalOpen.value = true;
}
function buildBody() {
  if (form.type === 'local') return { type: form.type, name: form.name, config: { dir: form.dir, keep: form.keep }, token: '' };
  return { type: form.type, name: form.name, config: form.type === 'gist' ? { gist_id: form.key } : { base: form.key }, token: form.token };
}
async function onSave() {
  try {
    if (editing.value) await storageApi.update(editing.value.id, buildBody());
    else await storageApi.create(buildBody());
    message.success('已保存');
    modalOpen.value = false;
    await load();
  } catch (error) { message.error(error.message); }
}
async function onToggle(t) { await storageApi.toggle(t.id); await load(); }
async function onRemove(t) {
  Modal.confirm({ title: `确认删除存储目标 ${t.name}？`, content: '删除后不再向该目标写入，历史文件不会清理；引用它的定时任务将被停用。', okType: 'danger',
    onOk: async () => { await storageApi.remove(t.id); message.success('已删除'); await load(); } });
}
const test = (id) => storageApi.test(id);
</script>
