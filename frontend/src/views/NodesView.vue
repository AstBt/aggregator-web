<template>
  <div>
    <div class="mini-stats">
      <div class="mini"><span class="m-ico" style="background:#e6f4ff;color:#0958d9">🌐</span><div><div class="v">{{ stats.alive }}</div><div class="k">存活节点（{{ runId ? '#' + runId : '最新轮次' }}）</div></div></div>
      <div class="mini"><span class="m-ico" style="background:#f6ffed;color:#389e0d">⚡</span><div><div class="v">{{ stats.avg }}ms</div><div class="k">平均延迟</div></div></div>
      <div class="mini"><span class="m-ico" style="background:#e6fffb;color:#08979c">🏠</span><div><div class="v">{{ stats.residential }}</div><div class="k">住宅 IP 节点</div></div></div>
      <div class="mini"><span class="m-ico" style="background:#fff7e6;color:#d48806">📦</span><div><div class="v">{{ artifacts.length }}</div><div class="k">本地产物</div></div></div>
    </div>

    <div class="card" v-if="artifacts.length">
      <div class="card-hd"><h3>本轮产物（本地文件）</h3><span class="muted" style="font-size:12px">写入策略见「结果存储」</span></div>
      <div class="dash-grid" style="margin-bottom:0">
        <div class="art" v-for="a in artifacts" :key="a.id">
          <span class="a-ico" :style="{ background: targetBg(a.target) }">{{ targetIcon(a.target) }}</span>
          <div style="flex:1">
            <h5>{{ a.target }}</h5>
            <p>{{ a.path.split(/[\\/]/).pop() }} · {{ (a.size / 1024).toFixed(1) }} KB</p>
            <div class="dl"><a-button size="small" type="primary" @click="download(a)">⤓ 下载</a-button></div>
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-hd">
        <h3>节点列表</h3>
        <div style="display:flex;gap:8px">
          <a-button size="small" @click="downloadCsv('nodes')">⤓ CSV</a-button>
          <a-button size="small" type="primary" @click="exportOpen = true">⤒ 导出客户端配置</a-button>
        </div>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:16px">
        <a-select v-model:value="filters.protocol" style="width:120px" placeholder="全部协议" allowClear @change="load">
          <a-select-option v-for="p in ['vless','vmess','hysteria2','ss','trojan','anytls']" :key="p" :value="p">{{ p }}</a-select-option>
        </a-select>
        <a-select v-model:value="filters.region" style="width:110px" placeholder="全部地区" allowClear @change="load">
          <a-select-option v-for="r in ['香港','台湾','新加坡','日本','美国','韩国']" :key="r" :value="r">{{ r }}</a-select-option>
        </a-select>
        <a-select v-model:value="filters.alive" style="width:110px" placeholder="全部状态" allowClear @change="load">
          <a-select-option :value="true">仅存活</a-select-option><a-select-option :value="false">仅失效</a-select-option>
        </a-select>
        <a-select v-model:value="filters.residential" style="width:110px" placeholder="IP 类型" allowClear @change="load">
          <a-select-option :value="true">住宅 IP</a-select-option><a-select-option :value="false">非住宅</a-select-option>
        </a-select>
        <a-select v-model:value="filters.delayBand" style="width:130px" placeholder="全部延迟" allowClear @change="load">
          <a-select-option value="fast">&lt; 300ms</a-select-option><a-select-option value="mid">300-800ms</a-select-option><a-select-option value="slow">&gt; 800ms</a-select-option>
        </a-select>
        <a-input-search v-model:value="filters.keyword" style="width:240px" placeholder="🔍 搜索节点名 / 服务器" allowClear @search="load" />
        <a-button size="small" type="primary" @click="load">查询</a-button>
        <a-button size="small" @click="reset">重置</a-button>
      </div>
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr>
            <th style="width:30px"><input type="checkbox" /></th>
            <th>节点名</th><th>协议</th><th>服务器</th><th>延迟</th><th>地区</th><th>住宅</th><th>来源订阅</th><th style="width:64px">操作</th>
          </tr></thead>
          <tbody>
            <tr v-for="n in rows" :key="n.id">
              <td><input type="checkbox" /></td>
              <td><b>{{ n.name }}</b></td>
              <td><span class="proto" :class="n.protocol">{{ n.protocol.toUpperCase() }}</span></td>
              <td class="mono">{{ n.server }}:{{ n.port }}</td>
              <td><span class="delay" :class="delayClass(n.delay_ms)">{{ n.delay_ms ?? '—' }}ms</span></td>
              <td>{{ n.region || '—' }}</td>
              <td><span v-if="n.residential" class="tag ok" style="line-height:18px">住宅</span><span v-else class="muted">—</span></td>
              <td class="mono muted">{{ n.source_sub ? hostOf(n.source_sub) : '—' }}</td>
              <td><a class="btn link" @click="openDetail(n)">详情</a></td>
            </tr>
            <tr v-if="!rows.length"><td colspan="9" class="empty-tip">暂无节点</td></tr>
          </tbody>
        </table>
      </div>
      <div class="pager"><span>共 {{ total }} 条</span><a-pagination v-model:current="page" :total="total" :page-size="20" simple @change="load" /></div>
    </div>

    <a-drawer :open="!!detail" title="节点详情" width="540" @close="detail = null">
      <template v-if="detail">
        <div class="kv-row"><span class="k">名称</span><span class="v">{{ detail.name }}</span></div>
        <div class="kv-row"><span class="k">协议</span><span class="v">{{ detail.protocol }}</span></div>
        <div class="kv-row"><span class="k">服务器</span><span class="v mono">{{ detail.server }}:{{ detail.port }}</span></div>
        <div class="kv-row"><span class="k">延迟</span><span class="v">{{ detail.delay_ms }}ms</span></div>
        <div class="kv-row"><span class="k">地区 / 住宅</span><span class="v">{{ detail.region || '—' }} · {{ detail.residential ? '住宅' : '非住宅' }}</span></div>
        <div class="kv-row"><span class="k">来源订阅</span><span class="v mono">{{ detail.source_sub }}</span></div>
        <div class="section-title">原始字段（raw）</div>
        <div class="raw-box">{{ JSON.stringify(detail.raw, null, 2) }}</div>
      </template>
    </a-drawer>

    <!-- 导出弹窗 -->
    <a-modal v-model:open="exportOpen" title="导出客户端配置" width="640px" @ok="onExport" ok-text="开始转换并下载" :confirm-loading="exporting">
      <div class="section-title">客户端类型（导出时进行协议转换）</div>
      <div class="radio-cards c3">
        <div class="radio-card" :class="{ sel: exportForm.target === 'clash' }" @click="exportForm.target = 'clash'"><h5>📕 Clash</h5><p>Clash / Clash Meta / mihomo 内核，YAML 格式</p></div>
        <div class="radio-card" :class="{ sel: exportForm.target === 'v2ray' }" @click="exportForm.target = 'v2ray'"><h5>📗 V2Ray (mixed)</h5><p>v2rayN / sing-box 等支持的混合订阅，Base64 文本</p></div>
        <div class="radio-card" :class="{ sel: exportForm.target === 'singbox' }" @click="exportForm.target = 'singbox'"><h5>📘 SingBox</h5><p>sing-box 客户端，JSON 格式</p></div>
      </div>
      <div class="section-title" style="margin-top:18px">导出范围</div>
      <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
        <span style="font-size:13px;color:var(--text-2)">默认仅导出存活节点</span>
        <a-checkbox v-model:checked="exportForm.only_alive">仅存活</a-checkbox>
      </div>
      <div class="sched-preview" style="margin-top:12px">预计节点 {{ total }} 个 · 服务端实时转换 · 文件格式 {{ ext }}</div>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { message } from 'ant-design-vue';

