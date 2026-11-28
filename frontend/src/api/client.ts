import axios from 'axios';

export const API_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

const client = axios.create({
  baseURL: API_URL,
  timeout: 120000, // 2 minutes (e.g. for uploads/indexing checks)
  withCredentials: true,
});

// Interceptor to handle auth errors (401)
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response && error.response.status === 401) {
      window.dispatchEvent(new CustomEvent('finsight:unauthorized'));
      const url = String(error.config?.url || '');
      const isSessionProbe = url.includes('/auth/me');
      if (!isSessionProbe && !window.location.pathname.includes('/login')) {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export default client;
