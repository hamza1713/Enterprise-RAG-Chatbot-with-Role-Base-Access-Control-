import { create } from 'zustand';
import client from '../api/client';
import type { AuthProvidersResponse } from '../types';

interface AuthState {
  username: string | null;
  role: string | null;
  authProvider: string | null;
  isAuthenticated: boolean;
  authReady: boolean;
  providers: AuthProvidersResponse | null;
  hydrateSession: () => Promise<void>;
  fetchProviders: () => Promise<AuthProvidersResponse>;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  clearLocalSession: () => void;
}

export const useAuthStore = create<AuthState>()((set) => ({
  username: null,
  role: null,
  authProvider: null,
  isAuthenticated: false,
  authReady: false,
  providers: null,

  hydrateSession: async () => {
    try {
      const res = await client.get<{ username: string; role: string; auth_provider?: string }>(
        '/auth/me',
        { timeout: 10000 }
      );
      set({
        username: res.data.username,
        role: res.data.role || 'General',
        authProvider: res.data.auth_provider || 'local',
        isAuthenticated: true,
        authReady: true,
      });
    } catch {
      set({
        username: null,
        role: null,
        authProvider: null,
        isAuthenticated: false,
        authReady: true,
      });
    }
  },

  fetchProviders: async () => {
    try {
      const res = await client.get<AuthProvidersResponse>('/auth/providers', { timeout: 8000 });
      set({ providers: res.data });
      return res.data;
    } catch {
      const fallback: AuthProvidersResponse = {
        local_enabled: true,
        oidc_enabled: false,
        provider_name: 'Enterprise SSO',
      };
      set({ providers: fallback });
      return fallback;
    }
  },

  login: async (username, password) => {
    const response = await client.post<{
      user: { username: string; role: string; auth_provider?: string };
      role: string;
    }>(
      '/auth/login',
      { username: username.trim(), password },
      { timeout: 15000 }
    );
    const u = response.data.user;
    set({
      username: u?.username || username.trim(),
      role: u?.role || response.data.role || 'General',
      authProvider: u?.auth_provider || 'local',
      isAuthenticated: true,
      authReady: true,
    });
  },

  logout: async () => {
    try {
      await client.post('/auth/logout');
    } catch {
      // Cookie clearing on client store continues regardless
    }
    set({
      username: null,
      role: null,
      authProvider: null,
      isAuthenticated: false,
      authReady: true,
    });
  },

  clearLocalSession: () => {
    set({
      username: null,
      role: null,
      authProvider: null,
      isAuthenticated: false,
      authReady: true,
    });
  },
}));
