-- Control plane schema for Phase 3: candidate -> validated draft -> batched dispatch.

CREATE TABLE IF NOT EXISTS job_drafts (
    id BIGSERIAL PRIMARY KEY,
    draft_id TEXT NOT NULL UNIQUE,
    organism_id TEXT NOT NULL,
    external_resource_id TEXT,
    job_type TEXT NOT NULL,
    cert_profile TEXT NOT NULL DEFAULT 'default',
    priority INTEGER NOT NULL DEFAULT 100,
    dedup_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'validated_pending_batch',
    normalized_payload_json JSONB NOT NULL,
    trace_id TEXT,
    batch_group_key TEXT,
    job_id TEXT,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    dispatched_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_job_drafts_status_created
ON job_drafts(status, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_job_drafts_group_status
ON job_drafts(batch_group_key, status);

