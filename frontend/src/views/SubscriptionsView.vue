<template>
  <div>
    <div class="mini-stats">
      <div class="mini"><span class="m-ico" style="background:#e6f4ff;color:#0958d9">📡</span><div><div class="v">{{ stats.total }}</div><div class="k">订阅池（验证后入库）</div></div></div>
      <div class="mini"><span class="m-ico" style="background:#f6ffed;color:#389e0d">✅</span><div><div class="v">{{ stats.alive }}</div><div class="k">可用订阅（验活确认）</div></div></div>
      <div class="mini"><span class="m-ico" style="background:#fff2f0;color:#cf1322">❌</span><div><div class="v">{{ stats.dead }}</div><div class="k">复核失效（容忍期）</div></div></div>
      <div class="mini"><span class="m-ico" style="background:#f5f5f5;color:rgba(0,0,0,.45)">🔄</span><div><div class="v">{{ stats.testing }}</div><div class="k">测试中</div></div></div>
    </div>
    <div class="card">
      <div class="card-hd">
        <h3>订阅池</h3>
        <div style="display:flex;gap:8px">
          <button class="btn sm" @click="downloadCsv('subscriptions')">⤓ 导出 CSV</button>
          <button class="btn sm primary" :disabled="testing" @click="onTestStatus">
            <span v-if="testing" class="spin-mini"></span>{{ testing ? `测试中 ${testDone}/${testTotal}` : '📶 测试订阅状态' }}
          </button>
        </div>
      </div>

      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:16px">
        <select class="input" style="width:150px;height:32px;font-size:12.5px" v-model="filters.origin" @change="load">
          <option value="">全部来源</option>
          <option v-for="o in origins" :key="o" :value="o">{{ o }}</option>
        </select>
        <select class="input" style="width:120px;height:32px;font-size:12.5px" v-model="filters.status" @change="load">
          <option value="">全部状态</option><option value="alive">存活</option><option value="dead">失效</option><option value="testing">测试中</option>
        </select>
        <input class="input" style="flex:1;min-width:220px" placeholder="🔍 搜索订阅 URL / 域名" v-model="filters.keyword" @keyup.enter="load">
        <button class="btn sm primary" @click="load">查询</button>
        <button class="btn sm" @click="reset">重置</button>
      </div>

      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr>
            <th style="width:30px"><input type="checkbox" v-model="allChecked" @change="toggleAll"></th>
            <th>订阅 URL</th><th>来源</th><th>状态</th><th>连续失败</th><th>存活节点数</th><th>首次发现</th><th>最近存活</th><th style="width:70px">操作</th>
          </tr></thead>
          <tbody>
            <tr v-for="s in rows" :key="s.id">
              <td><input type="checkbox" v-model="checked[s.id]"></td>
              <td class="url-cell"><div class="u">{{ s.url }}</div><div class="h">{{ hostOf(s.url) }}</div></td>
              <td><span class="tag info plain">{{ s.origin }}</span></td>
              <td><span class="tag" :class="statusClass(s.status)">{{ statusLabel(s.status) }}</span></td>
              <td :style="s.errors > 0 ? 'color:var(--error-tx)' : ''">{{ s.errors }}</td>
              <td><b>{{ s.node_count || s.contributed_nodes }}</b></td>
              <td class="muted">{{ fmt(s.first_seen_at) }}</td>
              <td class="muted">{{ fmt(s.last_alive_at) }}</td>
              <td><a class="btn link" @click="openDetail(s)">详情</a></td>
            </tr>
            <tr v-if="!rows.length"><td colspan="9" class="empty-tip">暂无订阅</td></tr>
          </tbody>
        </table>
      </div>
      <div class="pager">
        <span>共 {{ total }} 条 · 已选 {{ selectedCount }} 条 <a class="btn link" @click="onTestStatus">测试所选</a></span>
        <span>‹ 1 / 1 ›</span>
      </div>
    </div>

    <!-- 订阅详情抽屉 -->
    <div class="drawer-mask" @click="detail=null"></div>
    <aside class="drawer" :class="{ open: !!detail }">
      <div class="drawer-hd">
        <h3>订阅详情</h3>
        <span class="btn link" @click="detail=null" style="font-size:16px">✕</span>
      </div>
      <div class="drawer-bd" v-if="detail">
        <div class="kv-row"><span class="k">URL</span><span class="v mono">{{ detail.url }}</span></div>
        <div class="kv-row"><span class="k">来源</span><span class="v">{{ detail.origin }}</span></div>
        <div class="kv-row"><span class="k">状态</span><span class="v"><span class="tag" :class="statusClass(detail.status)">{{ statusLabel(detail.status) }}</span></span></div>
        <div class="kv-row"><span class="k">连续失败</span><span class="v">{{ detail.errors }} 次</span></div>
        <div class="kv-row"><span class="k">首次发现</span><span class="v muted">{{ fmt(detail.first_seen_at) }}</span></div>
        <div class="kv-row"><span class="k">最近存活</span><span class="v muted">{{ fmt(detail.last_alive_at) }}</span></div>
        <div class="kv-row"><span class="k">跳过缓存</span><span class="v">{{ detail.skip_cache ? '是' : '否' }}</span></div>

        <div class="section-title">
          该订阅的节点（{{ subNodes.length }}）
          <span class="muted" style="font-size:11px;font-weight:400">与「节点浏览」的散节点相互独立</span>
        </div>
        <div class="tbl-wrap" style="max-height:300px;overflow-y:auto">
          <table class="tbl">
            <thead><tr><th>节点名</th><th>协议</th><th>服务器</th><th>延迟</th><th>状态</th><th>地区</th></tr></thead>
            <tbody>
              <tr v-for="n in subNodes" :key="n.id">
                <td><b>{{ n.name }}</b></td>
                <td>{{ n.protocol }}</td>
                <td class="mono">{{ n.server }}:{{ n.port }}</td>
                <td><span class="delay" :class="n.delay_ms < 300 ? 'g' : n.delay_ms < 800 ? 'y' : 'r'">{{ n.delay_ms ?? '—' }}ms</span></td>
                <td><span class="tag" :class="n.alive ? 'ok' : 'err'">{{ n.alive ? '存活' : '失效' }}</span></td>
                <td>{{ n.region || '—' }}</td>
              </tr>
              <tr v-if="!subNodes.length"><td colspan="6" class="empty-tip">该订阅暂无解析节点</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </aside>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { message } from 'ant-design-vue';

