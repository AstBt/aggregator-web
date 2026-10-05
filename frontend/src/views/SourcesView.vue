<template>
  <div>
    <div class="callout gray" style="margin-bottom:16px">
      🧩 本页仅维护<b>爬取源信息</b>；全局规则与代理前往<a href="#" @click.prevent="$router.push('/crawl-params')">「爬取参数」</a>；验活相关在<a href="#" @click.prevent="$router.push('/alive-params')">「验活参数」</a>；结果写入位置由创建任务时绑定的存储目标决定。
    </div>
    <div class="card">
      <div class="card-hd">
        <h3>爬取源</h3>
        <div style="display:flex;gap:8px">
          <a-button size="small" @click="openImport">⤒ 导入</a-button>
          <a-button size="small" @click="onExport">⤓ 导出</a-button>
          <a-button type="primary" size="small" @click="openCreate">＋ 新建源</a-button>
        </div>
      </div>
      <div class="tabs">
        <div v-for="tab in tabs" :key="tab.key" class="tab" :class="{ active: filter === tab.key }" @click="filter = tab.key">
          {{ tab.label }}<span class="cnt">{{ tab.count }}</span>
        </div>
      </div>
      <div class="tbl-wrap" style="margin-top:14px">
        <table class="tbl">
          <thead><tr><th>名称</th><th>类型</th><th>配置摘要</th><th>启用</th><th style="width:240px">操作</th></tr></thead>
          <tbody>
            <tr v-for="s in filtered" :key="s.id">
              <td><b>{{ s.name }}</b></td>
              <td>
                <span class="tag plain" :class="typeTagClass(s.type)">
                  <span class="src-type-ico" :style="{ background: typeBg(s.type) }">{{ typeIcon(s.type) }}</span>{{ typeLabel(s.type) }}
                </span>
              </td>
              <td class="kv">{{ summary(s) }}</td>
              <td><span class="switch" :class="{ on: s.enable }" @click="onToggle(s)"></span></td>
              <td class="acts">
                <TestConnButton v-if="s.type === 'page'" :on-run="() => test(s.id)" />
                <a class="btn link" @click="openEdit(s)">编辑</a>
                <a class="btn link" style="color:var(--error)" @click="onRemove(s)">删除</a>
              </td>
            </tr>
            <tr v-if="!filtered.length"><td colspan="5" class="empty-tip">该类型下暂无源</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 新建/编辑弹窗：Schema 驱动动态表单 -->
    <a-modal v-model:open="modalOpen" :title="editing ? `编辑源 · ${form.name}` : '新建爬取源'" width="720px" @ok="onSave" ok-text="保存" :confirm-loading="saving">
      <div style="margin-bottom:14px">
        <label style="font-size:13px;color:var(--text-2)">选择源类型</label>
        <div class="radio-cards" style="margin-top:8px">
          <div v-for="(meta, key) in schemas" :key="key" class="radio-card" :class="{ sel: form.type === key }" @click="form.type = key">
            <h5>{{ meta.icon }} {{ meta.label }}</h5><p>{{ fieldsOf(key)[0]?.hint || '' }}</p>
          </div>
        </div>
      </div>
      <div class="form-grid" v-if="currentSchema">
        <!-- 标识字段：telegram=频道名，其他=源名称 -->
        <div class="form-item">
          <label><span style="color:var(--error)">*</span>{{ currentSchema.identity_label }}</label>
          <a-input v-model:value="form.name" :disabled="!!editing" :placeholder="currentSchema.identity === 'channel' ? '例: oneclickvpnkeys（不带 @）' : '例: my-source'" />
        </div>
        <!-- 动态字段 -->
        <template v-for="field in fieldsOf(form.type)" :key="field.key">
          <div class="form-item" v-if="fieldVisible(field)">
            <label>
              <span v-if="fieldRequired(field)" style="color:var(--error)">*</span>{{ field.label }}
              <a-tooltip :title="field.hint"><QuestionCircleOutlined style="color:var(--text-3);margin-left:4px" /></a-tooltip>
            </label>
            <a-input-number v-if="field.type === 'int'" v-model:value="configForm[field.key]" style="width:100%" :placeholder="field.example" />
            <a-switch v-else-if="field.type === 'bool'" v-model:checked="configForm[field.key]" />
            <a-select v-else-if="field.type === 'enum'" v-model:value="configForm[field.key]" :options="(field.options || []).map((o) => ({ value: o }))" :placeholder="field.example" />
            <a-input-password v-else-if="field.type === 'password'" v-model:value="configForm[field.key]" :placeholder="field.example" />
            <a-textarea v-else-if="field.type === 'list'" v-model:value="listForm[field.key]" :rows="Math.max(2, listLines(field.key).length)" :placeholder="'每行一条，例: ' + field.example" />
            <div v-else-if="field.type === 'kv'" class="kv-editor">
              <div v-for="(pair, i) in kvLines(field.key)" :key="i" class="kv-row-edit">
                <a-input v-model:value="pair.k" placeholder="Key" style="flex:1" />
                <a-input v-model:value="pair.v" :placeholder="'例: ' + field.example" style="flex:2" />
                <a @click="removeKv(field.key, i)" style="color:var(--error)">－</a>
              </div>
              <a @click="addKv(field.key)" class="btn link">＋ 添加一项</a>
            </div>
            <a-input v-else v-model:value="configForm[field.key]" :class="{ bad: formError }" :placeholder="field.example" />
          </div>
        </template>
        <div class="form-item full" v-if="formError">
          <div class="err-msg show">{{ formError }}</div>
        </div>
      </div>
    </a-modal>

    <!-- 导入弹窗 -->
    <a-modal v-model:open="importOpen" title="导入爬取源" width="560px" @ok="onImport" ok-text="导入">
      <div class="callout blue" style="margin-bottom:14px">支持从 my-config.json 的 crawl 节粘贴导入；字段将按 Schema 归一化，push_to 等分组残留字段静默丢弃，同名源合并而非覆盖。</div>
      <a-textarea v-model:value="importText" :rows="8" placeholder='{"telegram": {"channels": {...}}} 或 {"telegram": [{"name": "...", "config": {...}}]}' />
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { Modal, message } from 'ant-design-vue';
import { QuestionCircleOutlined } from '@ant-design/icons-vue';

