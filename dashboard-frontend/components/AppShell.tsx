'use client';

import React, { useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import Navbar from '@/components/Navbar';
import { useAuth } from '@/lib/AuthContext';
import NotificationManager from '@/components/NotificationManager';


const ADMIN_ROUTES = ['/users', '/control'];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { loading, isAuthenticated, isAdmin } = useAuth();

  const isLoginPage = pathname === '/login';
  const isDocumentosPage = pathname?.startsWith('/documentos');
  const requiresAdmin = ADMIN_ROUTES.some((prefix: string) => pathname?.startsWith(prefix));

  useEffect(() => {
    if (loading) return;
    if (!isAuthenticated && !isLoginPage && !isDocumentosPage) {
      router.replace('/login');
      return;
    }
    if (isAuthenticated && isLoginPage) {
      router.replace('/');
      return;
    }
    if (isAuthenticated && requiresAdmin && !isAdmin) {
      router.replace('/');
    }
  }, [loading, isAuthenticated, isLoginPage, isDocumentosPage, requiresAdmin, isAdmin, router]);

  if (loading && !isLoginPage && !isDocumentosPage) {
    return (
      <main className="min-h-screen flex items-center justify-center">
        <div className="text-sm text-muted-foreground">Cargando sesión...</div>
      </main>
    );
  }

  if (!isLoginPage && !isDocumentosPage && !isAuthenticated) {
    return null;
  }

  return (
    <>
      <NotificationManager />
      {!isLoginPage && <Navbar />}
      <main className={isLoginPage ? 'min-h-screen' : 'pt-24 pb-12 container mx-auto px-4'}>
        {children}
      </main>
    </>
  );
}
