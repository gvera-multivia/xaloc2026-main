-- Tabla de cola de trámites para los workers
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

-- Tabla de configuración de organismos para el orquestador
CREATE TABLE IF NOT EXISTS organismo_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL UNIQUE,           -- 'xaloc_girona', 'madrid', 'base_online'
    query_organisme TEXT NOT NULL,          -- Filtro LIKE para SQL Server: '%XALOC%'
    filtro_texp TEXT NOT NULL,              -- Tipos de expediente válidos CSV: '2,3'
    regex_expediente TEXT NOT NULL,         -- Patrón regex: '^\d{4}/\d{6}-MUL$'
    login_url TEXT NOT NULL,                -- URL de login: 'http://.../login'
    recursos_url TEXT NOT NULL,             -- URL de recursos: 'http://.../recursos/telematicos'
    active INTEGER DEFAULT 1,               -- 1 = Activo, 0 = Inactivo
    last_sync_at TIMESTAMP,                 -- Última sincronización
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