import { sources as sourcesApi } from '../api';
import TestConnButton from '../components/TestConnButton.vue';

const rows = ref([]);
const schemas = ref({});
const filter = ref('all');
const modalOpen = ref(false);
const importOpen = ref(false);
const importText = ref('');
const editing = ref(null);
const saving = ref(false);
const formError = ref('');
const form = reactive({ type: 'telegram', name: '' });
const configForm = reactive({});   // 标量字段
const listForm = reactive({});     // list 字段（多行文本）
const kvForm = reactive({});       // kv 字段（[{k,v}]）

const TYPE_TAG = { telegram: 'info', github: 'ok', gist: 'ok', google: 'warn', yandex: 'warn', page: 'purple', repo: 'ok', script: 'err' };
const TYPE_BG = { telegram: '#e6f4ff', github: '#f6ffed', gist: '#f6ffed', google: '#fff7e6', yandex: '#fff7e6', page: '#f9f0ff', repo: '#f6ffed', script: '#fff2f0' };

const currentSchema = computed(() => schemas.value[form.type] || null);
const fieldsOf = (type) => schemas.value[type]?.fields || [];
const typeIcon = (t) => schemas.value[t]?.icon || '🧩';
const typeLabel = (t) => schemas.value[t]?.label || t;
const typeTagClass = (t) => TYPE_TAG[t] || 'gray';
const typeBg = (t) => TYPE_BG[t] || '#f5f5f5';

const tabs = computed(() => [
  { key: 'all', label: '全部', count: rows.value.length },
  ...Object.keys(schemas.value)
    .filter((t) => rows.value.some((r) => r.type === t))
    .map((t) => ({ key: t, label: `${typeIcon(t)} ${typeLabel(t)}`, count: rows.value.filter((r) => r.type === t).length })),
]);
const filtered = computed(() => (filter.value === 'all' ? rows.value : rows.value.filter((r) => r.type === filter.value)));

const fieldVisible = (field) => {
  const depends = field.depends || {};
  return Object.entries(depends).every(([k, v]) => configForm[k] === v);
};
const fieldRequired = (field) => {
  if (field.required) return true;
  return Object.entries(field.required_when || {}).every(([k, v]) => configForm[k] === v);
};

function listLines(key) { return String(listForm[key] || '').split('\n'); }
function kvLines(key) { return kvForm[key] || []; }
function addKv(key) { (kvForm[key] ||= []).push({ k: '', v: '' }); }
function removeKv(key, i) { kvForm[key].splice(i, 1); }

function resetForm() {
  Object.keys(configForm).forEach((k) => delete configForm[k]);
  Object.keys(listForm).forEach((k) => delete listForm[k]);
  Object.keys(kvForm).forEach((k) => delete kvForm[k]);
  form.name = '';
  formError.value = '';
}