import { dashboard as dashboardApi, results as resultsApi, tasks as tasksApi } from '../api';

const rows = ref([]);
const total = ref(0);
const page = ref(1);
const detail = ref(null);
const artifacts = ref([]);
const runId = ref(null);
const stats = reactive({ alive: 0, avg: 0, residential: 0 });
const filters = reactive({ protocol: undefined, region: undefined, alive: undefined, residential: undefined, delayBand: undefined, keyword: '' });
const exportOpen = ref(false);
const exporting = ref(false);
const exportForm = reactive({ target: 'clash', only_alive: true });

const targetIcon = (t) => ({ clash: '📕', v2ray: '📗', singbox: '📘' }[t] || '📄');
const targetBg = (t) => ({ clash: '#e6f4ff', v2ray: '#f6ffed', singbox: '#f9f0ff' }[t] || '#f5f5f5');
const ext = computed(() => ({ clash: 'clash.yaml', v2ray: 'v2ray.txt', singbox: 'singbox.json' }[exportForm.target]));
const delayClass = (ms) => (ms == null ? '' : ms < 300 ? 'g' : ms < 800 ? 'y' : 'r');
const hostOf = (url) => { try { return new URL(url).hostname; } catch { return url; } };

async function load() {
  const base = { ...filters, page: page.value, page_size: 20 };
  if (filters.delayBand === 'fast') { base.min_delay = 0; base.max_delay = 299; }
  if (filters.delayBand === 'mid') { base.min_delay = 300; base.max_delay = 799; }
  if (filters.delayBand === 'slow') { base.min_delay = 800; }
  delete base.delayBand;
  const data = await resultsApi.nodes(base);
  rows.value = data.items;
  total.value = data.total;
}
async function loadMeta() {
  const overview = await dashboardApi.overview();
  stats.alive = overview.nodes_alive;
  stats.avg = overview.avg_delay_ms;
  stats.residential = overview.residential_count;
  runId.value = overview.latest_run_id;
  if (runId.value) artifacts.value = (await tasksApi.artifacts(runId.value)).items;
}
function reset() { Object.assign(filters, { protocol: undefined, region: undefined, alive: undefined, residential: undefined, delayBand: undefined, keyword: '' }); page.value = 1; load(); }
async function openDetail(n) { detail.value = await resultsApi.node(n.id); }
function download(a) {
  const url = `/api/tasks/${runId.value}/artifacts`;
  fetch(url).then(() => message.info('演示环境：请从服务端数据目录获取文件'));
}
async function onExport() {
  exporting.value = true;
  try {
    const data = await resultsApi.export({ target: exportForm.target, only_alive: exportForm.only_alive });
    const blob = new Blob([data.content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = data.filename; a.click();
    URL.revokeObjectURL(url);
    message.success(`已导出 ${data.count} 个节点（${data.filename}）`);
    exportOpen.value = false;
  } catch (error) {
    message.error(error.message);
  } finally {
    exporting.value = false;
  }
}
function downloadCsv(kind) { window.open(`/api/export/${kind}.csv`, '_blank'); }

onMounted(() => { load(); loadMeta(); });
</script>
