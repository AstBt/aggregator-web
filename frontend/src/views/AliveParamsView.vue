<template>
  <div>
    <div class="card">
      <div class="card-hd"><h3>核心参数</h3><span class="extra">滑块调整，创建任务时预填</span></div>
      <div class="slider-row">
        <div class="s-lb">节点验活超时<small>timeout · 单次探测最长等待</small></div>
        <a-slider v-model:value="form.timeout" :min="500" :max="30000" :step="500" style="max-width:320px" />
        <div class="s-val">{{ form.timeout }} ms</div>
      </div>
      <div class="slider-row">
        <div class="s-lb">最大存活延迟<small>delay · 阈值，实测超过即判失效</small></div>
        <a-slider v-model:value="form.max_delay" :min="500" :max="15000" :step="500" style="max-width:320px" />
        <div class="s-val">{{ form.max_delay }} ms</div>
      </div>
      <div class="slider-row">
        <div class="s-lb">验活线程数<small>num_threads</small></div>
        <a-slider v-model:value="form.num_threads" :min="1" :max="128" style="max-width:320px" />
        <div class="s-val">{{ form.num_threads }}</div>
      </div>
      <div class="slider-row">
        <div class="s-lb">HTTP 重试次数<small>retry</small></div>
        <a-slider v-model:value="form.retry" :min="1" :max="10" style="max-width:320px" />
        <div class="s-val">{{ form.retry }}</div>
      </div>
    </div>

    <div class="card">
      <div class="card-hd"><h3>测试 URL</h3><TestConnButton label="🔌 测试连通性" :on-run="testUrl" /></div>
      <div class="callout blue" style="margin-bottom:14px">
        🔀 两种探测路径不同：本页「测试连通性」在启用本地代理时<b>经代理</b>发出；<b>实际节点验活</b>由 mihomo 内核<b>经待测节点直连</b>，不经过本地代理。
      </div>
      <div style="margin-bottom:10px">
        <div v-for="(url, i) in form.test_urls" :key="url" style="display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px dashed #f2f3f5">
          <a-radio :checked="url === form.primary_test_url" @change="setPrimary(url)" />
          <a-input v-model:value="form.test_urls[i]" style="flex:1" />
          <span v-if="url === form.primary_test_url" class="tag info plain">生效中</span>
          <a v-else class="btn link" @click="setPrimary(url)">设为生效</a>
          <a class="btn link" style="color:var(--error)" @click="removeUrl(url)">删除</a>
        </div>
      </div>
      <div style="display:flex;gap:8px">
        <a-input v-model:value="newUrl" placeholder="https://… 输入后点击添加" style="max-width:420px" @keyup.enter="addUrl" />
        <a-button @click="addUrl">＋ 添加</a-button>
      </div>
    </div>

    <div class="card">
      <div class="card-hd"><h3>高级选项</h3></div>
      <div style="display:flex;gap:26px;flex-wrap:wrap">
        <label class="checkbox"><a-checkbox v-model:checked="form.regularize" /> 节点规范化（地区 / 住宅 IP 识别）</label>
        <label class="checkbox"><a-checkbox v-model:checked="form.keep_published_on_controller_error" /> 控制器故障时保留上轮已发布结果</label>
      </div>
      <div class="slider-hint" style="margin-top:10px">验活是回测 / 爬取+聚合模式的既定核心步骤，无需单独开关。</div>
    </div>

    <div class="card">
      <a-button type="primary" @click="save">保存参数</a-button>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { message } from 'ant-design-vue';

import { params as paramsApi } from '../api';
import TestConnButton from '../components/TestConnButton.vue';

const form = reactive({
  timeout: 5000, max_delay: 5000, num_threads: 64, retry: 3,
  test_urls: [], primary_test_url: '', regularize: true, keep_published_on_controller_error: true,
});
const newUrl = ref('');

async function load() {
  const data = await paramsApi.readAlive();
  Object.assign(form, data);
  if (!form.primary_test_url) form.primary_test_url = form.test_urls?.[0] || '';
}
async function save() {
  await paramsApi.writeAlive(form);
  message.success('验活参数已保存');
}
function setPrimary(url) {
  form.primary_test_url = url;
}
async function addUrl() {
  const url = newUrl.value.trim();
  if (!/^https?:\/\//.test(url)) return message.error('请输入合法的 http(s) 地址');
  if (!form.test_urls.includes(url)) form.test_urls.push(url);
  if (!form.primary_test_url) form.primary_test_url = url;
  newUrl.value = '';
  await save();
}
async function removeUrl(url) {
  if (form.test_urls.length <= 1) return message.error('至少保留一个测试 URL');
  form.test_urls = form.test_urls.filter((u) => u !== url);
  if (form.primary_test_url === url) form.primary_test_url = form.test_urls[0];
  await save();
}
const testUrl = () => paramsApi.testUrl(form.primary_test_url || form.test_urls[0]);
onMounted(load);
</script>
