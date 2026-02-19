-- Runtime schema for worker health/pauses without SQLite.

CREATE TABLE IF NOT EXISTS worker_runtime (
    worker_id TEXT PRIMARY KEY,
    run_id TEXT,
    pid INTEGER,
    status TEXT NOT NULL DEFAULT 'online',
    current_job_id TEXT,
    last_heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS site_processing_pauses (
    site_id TEXT PRIMARY KEY,
    reason TEXT,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS resource_processing_pauses (
    site_id TEXT NOT NULL,
    resource_id BIGINT NOT NULL,
    reason TEXT,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (site_id, resource_id)
);

CREATE INDEX IF NOT EXISTS ix_resource_processing_pauses_site_exp
ON resource_processing_pauses(site_id, expires_at);
