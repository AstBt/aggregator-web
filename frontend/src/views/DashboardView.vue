<template>
  <div>
    <div class="stat-grid">
      <div class="stat-card">
        <div class="sc-ico" style="background:#e6f4ff;color:#0958d9">📡</div>
        <div class="lb">订阅可达</div>
        <div class="num" style="color:#0958d9">{{ data.subs_alive ?? '-' }}</div>
        <div class="sub">累计 {{ data.subs_total ?? 0 }} · 上一轮验活确认</div>
      </div>
      <div class="stat-card">
        <div class="sc-ico" style="background:#f6ffed;color:#389e0d">🌐</div>
        <div class="lb">节点可用</div>
        <div class="num" style="color:#389e0d">{{ data.nodes_alive ?? '-' }}</div>
        <div class="sub">抓取 {{ data.nodes_total ?? 0 }} · 平均 {{ data.avg_delay_ms ?? 0 }}ms · 住宅 {{ data.residential_count ?? 0 }}</div>
      </div>
      <div class="stat-card">
        <div class="sc-ico" style="background:#f9f0ff;color:#722ed1">💾</div>
        <div class="lb">启用存储目标</div>
        <div class="num" style="color:#722ed1">{{ data.storage_targets_enabled ?? 0 }}</div>
        <div class="sub">目标为纯发布出口，旧数据来自系统库</div>
      </div>
      <div class="stat-card">
        <div class="sc-ico" style="background:#fff7e6;color:#d48806">📈</div>
        <div class="lb">近 7 日任务</div>
        <div class="num" style="color:#d48806">{{ weekRuns }}</div>
        <div class="sub">成功 {{ weekSuccess }} · 失败 {{ weekFailed }}</div>
      </div>
    </div>

    <div class="dash-grid">
      <div class="card">
        <div class="card-hd"><h3>节点协议分布</h3><span class="extra">存活节点</span></div>
        <div class="bars">
          <div v-for="item in protocolRows" :key="item.key" class="bar-row">
            <span class="muted">{{ item.key || '未知' }}</span>
            <div class="bar-track"><div class="bar-fill" :style="{ width: item.pct + '%', background: protocolColor(item.key) }"></div></div>
            <span class="pv">{{ item.count }}</span>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-hd"><h3>节点地区 Top 5</h3><span class="extra">存活节点</span></div>
        <div class="bars">
          <div v-for="item in regionRows" :key="item.region" class="bar-row">
            <span class="muted">{{ item.region }}</span>
            <div class="bar-track"><div class="bar-fill" :style="{ width: item.pct + '%', background: '#1677ff' }"></div></div>
            <span class="pv">{{ item.count }}</span>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-hd"><h3>节点延迟区间</h3><span class="extra">存活节点</span></div>
        <div class="bars">
          <div v-for="bucket in data.delay_buckets || []" :key="bucket.label" class="bar-row">
            <span class="muted">{{ bucket.label }}</span>
            <div class="bar-track"><div class="bar-fill" :style="{ width: bucket.pct + '%', background: bucket.color }"></div></div>
            <span class="pv">{{ bucket.count }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="two-col">
      <div class="card">
        <div class="card-hd"><h3>最近任务运行</h3><router-link class="btn link" to="/tasks">查看全部 →</router-link></div>
        <div class="tbl-wrap">
          <table class="tbl">
            <thead><tr><th>ID</th><th>模式</th><th>触发</th><th>状态</th><th>订阅/节点</th><th>耗时</th><th>开始时间</th></tr></thead>
            <tbody>
              <tr v-for="run in data.recent_runs || []" :key="run.id">
                <td class="mono">#{{ run.id }}</td>
                <td>{{ modeLabel(run.mode) }}</td>
                <td>{{ run.trigger === 'schedule' ? '定时' : '手动' }}</td>
                <td><span class="tag" :class="statusClass(run.status)">{{ statusLabel(run.status) }}</span></td>
                <td>{{ run.stats?.subs_alive ?? '—' }} / {{ run.stats?.nodes_alive ?? '—' }}</td>
                <td>{{ fmtDuration(run.duration_ms) }}</td>
                <td class="muted">{{ run.started_at?.replace('T', ' ').slice(0, 16) }}</td>
              </tr>
              <tr v-if="!(data.recent_runs || []).length"><td colspan="7" class="empty-tip">暂无任务记录</td></tr>
            </tbody>
          </table>
        </div>
      </div>
      <div class="card">
        <div class="card-hd"><h3>爬取源健康 / 存储状态</h3></div>
        <div class="health-row" v-for="s in data.source_health || []" :key="s.type">
          <span class="src">{{ typeIcon(s.type) }} {{ typeLabel(s.type) }}</span>
          <div class="bar-track"><div class="bar-fill" :style="{ width: (s.enabled / Math.max(s.total, 1) * 100) + '%', background: '#1677ff' }"></div></div>
          <span class="cnt">{{ s.enabled }}/{{ s.total }} 启用</span>
        </div>
        <div class="store-row" v-for="t in data.storage_status || []" :key="t.name">
          <span class="tgt-ico" :style="{ background: t.type === 'local' ? '#e6f4ff' : '#f6ffed' }">{{ t.type === 'local' ? '📁' : '🐙' }}</span>
          <b style="width:150px">{{ t.name }}</b>
          <span class="tag" :class="t.enable ? 'ok' : 'gray'">{{ t.enable ? '启用' : '停用' }}</span>
          <span style="flex:1"></span>
          <span class="muted">{{ t.last_write_at ? t.last_write_at.replace('T', ' ').slice(0, 16) : '未写入' }}</span>
          <span class="tag" :class="t.last_write_ok ? 'ok' : t.last_write_ok === false ? 'err' : 'gray'">
            {{ t.last_write_ok ? '成功' : t.last_write_ok === false ? '失败' : '—' }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';

import { dashboard as dashboardApi } from '../api';

const data = ref({});
const MODE = { crawl: '仅爬取', aggregate: '回测', full: '爬取+聚合' };
const TYPE = {
  telegram: ['📨', 'Telegram'], github: ['🐙', 'GitHub 搜索'], gist: ['📄', 'Gist 时间线'],
  google: ['🔍', 'Google 搜索'], yandex: ['🔎', 'Yandex 搜索'], page: ['🌐', '通用网页'],
  repo: ['📦', 'GitHub 仓库'], script: ['🧪', '脚本插件'],
};
const STATUS = { running: '运行中', success: '成功', failed: '失败', cancelled: '已取消', 'partial-success': '部分发布', pending: '等待中' };

const protocolRows = computed(() => {
  const rows = data.value.protocol_distribution || [];
  const max = Math.max(1, ...rows.map((r) => r.count));
  return rows.map((r) => ({ key: r.protocol || '未知', count: r.count, pct: Math.round((r.count / max) * 100) }));
});
const regionRows = computed(() => {
  const rows = data.value.region_top || [];
  const max = Math.max(1, ...rows.map((r) => r.count));
  return rows.map((r) => ({ ...r, pct: Math.round((r.count / max) * 100) }));
});
const inWeek = (iso) => iso && Date.now() - new Date(iso).getTime() < 7 * 864e5;
const weekRuns = computed(() => (data.value.recent_runs || []).filter((r) => inWeek(r.started_at)).length);
const weekSuccess = computed(() => (data.value.recent_runs || []).filter((r) => inWeek(r.started_at) && r.status === 'success').length);
const weekFailed = computed(() => (data.value.recent_runs || []).filter((r) => inWeek(r.started_at) && ['failed', 'partial-success'].includes(r.status)).length);

const modeLabel = (m) => MODE[m] || m;
const statusLabel = (s) => STATUS[s] || s;
const statusClass = (s) => ({ running: 'info', success: 'ok', failed: 'err', cancelled: 'gray', 'partial-success': 'warn', pending: 'warn' }[s] || 'gray');
const typeLabel = (t) => TYPE[t]?.[1] || t;
const typeIcon = (t) => TYPE[t]?.[0] || '🧩';
const protocolColor = (p) => ({ vless: '#1677ff', vmess: '#4096ff', hysteria2: '#52c41a', ss: '#13c2c2', trojan: '#faad14', anytls: '#eb2f96' }[p] || '#8c9eb5');
const fmtDuration = (ms) => (ms == null ? '—' : ms < 60000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.floor(ms / 60000)}m${Math.round((ms % 60000) / 1000)}s`);

onMounted(async () => {
  data.value = await dashboardApi.overview();
  const buckets = data.value.delay_buckets || [];
  const max = Math.max(1, ...buckets.map((b) => b.count));
  const colors = { '<300ms': '#52c41a', '300-800ms': '#faad14', '>800ms': '#f5222d' };
  data.value.delay_buckets = buckets.map((b) => ({ ...b, pct: Math.round((b.count / max) * 100), color: colors[b.label] || '#8c9eb5' }));
});
</script>
