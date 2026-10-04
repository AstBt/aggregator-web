<template>
  <div>
    <div class="card">
      <div class="card-hd"><h3>过滤规则</h3><span class="extra">对所有源生效</span></div>
      <div class="callout gray" style="margin-bottom:14px">
        合并顺序：<b>源级 exclude</b>（最高）→ <b>任务级默认过滤</b> → <b>全局 exclude</b>（最低），命中任一层即丢弃。
      </div>
      <div class="form-grid">
        <div class="form-item">
          <label>全局排除正则 <span class="hint">exclude</span></label>
          <a-input v-model:value="form.exclude" placeholder="留空不限制" />
        </div>
        <div class="form-item">
          <label>默认包含正则 <span class="hint">include</span></label>
          <a-input v-model:value="form.include" placeholder="留空不限制" />
        </div>
        <div class="form-item">
          <label>最大连续失败次数 <span class="hint">max_fails</span></label>
          <a-slider v-model:value="form.max_fails" :min="1" :max="20" style="max-width:280px" />
          <span class="s-val">{{ form.max_fails }}</span>
        </div>
        <div class="form-item">
          <label>结果包含原始节点 <span class="hint">include_nodes</span></label>
          <a-switch v-model:checked="form.include_nodes" />
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-hd">
        <h3>🌐 本地代理</h3>
        <TestConnButton label="🔌 测试连接" :on-run="testProxy" />
      </div>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
        <a-switch v-model:checked="proxy.enable" />
        <div><div style="font-size:13px;font-weight:500">启用代理（用于被墙数据源的直连回退）</div>
        <div class="slider-hint">仅对爬取阶段请求生效；节点验活始终经节点直连</div></div>
      </div>
      <div class="form-grid">
        <div class="form-item"><label>代理地址</label><a-input v-model:value="proxy.address" /></div>
        <div class="form-item"><label>代理探测地址</label><a-input v-model:value="proxy.test_url" /></div>
      </div>
    </div>

    <div class="card">
      <div style="display:flex;gap:10px">
        <a-button type="primary" @click="save">保存参数</a-button>
        <a-button @click="load">恢复默认</a-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { message } from 'ant-design-vue';

import { params as paramsApi } from '../api';
import TestConnButton from '../components/TestConnButton.vue';

const form = reactive({ exclude: '', include: '', max_fails: 5, include_nodes: true });
const proxy = reactive({ enable: false, address: 'http://127.0.0.1:7897', test_url: 'https://api.github.com/zen' });

async function load() {
  const data = await paramsApi.readCrawl();
  Object.assign(form, { exclude: data.exclude || '', include: data.include || '', max_fails: data.max_fails ?? 5, include_nodes: data.include_nodes ?? true });
  Object.assign(proxy, data.proxy || {});
}
async function save() {
  await paramsApi.writeCrawl({ ...form, proxy });
  message.success('参数已保存，对下一次创建的任务生效');
}
const testProxy = () => paramsApi.testProxy();
onMounted(load);
</script>
