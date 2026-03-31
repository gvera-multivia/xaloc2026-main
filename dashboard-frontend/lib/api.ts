export const API_BASE = '/api';

function isJwtExpired(token: string): boolean {
    try {
        const payloadPart = token.split('.')[1];
        if (!payloadPart) return false;
        const normalized = payloadPart.replace(/-/g, '+').replace(/_/g, '/');
        const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4);
        const payload = JSON.parse(atob(padded)) as { exp?: number };
        if (!payload.exp || !Number.isFinite(payload.exp)) return false;
        const nowSec = Math.floor(Date.now() / 1000);
        return payload.exp <= nowSec;
    } catch {
        return false;
    }
}

function readAuthToken(): string | null {
    if (typeof window === 'undefined') return null;
    try {
        const value = window.localStorage.getItem('dashboard_access_token');
        const token = value && value.trim() ? value.trim() : null;
        if (!token) return null;
        if (isJwtExpired(token)) {
            window.localStorage.removeItem('dashboard_access_token');
            return null;
        }
        return token;
    } catch {
        return null;
    }
}

async function fetcher<T>(path: string, options?: RequestInit): Promise<T> {
    const headers = new Headers(options?.headers || {});
    const token = readAuthToken();
    if (token && !headers.has('Authorization')) {
        headers.set('Authorization', `Bearer ${token}`);
    }

    const res = await fetch(`${API_BASE}${path}`, {
        credentials: 'include',
        ...options,
        headers,
    });
    if (!res.ok) {
        const errorText = await res.text().catch(() => 'Unknown error');
        throw new Error(errorText || `HTTP error! status: ${res.status}`);
    }
    if (res.status === 204) {
        return {} as T;
    }
    const text = await res.text();
    if (!text) {
        return {} as T;
    }
    return JSON.parse(text) as T;
}

export const api = {
    get: <T>(path: string) => fetcher<T>(path),
    post: <T>(path: string, body?: any) => fetcher<T>(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
    }),
    put: <T>(path: string, body?: any) => fetcher<T>(path, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
    }),
    delete: <T>(path: string) => fetcher<T>(path, { method: 'DELETE' }),
};

// Typed endpoints helpers
export const queueApi = {
    getCurrent: (page = 1, pageSize = 200) =>
        api.get<{ items: any[], total: number }>(`/queue/current?page=${page}&page_size=${pageSize}`),
    getLiveViewer: () => api.get<{ enabled: boolean; novnc_url: string | null }>('/queue/live-viewer'),
    getCompletionMarker: (day: string) => api.get<{ marker: string }>(`/queue/completion-marker?day=${day}`),
    deleteItem: (siteId: string, resourceId: number | string) =>
        api.delete<any>(`/queue/items/${encodeURIComponent(siteId)}/${resourceId}`),
    pauseSite: (siteId: string, minutes?: number, reason?: string) => {
        const params = new URLSearchParams();
        if (minutes) params.set('minutes', String(minutes));
        if (reason) params.set('reason', reason);
        return api.post<any>(`/queue/pauses/${encodeURIComponent(siteId)}?${params.toString()}`);
    },
    unpauseSite: (siteId: string) => api.delete<any>(`/queue/pauses/${encodeURIComponent(siteId)}`),
    pauseItem: (siteId: string, resourceId: number | string, minutes?: number, reason?: string) => {
        const params = new URLSearchParams();
        if (minutes) params.set('minutes', String(minutes));
        if (reason) params.set('reason', reason);
        return api.post<any>(`/queue/items/${encodeURIComponent(siteId)}/${resourceId}/pause?${params.toString()}`);
    },
    unpauseItem: (siteId: string, resourceId: number | string) =>
        api.delete<any>(`/queue/items/${encodeURIComponent(siteId)}/${resourceId}/pause`),
    recoverItem: (siteId: string, resourceId: number | string) =>
        api.post<any>(`/queue/items/${encodeURIComponent(siteId)}/${resourceId}/recover`),
    recoverStuck: (params?: {
        heartbeatTimeoutSeconds?: number;
        limit?: number;
        siteId?: string;
        resourceId?: number | string;
    }) => {
        const query = new URLSearchParams();
        if (params?.heartbeatTimeoutSeconds) {
            query.set('heartbeat_timeout_seconds', String(params.heartbeatTimeoutSeconds));
        }
        if (params?.limit) {
            query.set('limit', String(params.limit));
        }
        if (params?.siteId) {
            query.set('site_id', params.siteId);
        }
        if (params?.resourceId !== undefined && params?.resourceId !== null) {
            query.set('resource_id', String(params.resourceId));
        }
        const suffix = query.toString() ? `?${query.toString()}` : '';
        return api.post<any>(`/queue/recover-stuck${suffix}`);
    },
};

