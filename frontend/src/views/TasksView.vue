<template>
  <div class="task-layout">
    <!-- 左：任务列表 -->
    <section class="card" style="position:sticky;top:78px">
      <div class="card-hd">
        <h3>任务列表</h3>
        <a-button type="primary" size="small" @click="openCreate">＋ 创建任务</a-button>
      </div>
      <div class="seg" style="margin-bottom:12px">
        <a-radio-group v-model:value="statusFilter" button-style="solid" size="small">
          <a-radio-button value="all">全部</a-radio-button>
          <a-radio-button value="running">运行中</a-radio-button>
          <a-radio-button value="success">成功</a-radio-button>
          <a-radio-button value="failed">失败</a-radio-button>
        </a-radio-group>
      </div>
      <div class="tbl-wrap" style="max-height:600px;overflow-y:auto">
        <table class="tbl">
          <thead><tr><th>ID</th><th>模式</th><th>触发</th><th>状态</th><th>阶段</th><th>开始时间</th></tr></thead>
          <tbody>
            <tr v-for="t in filtered" :key="t.id" class="task-row" :class="{ sel: t.id === current?.id }" @click="select(t.id)">
              <td class="mono">#{{ t.id }}</td><td>{{ modeLabel(t.mode) }}</td><td>{{ t.trigger === 'schedule' ? '定时' : '手动' }}</td>
              <td><span class="tag" :class="statusClass(t.status)">{{ statusLabel(t.status) }}</span></td>
              <td class="muted" style="font-size:12px">{{ t.stage === 'done' ? '已完成' : t.progress ? Object.values(t.progress)[0] : t.stage }}</td>
              <td class="muted">{{ fmtTime(t.started_at) }}</td>
            </tr>
            <tr v-if="!filtered.length"><td colspan="6" class="empty-tip">没有符合条件的任务</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- 右：任务详情 -->
    <section class="card" v-if="current">
      <div class="card-hd">
        <h3>#{{ current.id }} · {{ modeLabel(current.mode) }}</h3>
        <div class="detail-actions">
          <span v-html="statusTag(current.status)"></span>
          <a-button v-if="current.status === 'running'" size="small" danger @click="cancel">⏹ 取消任务</a-button>
          <a-button size="small" @click="downloadLogs">⤓ 日志</a-button>
        </div>
      </div>
      <div class="stage-line">
        <div v-for="s in stages" :key="s" class="stage" :class="stageClass(s)"><span class="s-dot">{{ stageIdx(s) }}</span>{{ stageLabel(s) }}</div>
      </div>
      <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--text-3);margin-top:8px">
        <span>{{ progressText }}</span><span>已运行 {{ fmtDuration(current.duration_ms) }}</span>
      </div>
      <div class="pbar" style="margin-top:6px"><i :style="{ width: progressPct + '%' }"></i></div>
      <div class="run-meta" v-if="current.stats">
        <span class="chip" v-if="current.stats.subs_alive != null"><b>{{ current.stats.subs_alive }}</b>存活订阅</span>
        <span class="chip" v-if="current.stats.nodes_alive != null"><b>{{ current.stats.nodes_alive }}</b>存活节点</span>
        <span class="chip" v-if="current.stats.nodes_total != null"><b>{{ current.stats.nodes_total }}</b>抓取节点</span>
        <span class="chip"><b>{{ artifacts.length }}</b>产物</span>
      </div>
      <div class="detail-tabs">
        <div class="dt" :class="{ on: tab === 'log' }" @click="tab = 'log'">实时日志</div>
        <div class="dt" :class="{ on: tab === 'params' }" @click="tab = 'params'">运行参数</div>
        <div class="dt" :class="{ on: tab === 'arts' }" @click="tab = 'arts'">产物</div>
      </div>
      <div v-show="tab === 'log'">
        <div class="log-ctl" style="margin-bottom:10px">
          <label class="checkbox"><input type="checkbox" v-model="autoscroll" /> 自动滚动</label>
          <label class="checkbox"><input type="checkbox" v-model="onlyWarn" /> 仅看警告/错误</label>
          <span class="chip" style="padding:3px 10px"><span class="dot-live" v-if="current.status === 'running'"></span>{{ current.status === 'running' ? '实时' : '已结束' }}</span>
        </div>
        <div class="log-box log-pane" ref="logbox">
          <div v-for="l in visibleLogs" :key="l.id" class="log-line" :data-lv="l.level">
            <span class="ts">{{ l.created_at?.replace('T', ' ').slice(11, 19) }}</span>
            <span :class="'lv-' + l.level">{{ l.level }}</span>
            <span class="msg">{{ l.source }} {{ l.message }}</span>
          </div>
        </div>
      </div>
      <div v-show="tab === 'params'" class="param-list">
        <div class="kv-row" v-for="(v, k) in paramRows" :key="k"><span class="k">{{ k }}</span><span class="v">{{ v }}</span></div>
      </div>
      <div v-show="tab === 'arts'">
        <div v-if="current.publish_pending?.length" class="callout warn" style="margin-bottom:12px">
          ⚠️ 准原子发布中断：目标 <b>{{ current.publish_pending.join('、') }}</b> 未写入成功，系统库数据已可用。
          <div style="margin-top:8px"><a-button type="primary" size="small" @click="retryPublish">⟳ 重试发布</a-button></div>
        </div>
        <div v-for="a in artifacts" :key="a.id" class="kv-row" style="align-items:center">
          <span class="k">{{ a.target }}</span>
          <span class="v"><span class="mono">{{ a.path.split(/[\\/]/).pop() }}</span> <span class="muted">· {{ (a.size / 1024).toFixed(1) }} KB</span></span>
          <a class="btn link" style="margin-left:auto" @click="downloadArtifact(a)">下载</a>
        </div>
        <div v-if="!artifacts.length" class="empty-tip">本轮无产物</div>
      </div>
    </section>
    <section v-else class="card"><div class="empty-tip">选择左侧任务查看详情</div></section>
  </div>

  <!-- ============ 创建任务弹窗 ============ -->
  <a-modal v-model:open="createOpen" :title="editingSchedule ? '编辑定时任务' : scheduled ? '创建定时任务' : '创建任务'" width="880px" @ok="submit" :ok-text="editingSchedule ? '保存' : scheduled ? '创建定时任务' : '创建任务'" :confirm-loading="submitting">
    <div class="section-title">运行模式</div>
    <div class="radio-cards c3">
      <div class="radio-card" :class="{ sel: draft.mode === 'crawl' }" @click="draft.mode = 'crawl'">
        <h5>🕷️ 仅爬取</h5><p>跑取源并验证订阅，结果入系统库；不绑定存储目标</p>
      </div>
      <div class="radio-card" :class="{ sel: draft.mode === 'aggregate' }" @click="draft.mode = 'aggregate'">
        <h5>🧬 回测</h5><p>不爬取：从系统库读上轮订阅池与 remains → 重新拉取 → 验活 → 写入绑定目标</p>
      </div>
      <div class="radio-card" :class="{ sel: draft.mode === 'full' }" @click="draft.mode = 'full'">
        <h5>⚡ 爬取 + 聚合</h5><p>完整流程：爬取 → 与系统库订阅池及 remains 合并 → 验活 → 转换 → 写入绑定目标</p>
      </div>
    </div>

    <div class="section-title" style="margin-top:18px">运行参数（默认值取自验活参数页，可临时覆盖）</div>
    <div class="slider-row">
      <div class="s-lb">线程数<small>num_threads</small></div>
      <a-slider v-model:value="draft.num_threads" :min="1" :max="128" style="max-width:300px" />
      <div class="s-val">{{ draft.num_threads }}</div>
    </div>
    <div class="slider-row">
      <div class="s-lb">最大存活延迟<small>delay · 阈值，实测超过即判失效</small></div>
      <a-slider v-model:value="draft.max_delay" :min="500" :max="15000" :step="500" style="max-width:300px" />
      <div class="s-val">{{ draft.max_delay }} ms</div>
    </div>
    <div class="slider-row">
      <div class="s-lb">验活超时<small>timeout · 单次探测最长等待</small></div>
      <a-slider v-model:value="draft.timeout" :min="500" :max="30000" :step="500" style="max-width:300px" />
      <div class="s-val">{{ draft.timeout }} ms</div>
    </div>
    <div class="slider-hint">验活探测地址统一使用「验活参数」页配置的测试 URL。</div>

    <div class="section-title" style="margin-top:18px">存储目标绑定 <span style="font-weight:400;font-size:12px;color:var(--text-3)">回测 / 爬取+聚合模式必填</span></div>
    <div v-if="draft.mode === 'crawl'" class="callout gray">仅爬取模式<b>不绑定存储目标</b>：本轮订阅写入系统库供浏览，不推送任何目标、不读取旧数据。</div>
    <template v-else>
      <div class="callout gray" style="margin-bottom:12px">
        🔌 点击卡片选择本轮<b>写入</b>目标（可多选）。旧数据（订阅池 / remains）一律来自<b>系统库</b>，与绑定目标无关。绑定多目标时验活结果分别完整写入每个目标；发布为准原子，失败后可在详情页补偿重试。
      </div>
      <div class="bind-grid">
        <div v-for="t in targets" :key="t.id" class="bind-card" :class="{ sel: !!bound[t.id], disabled: !t.enable }" @click="toggleBind(t)">
          <span class="b-check">{{ bound[t.id] ? '✓' : '' }}</span>
          <div class="b-ico" :style="{ background: t.type === 'local' ? '#e6f4ff' : '#f6ffed' }">{{ t.type === 'local' ? '📁' : '🐙' }}</div>
          <h5>{{ t.name }} <span v-if="!t.enable" class="tag gray plain" style="font-size:10px">已停用</span></h5>
          <p>{{ t.type_name }}{{ t.enable ? '' : ' · 需先在结果存储中启用' }}</p>
        </div>
      </div>
    </template>

    <template v-if="draft.mode !== 'aggregate'">
      <div class="section-title" style="margin-top:18px">执行范围 <span style="font-weight:400;font-size:12px;color:var(--text-3)">按源类型分组选择，组内可细分</span></div>
      <div class="scope-summary">
        <span>已选 {{ selectedSourceCount }} / {{ totalSourceCount }} 个源</span>
        <a class="btn link" @click="scopeAll(true)">全选</a>
        <a class="btn link" @click="scopeAll(false)">全不选</a>
      </div>
      <div class="grp-grid">
        <div v-for="g in sourceGroups" :key="g.key" class="grp-card" :class="{ sel: groupState(g) === 'all', partial: groupState(g) === 'partial' }" @click="toggleGroup(g)">
          <span class="g-state">{{ groupState(g) === 'none' ? '' : '✓' }}</span>
          <div class="g-ico" :style="{ background: g.bg }">{{ g.icon }}</div>
          <h5>{{ g.label }}</h5><p>{{ groupSelected(g) }} / {{ g.sources.length }} 个源</p>
        </div>
      </div>
      <div v-if="openGroup" class="grp-detail">
        <div class="gd-hd"><span>{{ openGroup.icon }} {{ openGroup.label }}</span><a class="btn link" @click="grpToggleAll">全选 / 反选</a></div>
        <label v-for="s in openGroup.sources" :key="s.id">
          <input type="checkbox" v-model="sourceSel[s.id]" @change="refreshGroups" /> {{ s.name }} <span class="t">{{ s.enable ? '启用' : '已停用' }}</span>
        </label>
      </div>
    </template>
    <div v-else class="callout gray" style="margin-top:18px">回测模式不执行爬取，沿用系统库中的上轮订阅池与 remains。</div>

    <div class="section-title" style="margin-top:18px">执行方式</div>
    <div class="radio-cards c2">
      <div class="radio-card" :class="{ sel: !scheduled }" @click="scheduled = false"><h5>▶ 立即执行</h5><p>提交后立即开始运行</p></div>
      <div class="radio-card" :class="{ sel: scheduled }" @click="scheduled = true"><h5>⏰ 定时执行</h5><p>按间隔周期自动触发，图形化选择，无需手写表达式</p></div>
    </div>
    <div v-if="scheduled" style="margin-top:12px">
      <div class="sched-grid">
        <div v-for="k in SCHED_KINDS" :key="k.key" class="sched-opt" :class="{ sel: sched.kind === k.key }" @click="sched.kind = k.key">{{ k.label }}</div>
      </div>
      <div class="sched-fields">
        <template v-if="['minute','hour','day','week'].includes(sched.kind)">
          <div class="stepper"><button @click="sched.n = Math.max(1, sched.n - 1)">－</button><input v-model.number="sched.n" /><button @click="sched.n + 1">＋</button></div>
          <span>{{ unitLabel }}</span>
        </template>
        <input v-if="['day','daily','weekly'].includes(sched.kind)" type="time" class="time-input" v-model="sched.time" />
        <div v-if="['week','weekly'].includes(sched.kind)" class="week-pick">
          <span v-for="(w, i) in ['一','二','三','四','五','六','日']" :key="w" :class="{ on: sched.weekdays.includes(i + 1) }" @click="toggleWeek(i + 1)">{{ w }}</span>
        </div>
      </div>
      <div class="sched-preview">⏰ {{ schedPreview }}</div>
    </div>
  </a-modal>

  <!-- ============ 定时任务管理 ============ -->
  <section class="card" style="margin-top:16px">
    <div class="card-hd">
      <h3>定时任务</h3>
      <a-button type="primary" size="small" @click="openSchedule">＋ 新建定时</a-button>
    </div>
    <div class="callout gray" style="margin-bottom:14px">
      在创建任务弹窗选择「定时执行」即保存为定时任务（不立即产生 run）；到期由系统自动生成执行记录。周期为人类可读的间隔描述，无需填写 cron 表达式。
      <span v-if="scheduleRows.some((s) => s.disabled_reason)" style="color:var(--warning-tx)">
        有任务因执行器占用被跳过，将在下一周期恢复。
      </span>
    </div>
    <div class="tbl-wrap">
      <table class="tbl">
        <thead><tr><th>名称</th><th>周期</th><th>模式</th><th>绑定目标</th><th>启用</th><th>最近执行</th><th style="width:150px">操作</th></tr></thead>
        <tbody>
          <tr v-for="s in scheduleRows" :key="s.id">
            <td><b>{{ s.name }}</b><span v-if="s.disabled_reason" class="tag warn plain" style="margin-left:6px;font-size:10px">本轮跳过</span></td>
            <td>{{ schedDescribe(s.params?.spec) || s.cron }}</td>
            <td>{{ modeLabel(s.mode) }}</td>
            <td class="mono" style="font-size:11.5px">{{ (s.params?.bind_target_ids || []).map((id) => targets.find((t) => t.id === id)?.name || id).join(' + ') || '—（不绑定）' }}</td>
            <td><span class="switch" :class="{ on: s.enable }" @click="onToggleSchedule(s)"></span></td>
            <td class="muted">{{ fmtTime(s.last_run_at) }}</td>
            <td class="acts">
              <a class="btn link" @click="editSchedule(s)">编辑</a>
              <a class="btn link" style="color:var(--error)" @click="onRemoveSchedule(s)">删除</a>
            </td>
          </tr>
          <tr v-if="!scheduleRows.length"><td colspan="7" class="empty-tip">暂无定时任务</td></tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch, nextTick } from 'vue';