import { results as resultsApi, testJobs } from '../api';

const rows = ref([]);
const total = ref(0);
const detail = ref(null);
const subNodes = ref([]);
const checked = ref({});
const allChecked = ref(false);
const testing = ref(false);
const testDone = ref(0);
const testTotal = ref(0);
const origins = ['TELEGRAM', 'GITHUB', 'GIST', 'PAGE', 'GOOGLE', 'YANDEX', 'V2RAYSE', 'TEMPORARY', 'OWNED'];
const filters = reactive({ origin: '', status: '', keyword: '' });
const stats = reactive({ total: 0, alive: 0, dead: 0, testing: 0 });
const selectedCount = computed(() => Object.values(checked.value).filter(Boolean).length);

const statusClass = (s) => ({ alive: 'ok', dead: 'err', testing: 'info' }[s] || 'gray');
const statusLabel = (s) => ({ alive: '存活', dead: '失效', testing: '测试中' }[s] || s);
const hostOf = (url) => { try { return new URL(url).hostname; } catch { return ''; } };
const fmt = (iso) => (iso ? iso.replace('T', ' ').slice(0, 16) : '—');

async function load() {
  const params = { ...filters, page_size: 50 };
  const data = await resultsApi.subscriptions(params);
  rows.value = data.items;
  total.value = data.total;
  checked.value = {};
  allChecked.value = false;
}
async function loadStats() {
  for (const status of ['alive', 'dead', 'testing']) {
    const data = await resultsApi.subscriptions({ status, page_size: 1 });
    stats[status] = data.total;
  }
  const all = await resultsApi.subscriptions({ page_size: 1 });
  stats.total = all.total;
}
function reset() { Object.assign(filters, { origin: '', status: '', keyword: '' }); load(); }
function toggleAll() { rows.value.forEach((r) => (checked.value[r.id] = allChecked.value)); }

async function onTestStatus() {
  const ids = Object.entries(checked.value).filter(([, v]) => v).map(([k]) => Number(k));
  testing.value = true;
  try {
    const res = await resultsApi.testSubscriptions(ids);
    testTotal.value = res.total;
    message.success(ids.length ? `已开始测试所选 ${res.total} 个订阅` : `已开始测试全部 ${res.total} 个订阅`);
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
        if (job.status === 'success' || job.status === 'failed') {
          clearInterval(timer);
          testing.value = false;
          message[job.status === 'success' ? 'success' : 'error'](job.status === 'success' ? '订阅状态测试完成' : `测试失败: ${job.message}`);
          await load();
          await loadStats();
        }
      }
    } catch { /* 忽略轮询错误 */ }
  }, 1500);
}

async function openDetail(s) {
  detail.value = await resultsApi.subscription(s.id);
  const nodes = await resultsApi.subscriptionNodes(s.id, { page_size: 50 });
  subNodes.value = nodes.items;
}
function downloadCsv(kind) { window.open(`/api/export/${kind}.csv`, '_blank'); }

onMounted(() => { load(); loadStats(); });
</script>

<style scoped>
.spin-mini{display:inline-block;width:12px;height:12px;border:2px solid rgba(255,255,255,.4);border-top-color:#fff;border-radius:50%;animation:rot .7s linear infinite;margin-right:5px;vertical-align:-2px}
@keyframes rot{to{transform:rotate(360deg)}}
.url-cell{max-width:400px}
.url-cell .u{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:Consolas,monospace;font-size:12px;color:var(--text-1)}
.url-cell .h{font-size:11.5px;color:var(--text-3)}
.delay{font-weight:700;font-size:12.5px}
.delay.g{color:#389e0d}.delay.y{color:#d48806}.delay.r{color:#cf1322}
</style>
