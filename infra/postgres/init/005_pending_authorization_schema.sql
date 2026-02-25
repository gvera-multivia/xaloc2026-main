-- Pending authorization queue in PostgreSQL (replaces SQLite legacy table).

CREATE TABLE IF NOT EXISTS pending_authorization_queue (
    id BIGSERIAL PRIMARY KEY,
    site_id TEXT NOT NULL,
    resource_id BIGINT NOT NULL,
    payload_json JSONB NOT NULL,
    authorization_type TEXT NOT NULL DEFAULT 'gesdoc',
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    authorized_by TEXT,
    authorized_at TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_pending_auth_site_resource_pending
ON pending_authorization_queue(site_id, resource_id)
WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS ix_pending_auth_status_created
ON pending_authorization_queue(status, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_pending_auth_type_status_created
ON pending_authorization_queue(authorization_type, status, created_at DESC);