import { Modal, message } from 'ant-design-vue';

import { params as paramsApi, results as resultsApi, schedules as schedulesApi, storage as storageApi, tasks as tasksApi } from '../api';

const MODE = { crawl: '仅爬取', aggregate: '回测', full: '爬取+聚合' };
const STATUS = { running: '运行中', success: '成功', failed: '失败', cancelled: '已取消', 'partial-success': '部分发布', pending: '等待中' };
const STAGE_LIST = {
  crawl: ['init', 'crawl', 'done'],
  aggregate: ['init', 'fetch', 'check', 'convert', 'publish', 'done'],
  full: ['init', 'crawl', 'fetch', 'check', 'convert', 'publish', 'done'],
};
const STAGE_LABEL = { init: '初始化', crawl: '爬取源', validate: '订阅验证', fetch: '节点拉取', check: '验活', convert: '转换', publish: '发布', done: '完成' };
const GROUP_META = {
  telegram: ['📨', 'Telegram', '#e6f4ff'], github: ['🐙', 'GitHub 搜索', '#f6ffed'], gist: ['📄', 'Gist 时间线', '#f6ffed'],
  google: ['🔍', 'Google 搜索', '#fff7e6'], yandex: ['🔎', 'Yandex 搜索', '#fff7e6'], page: ['🌐', '通用网页', '#f9f0ff'],
  repo: ['📦', 'GitHub 仓库', '#f6ffed'], script: ['🧪', '脚本插件', '#fff2f0'],
};
const SCHED_KINDS = [
  { key: 'minute', label: '⏱️ 分钟级 · 每 N 分钟' }, { key: 'hour', label: '🕐 小时级 · 每 N 小时' },
  { key: 'day', label: '📅 天级 · 每 N 天' }, { key: 'week', label: '🗓️ 周级 · 每 N 周' },
  { key: 'daily', label: '🌅 每天几点' }, { key: 'weekly', label: '📆 每周几' },
];