function loadConfigIntoForm(type, config) {
  resetForm();
  for (const field of fieldsOf(type)) {
    const value = config?.[field.key];
    if (field.type === 'list') listForm[field.key] = Array.isArray(value) ? value.join('\n') : (value || '');
    else if (field.type === 'kv') kvForm[field.key] = Object.entries(value || {}).map(([k, v]) => ({ k, v: String(v) }));
    else if (field.type === 'bool') configForm[field.key] = !!value;
    else configForm[field.key] = value ?? field.default ?? '';
  }
}

function buildConfig() {
  const config = {};
  for (const field of fieldsOf(form.type)) {
    if (!fieldVisible(field)) continue;
    if (field.type === 'list') {
      config[field.key] = listLines(field.key).map((l) => l.trim()).filter(Boolean);
    } else if (field.type === 'kv') {
      config[field.key] = Object.fromEntries(kvLines(field.key).filter((p) => p.k.trim()).map((p) => [p.k.trim(), p.v]));
    } else if (field.type === 'bool') {
      config[field.key] = !!configForm[field.key];
    } else if (field.type === 'int') {
      config[field.key] = Number(configForm[field.key] || 0);
    } else {
      config[field.key] = (configForm[field.key] || '').trim();
    }
  }
  return config;
}

async function load() {
  const [list, schema] = await Promise.all([sourcesApi.list({ page_size: 200 }), sourcesApi.schema()]);
  rows.value = list.items;
  schemas.value = schema.schemas;
}
onMounted(load);

function openCreate() {
  resetForm();
  form.type = 'telegram';
  loadConfigIntoForm('telegram', {});
  editing.value = null;
  modalOpen.value = true;
}
function openEdit(s) {
  form.type = s.type;
  loadConfigIntoForm(s.type, s.config || {});
  form.name = s.name;
  editing.value = s;
  modalOpen.value = true;
}
async function onSave() {
  saving.value = true;
  formError.value = '';
  try {
    const config = buildConfig();
    if (editing.value) {
      await sourcesApi.update(editing.value.id, { config });
      message.success('已保存');
    } else {
      await sourcesApi.create({ type: form.type, name: form.name, config });
      message.success('源已创建');
    }
    modalOpen.value = false;
    await load();
  } catch (error) {
    formError.value = error.message;
  } finally {
    saving.value = false;
  }
}
async function onToggle(s) { await sourcesApi.toggle(s.id); await load(); }
async function onRemove(s) {
  Modal.confirm({
    title: `确认删除爬取源 ${s.name}？`, content: '其历史贡献记录将保留。', okType: 'danger',
    onOk: async () => { await sourcesApi.remove(s.id); message.success('已删除'); await load(); },
  });
}
const test = (id) => sourcesApi.test(id);
async function onExport() {
  const payload = await sourcesApi.export();
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'sources.json'; a.click();
  URL.revokeObjectURL(url);
}
async function onImport() {
  try {
    const result = await sourcesApi.import(JSON.parse(importText.value));
    message.success(`导入完成 · 新增 ${result.created} · 合并 ${result.merged}`);
    importOpen.value = false;
    await load();
  } catch (error) {
    message.error('JSON 解析或导入失败: ' + error.message);
  }
}

const summary = (s) => {
  const c = s.config || {};
  if (s.type === 'telegram') return `pages=<b>${c.pages ?? '-'}</b>${c.rename ? ' · rename=<b>' + c.rename + '</b>' : ''}`;
  if (s.type === 'page') return `url=<b>${(c.url || []).length}</b> 个${c.paged ? ' · 分页 ' + c.start + '-' + c.end : ''}`;
  if (s.type === 'gist') return `mode=<b>${c.mode || 'timeline'}</b> · max_gists=<b>${c.max_gists ?? '-'}</b>`;
  if (s.type === 'github') return `pages=<b>${c.pages ?? '-'}</b> · 凭证: <b>${c.token ? 'Token' : c.cookie ? 'Cookie' : '未配置'}</b>`;
  const first = Object.entries(c)[0];
  return first ? `${first[0]}=<b>${Array.isArray(first[1]) ? first[1].length + ' 项' : first[1]}</b>` : '默认参数';
};
</script>

<style scoped>
.src-type-ico{width:20px;height:20px;border-radius:5px;display:inline-flex;align-items:center;justify-content:center;font-size:11px;vertical-align:-4px;margin-right:4px}
.kv-editor{border:1px solid var(--border);border-radius:8px;padding:10px}
.kv-row-edit{display:flex;gap:8px;align-items:center;margin-bottom:8px}
.kv-row-edit a{padding:0 6px}
</style>
