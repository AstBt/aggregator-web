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
      <div class="tabs" id="srcTabs">
        <div v-for="tab in tabs" :key="tab.key" class="tab" :class="{ active: filter === tab.key }" @click="filter = tab.key">
          {{ tab.label }}<span class="cnt">{{ tab.count }}</span>
        </div>
      </div>
      <div class="tbl-wrap" style="margin-top:14px">
        <table class="tbl">
          <thead><tr><th>名称</th><th>类型</th><th>配置摘要</th><th>启用</th><th style="width:230px">操作</th></tr></thead>
          <tbody>
            <tr v-for="s in filtered" :key="s.id">
              <td><b>{{ s.name }}</b></td>
              <td><span class="tag plain" :class="typeTagClass(s.type)"><span class="src-type-ico" :style="{ background: typeBg(s.type) }">{{ typeIcon(s.type) }}</span>{{ typeLabel(s.type) }}</span></td>
              <td class="kv">{{ summary(s) }}</td>
              <td><span class="switch" :class="{ on: s.enable }" @click="onToggle(s)"></span></td>
              <td class="acts">
                <TestConnButton :on-run="() => test(s.id)" label="测试连接" />
                <a class="btn link" @click="openEdit(s)">编辑</a>
                <a class="btn link" style="color:var(--error)" @click="onRemove(s)">删除</a>
              </td>
            </tr>
            <tr v-if="!filtered.length"><td colspan="5" class="empty-tip">该类型下暂无源</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 新建/编辑弹窗 -->
    <a-modal v-model:open="modalOpen" :title="editing ? `编辑源 · ${form.name}` : '新建爬取源'" width="720px" @ok="onSave" ok-text="保存">
      <div style="margin-bottom:14px">
        <label style="font-size:13px;color:var(--text-2)">选择源类型</label>
        <div class="radio-cards" style="margin-top:8px">
          <div v-for="t in SOURCE_TYPES" :key="t.key" class="radio-card" :class="{ sel: form.type === t.key }" @click="form.type = t.key">
            <h5>{{ t.icon }} {{ t.label }}</h5><p>{{ t.hint }}</p>
          </div>
        </div>
      </div>
      <div class="form-grid">
        <div class="form-item">
          <label><span style="color:var(--error)">*</span>名称</label>
          <a-input v-model:value="form.name" :disabled="!!editing" placeholder="源名称（频道名/自定义）" />
        </div>
        <div class="form-item" v-if="['telegram','github','gist','google','yandex','repo'].includes(form.type)">
          <label>{{ numericLabel[form.type] || 'pages' }} <span class="hint">数值范围见提示</span></label>
          <a-input-number v-model:value="form.numeric" style="width:100%" />
        </div>
        <div class="form-item" v-if="form.type === 'page'">
          <label><span style="color:var(--error)">*</span>URL 列表 <span class="hint">每行一条</span></label>
          <a-textarea v-model:value="form.urls" :rows="4" placeholder="https://…" />
        </div>
        <div class="form-item" v-if="form.type === 'page'">
          <label>分页</label>
          <div style="display:flex;gap:8px;align-items:center">
            <a-switch v-model:checked="form.paged" />
            <a-input v-model:value="form.placeholder" placeholder="{page}" style="width:90px" :disabled="!form.paged" />
            <a-input-number v-model:value="form.start" :min="0" style="width:80px" :disabled="!form.paged" />
            <span class="muted">—</span>
            <a-input-number v-model:value="form.end" :min="0" style="width:80px" :disabled="!form.paged" />
          </div>
        </div>
        <div class="form-item" v-if="form.type === 'repo'">
          <label>username</label><a-input v-model:value="form.username" />
        </div>
        <div class="form-item" v-if="form.type === 'repo'">
          <label>repo</label><a-input v-model:value="form.repo" />
        </div>
        <div class="form-item" v-if="form.type === 'script'">
          <label><span style="color:var(--error)">*</span>plugin</label>
          <a-select v-model:value="form.plugin" :options="pluginOptions" show-search placeholder="选择插件" />
        </div>
        <div class="form-item">
          <label>包含正则 <span class="hint">include</span></label>
          <a-input v-model:value="form.include" :class="{ bad: !!formError }" />
          <div class="err-msg" :class="{ show: !!formError }">{{ formError }}</div>
        </div>
        <div class="form-item">
          <label>排除正则 <span class="hint">exclude</span></label>
          <a-input v-model:value="form.exclude" />
        </div>
      </div>
    </a-modal>

    <!-- 导入弹窗 -->
    <a-modal v-model:open="importOpen" title="导入爬取源" width="560px" @ok="onImport" ok-text="导入">
      <div class="callout blue" style="margin-bottom:14px">支持从 my-config.json 的 crawl 节粘贴导入；push_to 等分组残留字段将被静默丢弃，同名源合并而非覆盖。</div>
      <a-textarea v-model:value="importText" :rows="8" placeholder='{"telegram": {"channels": {...}}} 或 {"telegram": [{"name": "...", "config": {...}}]}' />
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { Modal, message } from 'ant-design-vue';

import { sources as sourcesApi } from '../api';
import TestConnButton from '../components/TestConnButton.vue';