const runs = ref([]);
const statusFilter = ref('all');
const current = ref(null);
const logs = ref([]);
const artifacts = ref([]);
const tab = ref('log');
const autoscroll = ref(true);
const onlyWarn = ref(false);
const logbox = ref(null);
const targets = ref([]);
const sourceRows = ref([]);
const sourceSel = ref({});
const openGroup = ref(null);
const bound = ref({});
const createOpen = ref(false);
const submitting = ref(false);
const scheduled = ref(false);
const scheduleRows = ref([]);
const editingSchedule = ref(null);
const sched = reactive({ kind: 'minute', n: 30, time: '09:00', weekdays: [1] });
const draft = reactive({ mode: 'full', num_threads: 64, max_delay: 5000, timeout: 5000 });

const filtered = computed(() => (statusFilter.value === 'all' ? runs.value : runs.value.filter((r) => r.status === statusFilter.value)));
const stages = computed(() => STAGE_LIST[current.value?.mode || 'crawl']);
const paramRows = computed(() => {
  const p = current.value?.params || {};
  const rows = { 模式: MODE[current.value?.mode], 线程数: p.num_threads, 最大存活延迟: (p.max_delay || '—') + ' ms', 验活超时: (p.timeout || '—') + ' ms' };
  if (p.bind_target_ids?.length) rows['绑定目标'] = (p.bind_target_ids || []).map((id) => targets.value.find((t) => t.id === id)?.name || id).join(' + ');
  else rows['绑定目标'] = '—（不绑定）';
  return rows;
});
const visibleLogs = computed(() => (onlyWarn.value ? logs.value.filter((l) => l.level !== 'INFO' && l.level !== 'DEBUG') : logs.value));

