import axios from 'axios';

export const API_URL = 'http://localhost:8000';

const client = axios.create({
  baseURL: API_URL,
  timeout: 120000, // 2 minutes (e.g. for uploads/indexing checks)
});

// Interceptor to add Bearer Token
client.interceptors.request.use(
  (config) => {
    // Retrieve auth store token from sessionStorage
    try {
      const persistedState = sessionStorage.getItem('finsight_auth');
      if (persistedState) {
        const parsed = JSON.parse(persistedState);
        const token = parsed.state?.token;
        if (token) {
          config.headers.Authorization = `Bearer ${token}`;
        }
      }
    } catch (e) {
      console.error('Error reading auth token from sessionStorage', e);
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Interceptor to handle auth errors (401)
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response && error.response.status === 401) {
      // Clear token and redirect to login if unauthorized
      console.warn('API returned 401 Unauthorized, clearing session...');
      sessionStorage.removeItem('finsight_auth');
      // Only reload if not already on login page to avoid loops
      if (!window.location.pathname.includes('/login')) {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export default client;
