CREATE TABLE IF NOT EXISTS tramite_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,          -- 'madrid', 'base_online', 'xaloc_girona'
    protocol TEXT,                  -- 'P1', 'P2', 'P3'
    payload JSON NOT NULL,          -- Datos del formulario en JSON
    status TEXT DEFAULT 'pending',  -- 'pending', 'processing', 'completed', 'failed'
    attempts INTEGER DEFAULT 0,
    screenshot_path TEXT,
    error_log TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP,
    result JSON,
    attachments_count INTEGER DEFAULT 0,
    attachments_metadata JSON
);

CREATE TABLE IF NOT EXISTS organismo_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    login_url TEXT,
    document_url_template TEXT,
    attachment_url_template TEXT,
    http_headers JSON,
    timeouts JSON,
    paths JSON,
    selectors JSON,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
