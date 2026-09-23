-- Global worker ordering by presentation date.

ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS submission_date DATE;

UPDATE jobs
SET submission_date = (payload_json->>'fecpres')::date
WHERE submission_date IS NULL
  AND NULLIF(BTRIM(payload_json->>'fecpres'), '') IS NOT NULL
  AND pg_input_is_valid(payload_json->>'fecpres', 'date');

CREATE INDEX IF NOT EXISTS ix_jobs_status_submission_priority
ON jobs(status, submission_date, priority, queued_at, id);
