ALTER TABLE realtime_incidents ADD COLUMN IF NOT EXISTS error_code TEXT;
ALTER TABLE realtime_incidents ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE realtime_incidents ADD COLUMN IF NOT EXISTS screenshot_path TEXT;
ALTER TABLE realtime_incidents ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ;
ALTER TABLE realtime_incidents ADD COLUMN IF NOT EXISTS resolved_by TEXT;

UPDATE realtime_incidents
SET error_code = incident_type
WHERE error_code IS NULL;

UPDATE realtime_incidents
SET status = 'NEW'
WHERE status IS NULL OR status = '';

ALTER TABLE realtime_incidents ALTER COLUMN status SET DEFAULT 'NEW';
ALTER TABLE realtime_incidents ALTER COLUMN status SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'realtime_incidents_status_check'
    ) THEN
        ALTER TABLE realtime_incidents
        ADD CONSTRAINT realtime_incidents_status_check
        CHECK (status IN ('NEW', 'REVIEWED', 'RESOLVED'));
    END IF;
END$$;
