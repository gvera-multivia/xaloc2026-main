export const API_BASE = '/api';

async function fetcher<T>(path: string, options?: RequestInit): Promise<T> {
    const res = await fetch(`${API_BASE}${path}`, options);
    if (!res.ok) {
        const errorText = await res.text().catch(() => 'Unknown error');
        throw new Error(errorText || `HTTP error! status: ${res.status}`);
    }
    return res.json() as Promise<T>;
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

export const configApi = {
    list: () => api.get<{ items: any[], total: number }>('/config'),
    setSiteActive: (siteId: string, active: boolean) =>
        api.post<any>(`/config/${encodeURIComponent(siteId)}/active`, { active }),
};

export const incidentsApi = {
    getPending: (page = 1, pageSize = 200) =>
        api.get<{ items: any[], total: number }>(`/incidents?page=${page}&page_size=${pageSize}`),
    claim: (id: string) => api.post<any>(`/incidents/${id}/claim`),
    release: (id: string) => api.post<any>(`/incidents/${id}/release`),
};