export const historyApi = {
    getIncidents: (day?: string, page = 1, pageSize = 200) =>
        api.get<{ items: any[], total: number }>(`/history/incidents?${day ? `day=${day}&` : ''}page=${page}&page_size=${pageSize}`),
    getSuccesses: (day?: string, page = 1, pageSize = 200) =>
        api.get<{ items: any[], total: number }>(`/history/successes?${day ? `day=${day}&` : ''}page=${page}&page_size=${pageSize}`),
    getDays: (source = 'all', page = 1, pageSize = 10) =>
        api.get<{ items: any[], total: number }>(`/history/days?source=${source}&page=${page}&page_size=${pageSize}`),
    getTopUsers: (limit = 500, day?: string) =>
        api.get<{ items: Array<{ usuario_asignado: string; total_recursos: number }>; total: number; limit: number; day?: string | null; morrigan_total?: number; morrigan_today_total?: number }>(
            `/history/top-users?limit=${limit}${day ? `&day=${encodeURIComponent(day)}` : ''}`,
        ),
    getPostgresDetails: (siteId: string, resourceId: number, limit = 200) =>
        api.get<{
            items: Array<{
                source: string;
                status?: string | null;
                day?: string | null;
                started_at?: string | null;
                ended_at?: string | null;
                site_id?: string | null;
                resource_id?: number | string | null;
                job_id?: string | null;
                protocol?: string | null;
                payload?: Record<string, any>;
                result?: Record<string, any>;
                metadata?: Record<string, any>;
            }>;
            total: number;
        }>(
            `/history/postgres-details?site_id=${encodeURIComponent(siteId)}&resource_id=${resourceId}&limit=${limit}`,
        ),
    resolveClientFolder: (payload: any) =>
        api.post<{ path: string; exists: boolean; fase_procedimiento?: string | null; fase_folder?: string | null; ruta_cliente?: string }>(
            '/client-folder',
            payload,
        ),
};

export const controlApi = {
    getStatus: () => api.get<any>('/control/status'),
    getLogs: (processName: string, lines = 100) => api.get<any>(`/logs/${processName}?lines=${lines}`),
    start: (processName: string) => api.post<any>(`/control/${processName}/start`),
    stop: (processName: string) => api.post<any>(`/control/${processName}/stop`),
    restart: (processName: string) => api.post<any>(`/control/${processName}/restart`),
};

export const authApi = {
    getPending: (type?: string) => api.get<{ items: any[], total: number }>(`/pending-auth${type ? `?authorization_type=${type}` : ''}`),
    approve: (id: number) => api.post<any>(`/pending-auth/${id}/approve`),
    reject: (id: number, reason: string) => api.post<any>(`/pending-auth/${id}/reject`, { reason }),
};

export const sessionApi = {
    login: (username: string, password: string) => api.post<{ ok: boolean; token?: string; user: { sub: string; username: string; role: string } }>(
        '/auth/login',
        { username, password },
    ),
    me: () => api.get<{ authenticated: boolean; user: { sub: string; username: string; role: string } }>('/auth/me'),
    logout: () => api.post<{ ok: boolean }>('/auth/logout'),
};

export const usersApi = {
    list: () => api.get<{ items: any[]; total: number }>('/auth/users'),
    create: (payload: { username: string; password: string; role: 'admin' | 'user'; active?: boolean }) =>
        api.post<{ created: boolean; user: any }>('/auth/users', payload),
    update: (id: number, payload: { username?: string; role?: string; active?: boolean; password?: string }) =>
        api.put<{ updated: boolean }>(`/auth/users/${id}`, payload),
    delete: (id: number) => api.delete<{ deleted: boolean }>(`/auth/users/${id}`),
};

export const configApi = {
    list: () => api.get<{ items: any[], total: number }>('/config'),
    update: (siteId: string, updates: Record<string, any>) =>
        api.put<any>(`/config/${encodeURIComponent(siteId)}`, updates),
    setSiteActive: (siteId: string, active: boolean) =>
        api.post<any>(`/config/${encodeURIComponent(siteId)}/active`, { active }),
};

export const incidentsApi = {
    getPending: (page = 1, pageSize = 200) =>
        api.get<{ items: any[], total: number }>(`/incidents?page=${page}&page_size=${pageSize}`),
    claim: (id: string) => api.post<any>(`/incidents/${id}/claim`),
    release: (id: string) => api.post<any>(`/incidents/${id}/release`),
    getIncidentGesdocStatus: (siteId: string, resourceId: number | string) =>
        api.get<{
            ok: boolean;
            incident_id?: string;
            numclient?: number | string;
            cliente_tipo?: number | null;
            client_folder_exists: boolean;
            client_folder_path?: string | null;
            has_sent_request: boolean;
            sent_request_entries: string[];
            available_actions: string[];
            locked_required: boolean;
        }>(`/incidents/${encodeURIComponent(siteId)}/${resourceId}/gesdoc-status`),
    runIncidentGesdocAction: (
        siteId: string,
        resourceId: number | string,
        action: 'generate' | 'send',
    ) =>
        api.post<{
            ok: boolean;
            action: 'generate' | 'send';
            cliente_tipo?: number | null;
            authorization_found: boolean;
            authorization_file?: string | null;
            destination_paths: string[];
            message: string;
        }>(`/incidents/${encodeURIComponent(siteId)}/${resourceId}/gesdoc-action`, { action }),
};

export const blacklistApi = {
    list: (siteId?: string) => api.get<{ items: any[], total: number }>(`/blacklist${siteId ? `?site_id=${siteId}` : ''}`),
    block: (siteId: string, resourceId: number | string, reason?: string, source?: string) =>
        api.post<any>('/blacklist', { site_id: siteId, resource_id: resourceId, reason, source }),
    unblock: (siteId: string, resourceId: number | string) =>
        api.delete<any>(`/blacklist/${encodeURIComponent(siteId)}/${resourceId}`),
};
