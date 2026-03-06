ALTER TABLE organismo_config
ADD COLUMN IF NOT EXISTS claim_limit_per_tick INTEGER;

UPDATE organismo_config
SET claim_limit_per_tick = 2,
    updated_at = NOW()
WHERE site_id = 'redsara'
  AND (claim_limit_per_tick IS NULL OR claim_limit_per_tick <> 2);
