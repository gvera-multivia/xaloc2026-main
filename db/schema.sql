-- Tabla de cola de trámites para los workers
CREATE TABLE IF NOT EXISTS tramite_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,          -- 'madrid', 'base_online', 'xaloc_girona'
    protocol TEXT,                  -- 'P1', 'P2', 'P3'
    resource_id INTEGER,            -- idRecurso remoto (para dedupe)
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
    claim_limit_per_tick INTEGER,           -- Limite por site en cada tick de claim (NULL = sin limite)
    active INTEGER DEFAULT 1,               -- 1 = Activo, 0 = Inactivo
    last_sync_at TIMESTAMP,                 -- Última sincronización
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla de cola de tareas pendientes de autorización externa (GESDOC)
-- Estas tareas NO se procesan automáticamente, requieren autorización manual
CREATE TABLE IF NOT EXISTS pending_authorization_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,              -- 'xaloc_girona', 'madrid', etc.
    resource_id INTEGER,                -- idRecurso remoto (para dedupe)
    payload JSON NOT NULL,              -- Datos del trámite en JSON
    authorization_type TEXT NOT NULL,   -- 'gesdoc', 'manual', etc.
    reason TEXT,                        -- Motivo por el que requiere autorización
    status TEXT DEFAULT 'pending',      -- 'pending', 'authorized', 'rejected', 'moved_to_queue'
    authorized_by TEXT,                 -- Usuario que autorizó
    authorized_at TIMESTAMP,            -- Fecha de autorización
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT                          -- Notas adicionales
);

-- Incidencias consolidadas de worker y orquestador
CREATE TABLE IF NOT EXISTS incidencias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idRecurso INTEGER,
    nExp TEXT,
    tipo_incidencia TEXT NOT NULL,      -- RETRY_EXHAUSTED, REQUIRES_GESDOC, REGEX_DISCARDED
    motivo TEXT,
    site_id TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_incidencias_site_tipo_time
ON incidencias(site_id, tipo_incidencia, timestamp);

-- Recursos bloqueados para evitar re-claim en siguientes ticks del brain
CREATE TABLE IF NOT EXISTS blocked_resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,
    resource_id INTEGER NOT NULL,
    reason TEXT,
    source TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_blocked_resources_site_resource
ON blocked_resources(site_id, resource_id);

CREATE INDEX IF NOT EXISTS ix_blocked_resources_site_time
ON blocked_resources(site_id, created_at);

-- Pausas temporales de procesamiento por site.
-- Si un site esta pausado, sus tareas pendientes se mantienen en cola
-- pero el worker no las reserva para ejecutar.
CREATE TABLE IF NOT EXISTS site_processing_pauses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL UNIQUE,
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_site_processing_pauses_expires
ON site_processing_pauses(expires_at);

-- Pausas temporales de procesamiento por recurso concreto (site + resource_id).
CREATE TABLE IF NOT EXISTS resource_processing_pauses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,
    resource_id INTEGER NOT NULL,
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_resource_processing_pauses_site_resource
ON resource_processing_pauses(site_id, resource_id);

CREATE INDEX IF NOT EXISTS ix_resource_processing_pauses_expires
ON resource_processing_pauses(expires_at);