const SOURCE_TYPES = [
  { key: 'telegram', label: 'Telegram 频道', icon: '📨', hint: '公共频道消息翻页爬取' },
  { key: 'github', label: 'GitHub 搜索', icon: '🐙', hint: '代码 / Issues 关键词检索' },
  { key: 'gist', label: 'Gist 时间线', icon: '📄', hint: '扫描公开 gist 内容' },
  { key: 'google', label: 'Google 搜索', icon: '🔍', hint: '搜索引擎检索' },
  { key: 'yandex', label: 'Yandex 搜索', icon: '🔎', hint: '搜索引擎检索' },
  { key: 'page', label: '通用网页', icon: '🌐', hint: '指定 URL 列表抓取提取' },
  { key: 'repo', label: 'GitHub 仓库', icon: '📦', hint: '监控仓库 commits' },
  { key: 'script', label: '脚本插件', icon: '🧪', hint: 'fofa / v2rayse 等插件' },
];
const TYPE_META = {
  telegram: ['📨', 'Telegram 频道', 'info'], github: ['🐙', 'GitHub 搜索', 'ok'], gist: ['📄', 'Gist 时间线', 'ok'],
  google: ['🔍', 'Google 搜索', 'warn'], yandex: ['🔎', 'Yandex 搜索', 'warn'], page: ['🌐', '通用网页', 'purple'],
  repo: ['📦', 'GitHub 仓库', 'ok'], script: ['🧪', '脚本插件', 'err'],
};
const NUMERIC = { telegram: ['pages', '翻页数'], github: ['pages', '搜索页数'], gist: ['max_gists', '扫描上限'], google: ['limit', '结果上限'], yandex: ['days', '天数'] };
const numericLabel = Object.fromEntries(Object.entries(NUMERIC).map(([k, v]) => [k, v[1]]));
const pluginOptions = ['fofa', 'v2rayse', 'v2rayfree', 'tempairport', 'scaner', 'gitforks', 'dynamic'];

const rows = ref([]);
const filter = ref('all');
const modalOpen = ref(false);
const importOpen = ref(false);
const importText = ref('');
const editing = ref(null);
const formError = ref('');
const form = reactive(blank());

function blank() {
  return { type: 'telegram', name: '', numeric: 5, urls: '', paged: false, placeholder: '{page}', start: 1, end: 5, username: '', repo: '', plugin: undefined, include: '', exclude: '' };
}

const tabs = computed(() => [
  { key: 'all', label: '全部', count: rows.value.length },
  ...Object.keys(TYPE_META)
    .filter((t) => rows.value.some((r) => r.type === t))
    .map((t) => ({ key: t, label: `${TYPE_META[t][0]} ${TYPE_META[t][1]}`, count: rows.value.filter((r) => r.type === t).length })),
]);
const filtered = computed(() => (filter.value === 'all' ? rows.value : rows.value.filter((r) => r.type === filter.value)));

const typeIcon = (t) => TYPE_META[t]?.[0] || '🧩';
const typeLabel = (t) => TYPE_META[t]?.[1] || t;
const typeTagClass = (t) => TYPE_META[t]?.[2] || 'gray';
const typeBg = (t) => ({ telegram: '#e6f4ff', github: '#f6ffed', gist: '#f6ffed', google: '#fff7e6', yandex: '#fff7e6', page: '#f9f0ff', repo: '#f6ffed', script: '#fff2f0' }[t] || '#f5f5f5');
const summary = (s) => {
  const c = s.config || {};
  if (s.type === 'page') return `url=<b>${(c.url || []).length}</b> 个${c.paged ? ' · 分页 ' + c.start + '-' + c.end : ''}`;
  const first = Object.entries(c)[0];
  return first ? `${first[0]}=<b>${Array.isArray(first[1]) ? first[1].length : first[1]}</b>` : '默认参数';
};

async function load() {
  rows.value = (await sourcesApi.list({ page_size: 200 })).items;
}
onMounted(load);

function openCreate() {
  Object.assign(form, blank());
  editing.value = null;
  formError.value = '';
  modalOpen.value = true;
}
function openEdit(s) {
  Object.assign(form, blank(), { type: s.type, name: s.name });
  const c = s.config || {};
  form.numeric = c[NUMERIC[s.type]?.[0]] ?? c.pages ?? c.limit ?? c.days ?? 5;
  form.urls = Array.isArray(c.url) ? c.url.join('\n') : c.url || '';
  form.paged = !!c.paged;
  form.placeholder = c.placeholder || '{page}';
  form.start = c.start ?? 1;
  form.end = c.end ?? 5;
  form.username = c.username || '';
  form.repo = c.repo || '';
  form.plugin = c.plugin;
  form.include = c.include || '';
  form.exclude = c.exclude || '';
  editing.value = s;
  modalOpen.value = true;
}

function buildConfig() {
  const config = {};
  if (form.type === 'page') {
    config.url = form.urls.split('\n').map((u) => u.trim()).filter(Boolean);
    if (form.paged) Object.assign(config, { paged: true, placeholder: form.placeholder, start: form.start, end: form.end });
  } else if (form.type === 'repo') {
    Object.assign(config, { username: form.username, repo: form.repo });
  } else if (form.type === 'script') {
    config.plugin = form.plugin;
  } else if (NUMERIC[form.type]) {
    config[NUMERIC[form.type][0]] = form.numeric;
  }
  if (form.include) config.include = form.include;
  if (form.exclude) config.exclude = form.exclude;
  return config;
}

async function onSave() {
  formError.value = '';
  const config = buildConfig();
  try {
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
    if (!formError.value) message.error(error.message);
  }
}

async function onToggle(s) {
  await sourcesApi.toggle(s.id);
  await load();
}
async function onRemove(s) {
  Modal.confirm({
    title: `确认删除爬取源 ${s.name}？`,
    content: '其历史贡献记录将保留。',
    okType: 'danger',
    onOk: async () => {
      await sourcesApi.remove(s.id);
      message.success('已删除');
      await load();
    },
  });
}
async function test(id) {
  return sourcesApi.test(id);
}
async function onExport() {
  const payload = await sourcesApi.export();
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  triggerDownload(blob, 'sources.json');
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
function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
</script>
