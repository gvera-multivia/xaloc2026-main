'use client';

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { sessionApi } from '@/lib/api';

export type DashboardUser = {
  sub: string;
  username: string;
  role: 'admin' | 'user' | string;
};

type AuthContextType = {
  user: DashboardUser | null;
  loading: boolean;
  isAuthenticated: boolean;
  isAdmin: boolean;
  refresh: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<DashboardUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await sessionApi.me();
      setUser(data.user || null);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    await sessionApi.login(username, password);
    await refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    try {
      await sessionApi.logout();
    } finally {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const value = useMemo<AuthContextType>(
    () => ({
      user,
      loading,
      isAuthenticated: !!user,
      isAdmin: user?.role === 'admin',
      refresh,
      login,
      logout,
    }),
    [user, loading, refresh, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return ctx;
}
