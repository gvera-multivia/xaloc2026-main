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

    // Initialize permission state
    useEffect(() => {
        if (typeof window !== 'undefined' && 'Notification' in window) {
            setPermission(Notification.permission);

            // Load last seen IDs from localStorage
            const savedAuthId = localStorage.getItem('lastSeenAuthId');
            if (savedAuthId) lastAuthId.current = parseInt(savedAuthId);

            const savedBlacklistId = localStorage.getItem('lastSeenBlacklistId');
            if (savedBlacklistId) lastBlacklistId.current = parseInt(savedBlacklistId);
        }
    }, []);

    const checkNewItems = async () => {
        if (!isAuthenticated || loading || Notification.permission !== 'granted') return;

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
                        new Notification('Autorización Requerida', {
                            body: `${item.site_id}: #${item.resource_id} requiere validación.`,
                            icon: '/favicon.ico', // Adjust if needed
                        });
                    });
                    lastAuthId.current = maxId;
                    localStorage.setItem('lastSeenAuthId', String(maxId));
                }
            }

            // 2. Check Blacklist
            const blacklistRes = await blacklistApi.list();
            if (blacklistRes.items && blacklistRes.items.length > 0) {
                // Items in blacklist usually have an 'id' based on the schema I found
                const maxId = Math.max(...blacklistRes.items.map((it: any) => it.id || 0));
                if (lastBlacklistId.current === 0 && maxId > 0) {
                    lastBlacklistId.current = maxId;
                    localStorage.setItem('lastSeenBlacklistId', String(maxId));
                } else if (maxId > lastBlacklistId.current) {
                    const newItems = blacklistRes.items.filter((it: any) => (it.id || 0) > lastBlacklistId.current);
                    newItems.forEach((item: any) => {
                        new Notification('Nuevo Recurso Bloqueado', {
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
        // Initial check
        checkNewItems();

        return () => clearInterval(intervalId);
    }, [isAuthenticated, loading]);

    // Public method to request permission (can be called from settings/admin)
    // We'll expose this via a custom event or just trust the admin setting
    useEffect(() => {
        const handleRequestPermission = () => {
            if ('Notification' in window) {
                Notification.requestPermission().then((res) => {
                    setPermission(res);
                    if (res === 'granted') {
                        sileo.success({ title: 'Notificaciones habilitadas', description: 'Recibirás alertas del sistema.' });
                        checkNewItems();
                    } else {
                        sileo.warning({ title: 'Notificaciones denegadas', description: 'No recibirás alertas en el escritorio.' });
                    }
                });
            }
        };

        window.addEventListener('request-browser-notifications', handleRequestPermission);
        return () => window.removeEventListener('request-browser-notifications', handleRequestPermission);
    }, [isAuthenticated, loading]);

    return null; // This is a logic-only component
}
