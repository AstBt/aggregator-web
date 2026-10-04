import axios from 'axios';

const http = axios.create({ baseURL: '/api', timeout: 30000 });

const TOKEN_KEY = 'agg_token';

export function getToken() {
  return sessionStorage.getItem(TOKEN_KEY) || '';
}
export function setToken(token) {
  if (token) sessionStorage.setItem(TOKEN_KEY, token);
  else sessionStorage.removeItem(TOKEN_KEY);
}

http.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

http.interceptors.response.use(
  (resp) => {
    const body = resp.data;
    if (body && typeof body === 'object' && 'code' in body && 'data' in body) {
      if (body.code === 0) return body.data;
      const error = new Error(body.message || `请求失败(${body.code})`);
      error.code = body.code;
      return Promise.reject(error);
    }
    return body;
  },
  (error) => {
    if (error.response?.status === 401) {
      setToken('');
      if (!location.pathname.startsWith('/login')) location.assign('/login');
    }
    const message = error.response?.data?.message || error.message;
    return Promise.reject(new Error(message));
  }
);

export default http;