const sourceGroups = computed(() => {
  const groups = {};
  for (const s of sourceRows.value) (groups[s.type] ||= []).push(s);
  return Object.entries(groups).map(([key, list]) => ({ key, sources: list, ...Object.fromEntries([['icon', GROUP_META[key]?.[0] || '🧩'], ['label', GROUP_META[key]?.[1] || key], ['bg', GROUP_META[key]?.[2] || '#f5f5f5']]) }));
});
const totalSourceCount = computed(() => sourceRows.value.length);
const selectedSourceCount = computed(() => Object.values(sourceSel.value).filter(Boolean).length);
const groupSelected = (g) => g.sources.filter((s) => sourceSel.value[s.id]).length;
const groupState = (g) => {
  const n = groupSelected(g);
  return n === 0 ? 'none' : n === g.sources.length ? 'all' : 'partial';
};
function toggleGroup(g) {
  const target = groupState(g) === 'all' ? false : true;
  g.sources.forEach((s) => { if (s.enable) sourceSel.value[s.id] = target; });
  openGroup.value = openGroup.value?.key === g.key ? null : g;
}
function grpToggleAll() {
  const g = openGroup.value;
  const target = groupSelected(g) !== g.sources.length;
  g.sources.forEach((s) => { if (s.enable) sourceSel.value[s.id] = target; });
}
function scopeAll(all) { sourceRows.value.forEach((s) => { if (s.enable) sourceSel.value[s.id] = all; }); }
function refreshGroups() {}
function toggleBind(t) { if (t.enable) bound.value[t.id] = !bound.value[t.id]; }

