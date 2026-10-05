<template>
  <div>
    <div class="mini-stats">
      <div class="mini"><span class="m-ico" style="background:#e6f4ff;color:#0958d9">🌐</span><div><div class="v">{{ stats.alive }}</div><div class="k">存活散节点（系统库 {{ stats.total }}）</div></div></div>
      <div class="mini"><span class="m-ico" style="background:#f6ffed;color:#389e0d">⚡</span><div><div class="v">{{ stats.avg }}ms</div><div class="k">平均延迟</div></div></div>
      <div class="mini"><span class="m-ico" style="background:#e6fffb;color:#08979c">🏠</span><div><div class="v">{{ stats.residential }}</div><div class="k">住宅 IP 节点</div></div></div>
      <div class="mini"><span class="m-ico" style="background:#f9f0ff;color:#722ed1">🧩</span><div><div class="v">{{ sources.length }}</div><div class="k">贡献爬取源</div></div></div>
    </div>

    <!-- 本轮产物 -->
    <div class="card" v-if="artifacts.length">
      <div class="card-hd"><h3>本轮产物（本地文件）</h3><span class="muted" style="font-size:12px">写入策略见「结果存储」</span></div>
      <div class="dash-grid" style="margin-bottom:0">
        <div class="art" v-for="a in artifacts" :key="a.id">
          <span class="a-ico" :style="{ background: targetBg(a.target) }">{{ targetIcon(a.target) }}</span>
          <div style="flex:1">
            <h5>{{ a.target === 'v2ray' ? 'V2Ray (mixed)' : a.target }}</h5>
            <p>{{ a.path.split(/[\\/]/).pop() }} · {{ (a.size / 1024).toFixed(1) }} KB</p>
            <div class="dl"><button class="btn sm primary" @click="downloadArtifact(a)">⤓ 下载</button></div>
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-hd">
        <h3>节点列表<small class="muted" style="font-weight:400">&nbsp;·&nbsp;爬取源直接获得的散节点</small></h3>
        <div style="display:flex;gap:8px">
          <button class="btn sm" @click="downloadCsv('nodes')">⤓ CSV</button>
          <button class="btn sm primary" :disabled="testing" @click="onTestStatus">
            <span v-if="testing" class="spin-mini"></span>{{ testing ? `测试中 ${testDone}/${testTotal}${testPhase ? ' · ' + testPhase : ''}` : '📶 测试节点状态' }}
          </button>
          <button class="btn sm primary" @click="exportOpen = true; loadExportHistory()">⤒ 导出客户端配置</button>
        </div>
      </div>

      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:16px">
        <select class="input" style="width:120px;height:32px;font-size:12.5px" v-model="filters.protocol" @change="load">
          <option value="">全部协议</option>
          <option v-for="p in ['vless','vmess','hysteria2','ss','trojan','anytls']" :key="p" :value="p">{{ p }}</option>
        </select>
        <select class="input" style="width:120px;height:32px;font-size:12.5px" v-model="filters.source" @change="load">
          <option value="">全部爬取源</option>
          <option v-for="s in sources" :key="s" :value="s">{{ s }}</option>
        </select>
        <select class="input" style="width:110px;height:32px;font-size:12.5px" v-model="filters.region" @change="load">
          <option value="">全部地区</option>
          <option v-for="r in ['香港','台湾','新加坡','日本','美国','韩国']" :key="r" :value="r">{{ r }}</option>
        </select>
        <select class="input" style="width:110px;height:32px;font-size:12.5px" v-model="filters.alive" @change="load">
          <option value="">全部状态</option><option :value="true">仅存活</option><option :value="false">仅失效</option>
        </select>
        <select class="input" style="width:130px;height:32px;font-size:12.5px" v-model="filters.delayBand" @change="load">
          <option value="">全部延迟</option><option value="fast">&lt; 300ms</option><option value="mid">300-800ms</option><option value="slow">&gt; 800ms</option>
        </select>
        <input class="input" style="flex:1;min-width:200px" placeholder="🔍 搜索节点名 / 服务器" v-model="filters.keyword" @keyup.enter="load">
        <button class="btn sm primary" @click="load">查询</button>
        <button class="btn sm" @click="reset">重置</button>
      </div>

      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr>
            <th style="width:30px"><input type="checkbox" v-model="allChecked" @change="toggleAll"></th>
            <th>节点名</th><th>协议</th><th>服务器</th><th>延迟</th><th>地区</th><th>住宅</th><th>爬取源</th><th style="width:64px">操作</th>
          </tr></thead>
          <tbody>
            <tr v-for="n in rows" :key="n.id">
              <td><input type="checkbox" v-model="checked[n.id]"></td>
              <td><b>{{ n.name }}</b></td>
              <td><span class="proto" :class="n.protocol">{{ n.protocol.toUpperCase() }}</span></td>
              <td class="mono">{{ n.server }}:{{ n.port }}</td>
              <td><span class="delay" :class="delayClass(n.delay_ms)">{{ n.delay_ms ?? '—' }}ms</span></td>
              <td>{{ n.region || '—' }}</td>
              <td><span v-if="n.residential" class="tag ok" style="line-height:18px">住宅</span><span v-else class="muted">—</span></td>
              <td><span class="tag gray plain">{{ n.source || '—' }}</span></td>
              <td><a class="btn link" @click="openDetail(n)">详情</a></td>
            </tr>
            <tr v-if="!rows.length"><td colspan="9" class="empty-tip">暂无散节点（请在任务中启用爬取源并执行爬取）</td></tr>
          </tbody>
        </table>
      </div>
      <div class="pager">
        <span>共 {{ total }} 条 · 已选 {{ selectedCount }} 条 <a class="btn link" @click="onTestStatus">测试所选</a></span>
        <span>‹ 1 / 1 ›</span>
      </div>
    </div>

    <!-- 节点详情抽屉 -->
    <div class="drawer-mask" @click="detail=null"></div>
    <aside class="drawer" :class="{ open: !!detail }">
      <div class="drawer-hd"><h3>节点详情</h3><span class="btn link" @click="detail=null" style="font-size:16px">✕</span></div>
      <div class="drawer-bd" v-if="detail">
        <div class="kv-row"><span class="k">名称</span><span class="v">{{ detail.name }}</span></div>
        <div class="kv-row"><span class="k">协议</span><span class="v">{{ detail.protocol }}</span></div>
        <div class="kv-row"><span class="k">服务器</span><span class="v mono">{{ detail.server }}:{{ detail.port }}</span></div>
        <div class="kv-row"><span class="k">延迟</span><span class="v">{{ detail.delay_ms ?? '—' }}ms</span></div>
        <div class="kv-row"><span class="k">地区 / 住宅</span><span class="v">{{ detail.region || '—' }} · {{ detail.residential ? '住宅' : '非住宅' }}</span></div>
        <div class="kv-row"><span class="k">爬取源</span><span class="v">{{ detail.source || '—' }}</span></div>
        <div class="kv-row"><span class="k">发现轮次</span><span class="v muted">{{ detail.run_id ? '#' + detail.run_id : '—' }}</span></div>
        <div class="section-title">原始字段（raw）</div>
        <div class="raw-box">{{ JSON.stringify(detail.raw, null, 2) }}</div>
      </div>
    </aside>

    <!-- 导出弹窗 -->
    <div class="modal-mask" :class="{ show: exportOpen }" @click.self="exportOpen=false">
      <div class="modal">
        <div class="modal-hd">
          <h3>导出客户端配置</h3>
          <span class="close-x" @click="exportOpen=false">✕</span>
        </div>
        <div class="modal-bd">
          <div class="section-title">客户端类型（导出时进行协议转换）</div>
          <div class="radio-cards c3">
            <div class="radio-card" :class="{ sel: exportForm.target === 'clash' }" @click="exportForm.target='clash'"><h5>📕 Clash</h5><p>Clash / Clash Meta / mihomo 内核，YAML 格式</p></div>
            <div class="radio-card" :class="{ sel: exportForm.target === 'v2ray' }" @click="exportForm.target='v2ray'"><h5>📗 V2Ray (mixed)</h5><p>v2rayN / sing-box 等支持的混合订阅，Base64 文本</p></div>
            <div class="radio-card" :class="{ sel: exportForm.target === 'singbox' }" @click="exportForm.target='singbox'"><h5>📘 SingBox</h5><p>sing-box 客户端，JSON 格式</p></div>
          </div>
          <div class="section-title" style="margin-top:18px">导出范围</div>
          <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
            <span style="font-size:13px;color:var(--text-2)">默认仅导出存活节点</span>
            <label class="checkbox"><input type="checkbox" v-model="exportForm.only_alive"> 仅存活</label>
          </div>
          <div class="sched-preview" style="margin-top:12px">预计节点 {{ total }} 个 · 服务端实时转换 · 文件格式 {{ ext }}</div>
          <div class="section-title" style="margin-top:18px">导出历史（最近 {{ exportHistory.length }} 次）</div>
          <table class="tbl" v-if="exportHistory.length">
            <thead><tr><th>类型</th><th>文件</th><th>节点数</th><th>大小</th><th>时间</th></tr></thead>
            <tbody>
              <tr v-for="e in exportHistory" :key="e.id">
                <td>{{ e.target === 'v2ray' ? 'V2Ray (mixed)' : e.target }}</td>
                <td class="mono">{{ e.filename }}</td>
                <td>{{ e.count }}</td>
                <td>{{ (e.size / 1024).toFixed(1) }} KB</td>
                <td class="muted">{{ e.created_at?.replace('T', ' ').slice(0, 16) }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="muted" style="font-size:12.5px">暂无导出记录</div>
        </div>
        <div class="modal-ft">
          <button class="btn" @click="exportOpen=false">取消</button>
          <button class="btn primary" :disabled="exporting" @click="onExport">{{ exporting ? '转换中…' : '开始转换并下载' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { message } from 'ant-design-vue';

import { dashboard as dashboardApi, exports as exportsApi, results as resultsApi, tasks as tasksApi, testJobs } from '../api';

const rows = ref([]);
const total = ref(0);
const detail = ref(null);
const artifacts = ref([]);
const sources = ref([]);
const checked = ref({});
const allChecked = ref(false);
const testing = ref(false);
const testPhase = ref('');
const testDone = ref(0);
const testTotal = ref(0);
const exportOpen = ref(false);
const exporting = ref(false);
const exportHistory = ref([]);
const exportForm = reactive({ target: 'clash', only_alive: true });
const filters = reactive({ protocol: '', source: '', region: '', alive: '', delayBand: '', keyword: '' });
const stats = reactive({ total: 0, alive: 0, avg: 0, residential: 0 });
const selectedCount = computed(() => Object.values(checked.value).filter(Boolean).length);
const ext = computed(() => ({ clash: 'clash.yaml', v2ray: 'v2ray.txt', singbox: 'singbox.json' }[exportForm.target]));
const PHASE_LABELS = { delay: '测速', locate: '定位' };

const targetIcon = (t) => ({ clash: '📕', v2ray: '📗', singbox: '📘' }[t] || '📄');
const targetBg = (t) => ({ clash: '#e6f4ff', v2ray: '#f6ffed', singbox: '#f9f0ff' }[t] || '#f5f5f5');
const delayClass = (ms) => (ms == null ? '' : ms < 300 ? 'g' : ms < 800 ? 'y' : 'r');

async function load() {
  const base = { ...filters, page_size: 50 };
  if (filters.alive === '' || filters.alive === null) delete base.alive;
  if (filters.delayBand === 'fast') { base.min_delay = 0; base.max_delay = 299; }
  if (filters.delayBand === 'mid') { base.min_delay = 300; base.max_delay = 799; }
  if (filters.delayBand === 'slow') { base.min_delay = 800; }
  delete base.delayBand;
  const data = await resultsApi.nodes(base);
  rows.value = data.items;
  total.value = data.total;
  checked.value = {};
  allChecked.value = false;
  const srcSet = new Set(data.items.map((n) => n.source).filter(Boolean));
  sources.value = [...srcSet].sort();
}
async function loadMeta() {
  const overview = await dashboardApi.overview();
  // 汇总口径与列表一致：系统库中的散节点（kind=crawl），不关联单一任务轮次
  const loose = overview.loose || { total: 0, alive: 0, avg_delay_ms: 0, residential: 0, sources: [] };
  stats.total = loose.total;
  stats.alive = loose.alive;
  stats.avg = loose.avg_delay_ms;
  stats.residential = loose.residential;
  sources.value = [...new Set([...sources.value, ...loose.sources])].sort();
  const latestRun = overview.recent_runs?.[0]?.id;
  if (latestRun) artifacts.value = (await tasksApi.artifacts(latestRun)).items;
}
function reset() { Object.assign(filters, { protocol: '', source: '', region: '', alive: '', delayBand: '', keyword: '' }); load(); }
function toggleAll() { rows.value.forEach((r) => (checked.value[r.id] = allChecked.value)); }

async function onTestStatus() {
  const ids = Object.entries(checked.value).filter(([, v]) => v).map(([k]) => Number(k));
  testing.value = true;
  testPhase.value = '';
  try {
    const res = await resultsApi.testNodes({ ids, locate: true, residential: true });
    testTotal.value = res.total;
    message.success(ids.length ? `已开始测试所选 ${res.total} 个节点` : `已开始测试全部 ${res.total} 个散节点`);
    pollJob(res.job_id);
  } catch (error) {
    message.error(error.message);
    testing.value = false;
  }
}
async function pollJob(jobId) {
  const timer = setInterval(async () => {
    try {
      const jobs = (await testJobs.list()).items;
      const job = jobs.find((j) => j.job_id === jobId);
      if (job) {
        testDone.value = job.done;
        testTotal.value = job.total;
        testPhase.value = PHASE_LABELS[job.phase] || '';
        if (job.status === 'success' || job.status === 'failed') {
          clearInterval(timer);
          testing.value = false;
          message[job.status === 'success' ? 'success' : 'error'](job.status === 'success' ? '节点状态测试完成，已更新延迟/地区/住宅信息' : `测试失败: ${job.message}`);
          await load();
          await loadMeta();
        }
      }
    } catch { /* 忽略轮询错误 */ }
  }, 1500);
}

async function openDetail(n) { detail.value = await resultsApi.node(n.id); }
function downloadArtifact(a) { message.info('演示环境：请从服务端数据目录获取文件'); }
async function loadExportHistory() { exportHistory.value = (await exportsApi.list(10)).items; }
async function onExport() {
  exporting.value = true;
  try {
    const data = await resultsApi.export({ target: exportForm.target, only_alive: exportForm.only_alive, kind: 'crawl' });
    const blob = new Blob([data.content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = data.filename; a.click();
    URL.revokeObjectURL(url);
    message.success(`已导出 ${data.count} 个节点（${data.filename}）`);
    await loadExportHistory();
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

<style scoped>
.spin-mini{display:inline-block;width:12px;height:12px;border:2px solid rgba(255,255,255,.4);border-top-color:#fff;border-radius:50%;animation:rot .7s linear infinite;margin-right:5px;vertical-align:-2px}
@keyframes rot{to{transform:rotate(360deg)}}
.proto{font-weight:600;font-size:12px;letter-spacing:.3px}
.proto.vless{color:#0958d9}.proto.vmess{color:#4096ff}.proto.hysteria2{color:#389e0d}
.proto.ss{color:#08979c}.proto.trojan{color:#d46b08}.proto.anytls{color:#c41d7f}
.delay{font-weight:700;font-size:12.5px}
.delay.g{color:#389e0d}.delay.y{color:#d48806}.delay.r{color:#cf1322}
.art{border:1px solid #e8edf4;border-radius:10px;padding:15px 16px;display:flex;gap:13px;align-items:flex-start;transition:box-shadow .2s}
.art:hover{box-shadow:0 4px 14px rgba(0,0,0,.06)}
.art .a-ico{width:42px;height:42px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:19px;flex:none}
.art h5{font-size:13.5px;font-weight:600;margin-bottom:3px}
.art p{font-size:11.5px;color:var(--text-3);line-height:1.6}
.art .dl{margin-top:9px}
.raw-box{background:#1d2433;color:#c9d4e6;border-radius:8px;padding:13px 15px;font-family:Consolas,monospace;font-size:11.5px;line-height:1.75;white-space:pre-wrap;word-break:break-all}
</style>
