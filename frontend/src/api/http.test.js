import { describe, expect, it } from 'vitest';

import { getToken, setToken } from './http';

describe('token 会话管理', () => {
  it('设置后读取、清空后为空', () => {
    setToken('abc123');
    expect(getToken()).toBe('abc123');
    setToken('');
    expect(getToken()).toBe('');
  });
});
