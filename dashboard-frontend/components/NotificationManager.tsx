'use client';

import React, { useEffect, useRef, useState } from 'react';
import { authApi, blacklistApi } from '@/lib/api';
import { useAuth } from '@/lib/AuthContext';
import { sileo } from 'sileo';

const POLLING_INTERVAL = 30000; // 30 seconds

export default function NotificationManager() {
    const { isAuthenticated, loading } = useAuth();
    const [permission, setPermission] = useState<NotificationPermission>('default');
    const lastAuthId = useRef<number>(0);
    const lastBlacklistId = useRef<number>(0);

    const canUseBrowserNotifications = () =>
        typeof window !== 'undefined' && window.isSecureContext && 'Notification' in window;

    // Initialize permission state
    useEffect(() => {
        if (!canUseBrowserNotifications()) return;

        setPermission(window.Notification.permission);

        // Load last seen IDs from localStorage
        const savedAuthId = localStorage.getItem('lastSeenAuthId');
        if (savedAuthId) lastAuthId.current = parseInt(savedAuthId, 10);

        const savedBlacklistId = localStorage.getItem('lastSeenBlacklistId');
        if (savedBlacklistId) lastBlacklistId.current = parseInt(savedBlacklistId, 10);
    }, []);

    const checkNewItems = async () => {
        if (!isAuthenticated || loading || !canUseBrowserNotifications() || window.Notification.permission !== 'granted') return;

        try {
            // 1. Check Pending Authorizations
            const authRes = await authApi.getPending();
            if (authRes.items && authRes.items.length > 0) {
                const maxId = Math.max(...authRes.items.map((it: any) => it.id));
                if (lastAuthId.current === 0) {
                    // First run, just seed the ID to avoid spam
                    lastAuthId.current = maxId;
                    localStorage.setItem('lastSeenAuthId', String(maxId));
                } else if (maxId > lastAuthId.current) {
                    const newItems = authRes.items.filter((it: any) => it.id > lastAuthId.current);
                    newItems.forEach((item: any) => {
                        new window.Notification('Autorizacion requerida', {
                            body: `${item.site_id}: #${item.resource_id} requiere validacion.`,
                            icon: '/favicon.ico',
                        });
                    });
                    lastAuthId.current = maxId;
                    localStorage.setItem('lastSeenAuthId', String(maxId));
                }
            }

            // 2. Check Blacklist
            const blacklistRes = await blacklistApi.list();
            if (blacklistRes.items && blacklistRes.items.length > 0) {
                const maxId = Math.max(...blacklistRes.items.map((it: any) => it.id || 0));
                if (lastBlacklistId.current === 0 && maxId > 0) {
                    lastBlacklistId.current = maxId;
                    localStorage.setItem('lastSeenBlacklistId', String(maxId));
                } else if (maxId > lastBlacklistId.current) {
                    const newItems = blacklistRes.items.filter((it: any) => (it.id || 0) > lastBlacklistId.current);
                    newItems.forEach((item: any) => {
                        new window.Notification('Nuevo recurso bloqueado', {
                            body: `${item.site_id}: #${item.resource_id} ha sido bloqueado.`,
                            icon: '/favicon.ico',
                        });
                    });
                    lastBlacklistId.current = maxId;
                    localStorage.setItem('lastSeenBlacklistId', String(maxId));
                }
            }
        } catch (err) {
            console.error('Error polling for notifications:', err);
        }
    };

    useEffect(() => {
        if (!isAuthenticated || loading) return;

        const intervalId = setInterval(checkNewItems, POLLING_INTERVAL);
        checkNewItems();

        return () => clearInterval(intervalId);
    }, [isAuthenticated, loading, permission]);

    // Public method to request permission (can be called from settings/admin)
    useEffect(() => {
        const handleRequestPermission = () => {
            if (!canUseBrowserNotifications()) {
                sileo.warning({
                    title: 'Notificaciones no disponibles',
                    description: 'Se requiere HTTPS o localhost para usar notificaciones del navegador.',
                });
                return;
            }

            window.Notification.requestPermission().then((res) => {
                setPermission(res);
                if (res === 'granted') {
                    sileo.success({ title: 'Notificaciones habilitadas', description: 'Recibiras alertas del sistema.' });
                    checkNewItems();
                } else {
                    sileo.warning({ title: 'Notificaciones denegadas', description: 'No recibiras alertas en el escritorio.' });
                }
            });
        };

        window.addEventListener('request-browser-notifications', handleRequestPermission);
        return () => window.removeEventListener('request-browser-notifications', handleRequestPermission);
    }, [isAuthenticated, loading, permission]);

    return null; // This is a logic-only component
}
