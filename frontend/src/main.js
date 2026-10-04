import { createApp } from 'vue';
import { createPinia } from 'pinia';
import Antd from 'ant-design-vue';
import 'ant-design-vue/dist/reset.css';
import 'ant-design-vue/es/message/style';
import 'ant-design-vue/es/modal/style';

import App from './App.vue';
import router from './router';
import './styles/app.css';

createApp(App).use(createPinia()).use(router).use(Antd).mount('#app');
