-- Initial PostgreSQL schema for microservices migration (Phase 0).
-- Idempotent by design for local/dev bootstrap.

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS roles (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scopes (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id BIGINT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS role_scopes (
    role_id BIGINT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    scope_id BIGINT NOT NULL REFERENCES scopes(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (role_id, scope_id)
);

CREATE TABLE IF NOT EXISTS organisms (
    id BIGSERIAL PRIMARY KEY,
    site_id TEXT NOT NULL UNIQUE,
    name TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    config_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rulesets (
    id BIGSERIAL PRIMARY KEY,
    organism_id BIGINT NOT NULL REFERENCES organisms(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    rules_json JSONB NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organism_id, version)
);

CREATE TABLE IF NOT EXISTS jobs (
    id BIGSERIAL PRIMARY KEY,
    job_id TEXT NOT NULL UNIQUE,
    organism_id BIGINT REFERENCES organisms(id),
    dedup_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    payload_json JSONB NOT NULL,
    result_json JSONB,
    error_message TEXT,
    queued_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS job_attempts (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    attempt_no INTEGER NOT NULL,
    worker_id TEXT,
    status TEXT NOT NULL,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (job_id, attempt_no)
);

CREATE TABLE IF NOT EXISTS job_artifacts (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    sha256 TEXT,
    size_bytes BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    event_id UUID NOT NULL UNIQUE,
    job_id BIGINT REFERENCES jobs(id),
    event_type TEXT NOT NULL,
    actor TEXT,
    payload_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_jobs_organism_status_created
ON jobs(organism_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_job_attempts_job_attempt
ON job_attempts(job_id, attempt_no DESC);

CREATE INDEX IF NOT EXISTS ix_events_job_created
ON events(job_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_events_type_created
ON events(event_type, created_at DESC);

INSERT INTO roles (code, name)
VALUES
    ('admin', 'Admin'),
    ('consultor', 'Consultor'),
    ('comercial', 'Comercial'),
    ('cliente', 'Cliente')
ON CONFLICT (code) DO NOTHING;
