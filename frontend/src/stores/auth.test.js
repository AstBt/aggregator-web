import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it } from 'vitest';

import { useAuthStore } from './auth';

describe('auth store RBAC', () => {
  beforeEach(() => setActivePinia(createPinia()));

  it('admin 拥有全部权限', () => {
    const store = useAuthStore();
    store.user = { role: 'admin' };
    expect(store.atLeast('admin')).toBe(true);
    expect(store.atLeast('operator')).toBe(true);
    expect(store.atLeast('viewer')).toBe(true);
  });

  it('operator 不可管理用户与存储目标', () => {
    const store = useAuthStore();
    store.user = { role: 'operator' };
    expect(store.atLeast('operator')).toBe(true);
    expect(store.atLeast('admin')).toBe(false);
  });

  it('未登录按 viewer 兜底且越权被拒', () => {
    const store = useAuthStore();
    store.user = null;
    expect(store.atLeast('viewer')).toBe(true);
    expect(store.atLeast('operator')).toBe(false);
  });
});
