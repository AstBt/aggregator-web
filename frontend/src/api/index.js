import http from './http';

export const auth = {
  login: (data) => http.post('/auth/login', data),
  logout: () => http.post('/auth/logout'),
  me: () => http.get('/auth/me'),
  changePassword: (data) => http.put('/auth/password', data),
};

export const dashboard = {
  overview: () => http.get('/dashboard/overview'),
};

export const users = {
  list: (params) => http.get('/users', { params }),
  create: (data) => http.post('/users', data),
  update: (id, data) => http.put(`/users/${id}`, data),
  remove: (id) => http.delete(`/users/${id}`),
};

export const sources = {
  list: (params) => http.get('/sources', { params }),
  create: (data) => http.post('/sources', data),
  update: (id, data) => http.put(`/sources/${id}`, data),
  remove: (id) => http.delete(`/sources/${id}`),
  toggle: (id) => http.post(`/sources/${id}/toggle`),
  test: (id) => http.post(`/sources/${id}/test`),
  export: () => http.get('/sources/export'),
  import: (payload) => http.post('/sources/import', payload),
};

export const params = {
  readCrawl: () => http.get('/settings/crawl'),
  writeCrawl: (data) => http.put('/settings/crawl', data),
  testProxy: () => http.post('/settings/crawl/proxy/test'),
  readAlive: () => http.get('/settings/alive'),
  writeAlive: (data) => http.put('/settings/alive', data),
  addTestUrl: (url) => http.post('/settings/alive/test-urls', { url }),
  removeTestUrl: (url) => http.delete('/settings/alive/test-urls', { params: { url } }),
  testUrl: (url) => http.post('/settings/alive/test-url', null, { params: { url } }),
};

export const tasks = {
  list: (params) => http.get('/tasks', { params }),
  create: (data) => http.post('/tasks', data),
  detail: (id) => http.get(`/tasks/${id}`),
  logs: (id, since) => http.get(`/tasks/${id}/logs`, { params: { since } }),
  cancel: (id) => http.post(`/tasks/${id}/cancel`),
  retryPublish: (id) => http.post(`/tasks/${id}/retry-publish`),
  artifacts: (id) => http.get(`/tasks/${id}/artifacts`),
};

export const results = {
  subscriptions: (params) => http.get('/subscriptions', { params }),
  subscription: (id) => http.get(`/subscriptions/${id}`),
  nodes: (params) => http.get('/nodes', { params }),
  node: (id) => http.get(`/nodes/${id}`),
  export: (data) => http.post('/nodes/export', data),
};

export const storage = {
  list: () => http.get('/storage-targets'),
  create: (data) => http.post('/storage-targets', data),
  update: (id, data) => http.put(`/storage-targets/${id}`, data),
  remove: (id) => http.delete(`/storage-targets/${id}`),
  toggle: (id) => http.post(`/storage-targets/${id}/toggle`),
  test: (id) => http.post(`/storage-targets/${id}/test`),
};
