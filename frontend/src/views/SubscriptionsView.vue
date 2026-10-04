<template>
  <div>
    <div class="mini-stats">
      <div class="mini"><span class="m-ico" style="background:#e6f4ff;color:#0958d9">📡</span><div><div class="v">{{ stats.total }}</div><div class="k">累计订阅</div></div></div>
      <div class="mini"><span class="m-ico" style="background:#f6ffed;color:#389e0d">✅</span><div><div class="v">{{ stats.alive }}</div><div class="k">可用订阅（上轮验活）</div></div></div>
      <div class="mini"><span class="m-ico" style="background:#fff2f0;color:#cf1322">❌</span><div><div class="v">{{ stats.dead }}</div><div class="k">失效订阅</div></div></div>
      <div class="mini"><span class="m-ico" style="background:#f5f5f5;color:rgba(0,0,0,.45)">🕓</span><div><div class="v">{{ stats.pending }}</div><div class="k">待验证</div></div></div>
    </div>
    <div class="card">
      <div class="card-hd">
        <h3>订阅池</h3>
        <div style="display:flex;gap:8px">
          <a-button size="small" @click="downloadCsv('subscriptions')">⤓ 导出 CSV</a-button>
        </div>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:16px">
        <a-select v-model:value="filters.origin" style="width:150px" placeholder="全部来源" allowClear @change="load">
          <a-select-option v-for="o in origins" :key="o" :value="o">{{ o }}</a-select-option>
        </a-select>
        <a-select v-model:value="filters.status" style="width:120px" placeholder="全部状态" allowClear @change="load">
          <a-select-option value="alive">存活</a-select-option><a-select-option value="dead">失效</a-select-option><a-select-option value="pending">待验证</a-select-option>
        </a-select>
        <a-input-search v-model:value="filters.keyword" style="width:280px" placeholder="🔍 搜索订阅 URL / 域名" allowClear @search="load" />
        <a-button size="small" type="primary" @click="load">查询</a-button>
        <a-button size="small" @click="reset">重置</a-button>
      </div>
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr>
            <th style="width:30px"><input type="checkbox" v-model="allChecked" @change="toggleAll" /></th>
            <th>订阅 URL</th><th>来源</th><th>状态</th><th>连续失败</th><th>贡献节点(存活)</th><th>首次发现</th><th>最近存活</th><th style="width:70px">操作</th>
          </tr></thead>
          <tbody>
            <tr v-for="s in rows" :key="s.id">
              <td><input type="checkbox" v-model="checked[s.id]" /></td>
              <td class="url-cell"><div class="u">{{ s.url }}</div><div class="h">{{ hostOf(s.url) }}</div></td>
              <td><span class="tag info plain">{{ s.origin }}</span></td>
              <td><span class="tag" :class="statusClass(s.status)">{{ statusLabel(s.status) }}</span></td>
              <td :class="{ 'tag-err': s.errors > 0 }" :style="s.errors > 0 ? 'color:var(--error-tx)' : ''">{{ s.errors }}</td>
              <td><b>{{ s.contributed_nodes }}</b></td>
              <td class="muted">{{ fmt(s.first_seen_at) }}</td>
              <td class="muted">{{ fmt(s.last_alive_at) }}</td>
              <td><a class="btn link" @click="openDetail(s)">详情</a></td>
            </tr>
            <tr v-if="!rows.length"><td colspan="9" class="empty-tip">暂无订阅</td></tr>
          </tbody>
        </table>
      </div>
      <div class="pager"><span>共 {{ total }} 条</span><a-pagination v-model:current="page" :total="total" :page-size="20" simple @change="load" /></div>
    </div>

    <a-drawer :open="!!detail" title="订阅详情" width="540" @close="detail = null">
      <template v-if="detail">
        <div class="kv-row"><span class="k">URL</span><span class="v mono">{{ detail.url }}</span></div>
        <div class="kv-row"><span class="k">来源</span><span class="v">{{ detail.origin }}</span></div>
        <div class="kv-row"><span class="k">状态</span><span class="v"><span class="tag" :class="statusClass(detail.status)">{{ statusLabel(detail.status) }}</span></span></div>
        <div class="kv-row"><span class="k">连续失败</span><span class="v">{{ detail.errors }} 次</span></div>
        <div class="kv-row"><span class="k">首次发现</span><span class="v muted">{{ fmt(detail.first_seen_at) }}</span></div>
        <div class="kv-row"><span class="k">最近存活</span><span class="v muted">{{ fmt(detail.last_alive_at) }}</span></div>
        <div class="kv-row"><span class="k">跳过缓存</span><span class="v">{{ detail.skip_cache ? '是' : '否' }}</span></div>
        <div class="section-title">上轮贡献节点（存活）</div>
        <div class="muted" style="font-size:12.5px">{{ detail.contributed_nodes }} 个（节点明细见「节点浏览」按来源订阅搜索）</div>
      </template>
    </a-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue';

import { results as resultsApi } from '../api';

const rows = ref([]);
const total = ref(0);
const page = ref(1);
const detail = ref(null);
const checked = ref({});
const allChecked = ref(false);
const origins = ['TELEGRAM', 'GITHUB', 'GIST', 'PAGE', 'GOOGLE', 'YANDEX', 'V2RAYSE', 'TEMPORARY', 'OWNED'];
const filters = reactive({ origin: undefined, status: undefined, keyword: '' });
const stats = reactive({ total: 0, alive: 0, dead: 0, pending: 0 });

const statusClass = (s) => ({ alive: 'ok', dead: 'err', pending: 'warn' }[s] || 'gray');
const statusLabel = (s) => ({ alive: '存活', dead: '失效', pending: '待验证' }[s] || s);
const hostOf = (url) => { try { return new URL(url).hostname; } catch { return ''; } };
const fmt = (iso) => (iso ? iso.replace('T', ' ').slice(0, 16) : '—');

async function load() {
  const data = await resultsApi.subscriptions({ ...filters, page: page.value, page_size: 20 });
  rows.value = data.items;
  total.value = data.total;
  checked.value = {};
  allChecked.value = false;
}
async function loadStats() {
  for (const status of ['alive', 'dead', 'pending']) {
    const data = await resultsApi.subscriptions({ status, page: 1, page_size: 1 });
    stats[status] = data.total;
  }
  const all = await resultsApi.subscriptions({ page: 1, page_size: 1 });
  stats.total = all.total;
}
function reset() { Object.assign(filters, { origin: undefined, status: undefined, keyword: '' }); page.value = 1; load(); }
function toggleAll() { rows.value.forEach((r) => (checked.value[r.id] = allChecked.value)); }
async function openDetail(s) { detail.value = await resultsApi.subscription(s.id); }
function downloadCsv(kind) { window.open(`/api/export/${kind}.csv`, '_blank'); }

onMounted(() => { load(); loadStats(); });
</script>