const unitLabel = computed(() => ({ minute: '分钟', hour: '小时', day: '天', week: '周' }[sched.kind] || ''));
const schedPreview = computed(() => {
  const wd = (sched.weekdays || []).map((d) => '周' + ['一','二','三','四','五','六','日'][d - 1]).join('');
  const T = sched.time;
  const N = Math.max(1, sched.n || 1);
  if (sched.kind === 'minute') return `每 ${N} 分钟执行一次`;
  if (sched.kind === 'hour') return `每 ${N} 小时执行一次`;
  if (sched.kind === 'day') return `每 ${N} 天的 ${T} 执行`;
  if (sched.kind === 'week') return `每 ${N} 周的${wd}执行`;
  if (sched.kind === 'daily') return `每天 ${T} 执行`;
  return `每周${wd}的 ${T} 执行`;
});
function toggleWeek(w) {
  sched.weekdays = sched.weekdays.includes(w) ? sched.weekdays.filter((d) => d !== w) : [...sched.weekdays, w].sort();
  if (!sched.weekdays.length) sched.weekdays = [w];
}

const modeLabel = (m) => MODE[m] || m;
const statusLabel = (s) => STATUS[s] || s;
const statusClass = (s) => ({ running: 'info', success: 'ok', failed: 'err', cancelled: 'gray', 'partial-success': 'warn', pending: 'warn' }[s] || 'gray');
const statusTag = (s) => `<span class="tag ${statusClass(s)}">${statusLabel(s)}</span>`;
const fmtTime = (iso) => (iso ? iso.replace('T', ' ').slice(5, 16) : '—');
const fmtDuration = (ms) => (ms == null ? '—' : ms < 60000 ? (ms / 1000).toFixed(1) + 's' : Math.floor(ms / 60000) + 'm' + Math.round((ms % 60000) / 1000) + 's');
const stageLabel = (s) => STAGE_LABEL[s] || s;
const stageIdx = (s) => stages.value.indexOf(s) + 1;

