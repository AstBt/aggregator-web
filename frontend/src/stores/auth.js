import { defineStore } from 'pinia';

import * as api from '../api';

const ROLE_RANK = { viewer: 0, operator: 1, admin: 2 };

export const useAuthStore = defineStore('auth', {
  state: () => ({ user: null, loaded: false }),
  getters: {
    role: (s) => s.user?.role || 'viewer',
    atLeast: (s) => (role) => ROLE_RANK[s.user?.role || 'viewer'] >= ROLE_RANK[role],
  },
  actions: {
    async login(username, password) {
      const data = await api.auth.login({ username, password });
      sessionStorage.setItem('agg_token', data.accessToken);
      await this.loadMe();
      return data;
    },
    async loadMe() {
      this.user = await api.auth.me();
      this.loaded = true;
    },
    async logout() {
      try {
        await api.auth.logout();
      } finally {
        sessionStorage.removeItem('agg_token');
        this.user = null;
      }
    },
  },
});
