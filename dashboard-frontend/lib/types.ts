export type SiteID = 'madrid' | 'xaloc_girona' | 'base_online' | 'ayunta_palma' | string;

export interface QueueItem {
    site_id: SiteID;
    resource_id: number | string;
    protocol?: string;
    state: 'pending' | 'processing' | 'completed' | 'failed' | string;
    started_at?: string;
    completed_at?: string;
    priority?: 'low' | 'medium' | 'high';
}

export interface Incident {
    site_id: SiteID;
    resource_id: number | string;
    incident_type?: string;
    reason?: string;
    started_at: string;
}

export interface PendingAuth {
    id: number;
    site_id: SiteID;
    resource_id?: string;
    authorization_type?: string;
    reason?: string;
    created_at: string;
    payload?: any;
}

export interface ProcessStatus {
    status: 'running' | 'stopped' | 'error';
    pid?: number;
    started_at?: string;
    memory_mb?: number;
}

export interface DashboardStatus {
    worker: string;
    brain: string;
}

export interface EventLog {
    ts: string;
    kind: 'info' | 'ok' | 'warn' | 'error';
    msg: string;
}

export interface PauseInfo {
    site_id: SiteID;
    reason?: string;
    expires_at?: string;
}

export interface ItemPauseInfo extends PauseInfo {
    resource_id: number | string;
}

export interface OrganismoConfig {
    site_id: SiteID;
    active: number | boolean;
    query_organisme?: string;
    filtro_texp?: string;
    regex_expediente?: string;
    login_url?: string;
    recursos_url?: string;
}

export interface DashboardUser {
    id?: number;
    sub?: string;
    username: string;
    role: 'admin' | 'user' | string;
    active?: number | boolean;
    created_at?: string;
    updated_at?: string;
}