const stageReached = computed(() => {
  const t = current.value;
  if (!t) return -1;
  if (t.stage === 'done' || t.status === 'success') return stages.value.length;
  const idx = stages.value.indexOf(t.stage);
  return idx === -1 ? 0 : idx;
});
function stageClass(s) {
  const idx = stages.value.indexOf(s);
  const reached = stageReached.value;
  if (idx < reached) return 'done';
  if (current.value?.status === 'running' && idx === reached) return 'cur';
  if (['failed', 'cancelled', 'partial-success'].includes(current.value?.status) && idx === reached) return 'failed';
  return '';
}
const progressText = computed(() => {
  const t = current.value;
  if (!t) return '';
  if (t.stage === 'done') return '100%';
  const p = t.progress && Object.values(t.progress)[0];
  return p ? `${STAGE_LABEL[t.stage] || t.stage} ${p}` : STAGE_LABEL[t.stage] || t.stage || '';
});
const progressPct = computed(() => {
  const t = current.value;
  if (!t) return 0;
  if (t.stage === 'done' || t.status === 'success') return 100;
  const p = t.progress && Object.values(t.progress)[0];
  if (p && p.includes('/')) {
    const [done, total] = p.split('/').map(Number);
    if (total > 0) return Math.round((done / total) * 100);
  }
  return Math.round((stageReached.value / Math.max(1, stages.value.length)) * 100);
});

