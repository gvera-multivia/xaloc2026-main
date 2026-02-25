-- Admin/config schema used by dashboard/brain without SQLite dependency.

CREATE TABLE IF NOT EXISTS organismo_config (
    id BIGSERIAL PRIMARY KEY,
    site_id TEXT NOT NULL UNIQUE,
    query_organisme TEXT NOT NULL,
    filtro_texp TEXT NOT NULL,
    regex_expediente TEXT NOT NULL,
    login_url TEXT NOT NULL,
    recursos_url TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    last_sync_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_organismo_config_active
ON organismo_config(active, site_id);

CREATE TABLE IF NOT EXISTS blocked_resources (
    id BIGSERIAL PRIMARY KEY,
    site_id TEXT NOT NULL,
    resource_id BIGINT NOT NULL,
    reason TEXT,
    source TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(site_id, resource_id)
);

CREATE INDEX IF NOT EXISTS ix_blocked_resources_site_time
ON blocked_resources(site_id, created_at DESC);
