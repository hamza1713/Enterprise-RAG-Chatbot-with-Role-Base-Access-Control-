import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import axios from 'axios';
import { API_URL } from '../api/client';

interface AuthState {
  username: string | null;
  role: string | null;
  token: string | null;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      username: null,
      role: null,
      token: null,
      isAuthenticated: false,

      login: async (username, password) => {
        // Prepare Basic Auth credentials
        const authHeader = 'Basic ' + window.btoa(unescape(encodeURIComponent(`${username.trim()}:${password.trim()}`)));
        
        const response = await axios.get(`${API_URL}/login`, {
          headers: {
            Authorization: authHeader,
          },
        });

        const data = response.data;
        set({
          username: username.trim(),
          role: data.role || 'General',
          token: data.access_token,
          isAuthenticated: true,
        });
      },

      logout: () => {
        set({
          username: null,
          role: null,
          token: null,
          isAuthenticated: false,
        });
      },
    }),
    {
      name: 'finsight_auth',
      storage: createJSONStorage(() => sessionStorage),
    }
  )
);