let logTimer = null;
async function loadList() {
  runs.value = (await tasksApi.list({ page_size: 50 })).items;
  if (!current.value && runs.value.length) select(runs.value[0].id);
}
async function select(id) {
  clearInterval(logTimer);
  current.value = await tasksApi.detail(id);
  await loadLogs();
  artifacts.value = (await tasksApi.artifacts(id)).items;
  if (current.value.status === 'running' || current.value.status === 'pending') {
    logTimer = setInterval(pollRunning, 2000);
  }
  tab.value = 'log';
}
async function loadLogs() {
  logs.value = (await tasksApi.logs(current.value.id)).items;
  await nextTick();
  if (autoscroll.value && logbox.value) logbox.value.scrollTop = logbox.value.scrollHeight;
}
async function pollRunning() {
  const t = current.value;
  if (!t) return clearInterval(logTimer);
  current.value = await tasksApi.detail(t.id);
  const before = logs.value.length;
  logs.value = (await tasksApi.logs(t.id)).items;
  await nextTick();
  if (autoscroll.value && logbox.value) logbox.value.scrollTop = logbox.value.scrollHeight;
  if (!['running', 'pending'].includes(current.value.status)) {
    clearInterval(logTimer);
    artifacts.value = (await tasksApi.artifacts(t.id)).items;
    loadList();
  }
}
watch([autoscroll], async () => { await nextTick(); if (autoscroll.value && logbox.value) logbox.value.scrollTop = logbox.value.scrollHeight; });

