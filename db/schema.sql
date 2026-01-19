CREATE TABLE IF NOT EXISTS tramite_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,          -- 'madrid', 'base_online', 'xaloc_girona'
    protocol TEXT,                  -- 'P1', 'P2', 'P3'
    payload JSON NOT NULL,          -- Datos del formulario en JSON (string)
    status TEXT DEFAULT 'pending',  -- 'pending', 'processing', 'completed', 'failed'
    attempts INTEGER DEFAULT 0,
    screenshot_path TEXT,
    error_log TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

