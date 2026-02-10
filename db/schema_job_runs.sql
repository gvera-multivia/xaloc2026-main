CREATE TABLE IF NOT EXISTS job_runs (
    job_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    resource_id INTEGER,
    protocol TEXT,
    state TEXT NOT NULL DEFAULT 'created',
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    error_code TEXT,
    error_message TEXT,
    payload_snapshot JSON,
    result_snapshot JSON,
    worker_id TEXT,
    trace_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    queued_at TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_job_runs_site_state
ON job_runs(site_id, state);