async function cancel() {
  Modal.confirm({ title: '确认取消当前运行中的任务？', content: '已写入的数据不会回滚。', onOk: async () => { await tasksApi.cancel(current.value.id); message.success('已发送取消信号'); } });
}
async function retryPublish() {
  const r = await tasksApi.retryPublish(current.value.id);
  message.success(r.ok ? '补偿完成，任务已置为成功' : `仍有 ${r.remaining.length} 个目标失败`);
  await select(current.value.id);
}
function downloadArtifact(a) {
  const blob = new Blob([a.path], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  triggerDownload(url, a.path.split(/[\\/]/).pop());
}
function downloadLogs() {
  const text = logs.value.map((l) => `${l.created_at} ${l.level} ${l.source} ${l.message}`).join('\n');
  triggerDownload(URL.createObjectURL(new Blob([text], { type: 'text/plain' })), `run-${current.value.id}.log`);
}
function triggerDownload(url, filename) {
  const a = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

async function openCreate() {
  await prepareDraft();
  scheduled.value = false;
  editingSchedule.value = null;
  Object.assign(draft, { mode: 'full' });
  createOpen.value = true;
}
async function openSchedule() {
  await prepareDraft();
  scheduled.value = true;
  editingSchedule.value = null;
  Object.assign(draft, { mode: 'full' });
  Object.assign(sched, { kind: 'minute', n: 30, time: '09:00', weekdays: [1] });
  createOpen.value = true;
}
async function editSchedule(item) {
  await prepareDraft();
  scheduled.value = true;
  editingSchedule.value = item;
  const spec = item.params?.spec || {};
  const mode = ({ crawl: 'crawl', aggregate: 'aggregate', full: 'full' })[item.mode] || 'full';
  Object.assign(draft, { mode, num_threads: item.params?.num_threads ?? 64, max_delay: item.params?.max_delay ?? 5000, timeout: item.params?.timeout ?? 5000 });
  Object.assign(sched, { kind: spec.kind || 'minute', n: spec.n ?? 30, time: spec.time || '09:00', weekdays: spec.weekdays || [1] });
  bound.value = Object.fromEntries((item.params?.bind_target_ids || []).map((id) => [id, true]));
  createOpen.value = true;
}
async function prepareDraft() {
  const [alive, tgts] = await Promise.all([paramsApi.readAlive(), storageApi.list()]);
  Object.assign(draft, { num_threads: alive.num_threads ?? 64, max_delay: alive.max_delay ?? 5000, timeout: alive.timeout ?? 5000 });
  targets.value = tgts.items;
  sourceRows.value = (await (await import('../api')).sources.list({ page_size: 200 })).items;
  sourceSel.value = Object.fromEntries(sourceRows.value.filter((s) => s.enable).map((s) => [s.id, true]));
  bound.value = Object.fromEntries(tgts.items.filter((t) => t.enable).slice(0, 1).map((t) => [t.id, true]));
}
async function loadSchedules() {
  scheduleRows.value = (await schedulesApi.list()).items;
}
const schedDescribe = (spec) => {
  if (!spec) return '';
  const wd = (spec.weekdays || []).map((d) => '周' + ['一', '二', '三', '四', '五', '六', '日'][d - 1]).join('');
  const N = Math.max(1, spec.n ?? 1);
  const T = spec.time || '00:00';
  if (spec.kind === 'minute') return `每 ${N} 分钟`;
  if (spec.kind === 'hour') return `每 ${N} 小时`;
  if (spec.kind === 'day') return `每 ${N} 天的 ${T}`;
  if (spec.kind === 'week') return `每 ${N} 周的${wd}`;
  if (spec.kind === 'daily') return `每天 ${T}`;
  if (spec.kind === 'weekly') return `每周${wd}的 ${T}`;
  return spec.kind;
};
async function onToggleSchedule(s) {
  await schedulesApi.toggle(s.id);
  await loadSchedules();
}
async function onRemoveSchedule(s) {
  Modal.confirm({
    title: `确认删除定时任务 ${s.name}？`,
    content: '删除后不再自动执行，历史 run 记录保留。',
    okType: 'danger',
    onOk: async () => { await schedulesApi.remove(s.id); message.success('已删除'); await loadSchedules(); },
  });
}
async function submit() {
  if (draft.mode !== 'crawl') {
    const ids = Object.entries(bound.value).filter(([, v]) => v).map(([k]) => Number(k)).filter((id) => targets.value.find((t) => t.id === id)?.enable);
    if (!ids.length) return message.error('回测 / 爬取+聚合模式必须绑定至少一个存储目标');
    draft.bind_target_ids = ids;
  }
  const payload = { mode: draft.mode, params: { num_threads: draft.num_threads, max_delay: draft.max_delay, timeout: draft.timeout }, bind_target_ids: draft.bind_target_ids || [] };
  if (draft.mode !== 'aggregate') payload.source_ids = Object.entries(sourceSel.value).filter(([, v]) => v).map(([k]) => Number(k));
  try {
    submitting.value = true;
    if (scheduled.value) {
      const spec = { kind: sched.kind, n: sched.n, time: sched.time, weekdays: sched.weekdays };
      const body = {
        name: editingSchedule.value?.name || `定时-${draft.mode === 'full' ? '爬取+聚合' : modeLabel(draft.mode)}`,
        kind: spec.kind, n: spec.n, time: spec.time, weekdays: spec.weekdays,
        mode: draft.mode,
        params: { num_threads: draft.num_threads, max_delay: draft.max_delay, timeout: draft.timeout, spec },
        bind_target_ids: draft.bind_target_ids || [],
      };
      if (editingSchedule.value) await schedulesApi.update(editingSchedule.value.id, body);
      else await schedulesApi.create(body);
      message.success(editingSchedule.value ? '定时任务已更新' : '定时任务已创建（到期自动执行）');
      createOpen.value = false;
      await loadSchedules();
    } else {
      await tasksApi.create(payload);
      message.success('任务已创建');
      createOpen.value = false;
      await loadList();
    }
  } catch (error) {
    message.error(error.message);
  } finally {
    submitting.value = false;
  }
}

onMounted(() => { loadList(); loadSchedules(); });
onBeforeUnmount(() => clearInterval(logTimer));
</script>
