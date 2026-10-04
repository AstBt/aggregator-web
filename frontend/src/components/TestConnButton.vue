<template>
  <div>
    <div class="test-conn" v-if="result.ok" style="margin-bottom:10px"><span class="test-result ok">✓ 连通正常 · HTTP {{ result.status }} · {{ result.cost_ms }}ms</span></div>
    <div class="test-conn" v-else-if="result.ok === false" style="margin-bottom:10px"><span class="test-result fail">✗ {{ result.error || ('HTTP ' + result.status) }}</span></div>
    <a-button size="small" :loading="testing" @click="run">{{ label }}</a-button>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import { message } from 'ant-design-vue';

const props = defineProps({ label: { default: '测试连接' }, onRun: { type: Function, required: true } });
const testing = ref(false);
const result = ref({});

const run = async () => {
  testing.value = true;
  try {
    result.value = await props.onRun();
    if (!result.value?.ok) message.warning(result.value?.detail || result.value?.error || '未通过');
  } catch (error) {
    result.value = { ok: false, error: error.message };
    message.error(error.message);
  } finally {
    testing.value = false;
  }
};
</script>
