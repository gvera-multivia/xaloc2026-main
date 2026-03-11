# phase5-canary-rollout-runbook.md

## Purpose
Execute Phase 5 safely: canary, parity verification, promotion, and rollback for the canonical consultor migration.

## Scope
- Production/staging rollout execution for migrated architecture.
- Site-by-site canary over active runtime path (`brain_claim` -> `payload_validator` -> worker).
- Verification of claims, incidents, queue health, and job outcomes.

## Relevant Files
- `services/brain_claim/app.py`
- `services/payload_validator/app.py`
- `core/worker/consumer.py`
- `core/realtime_store.py`
- `core/pg_runtime_store.py`
- `core/pg_admin_store.py`
- `infra/docker/docker-compose.microservices.yml`
- `docs/consultor-migration/final-canonical-migration-execution-plan.md`

## Target Behavior
- Only consultor-backed retrieval is active.
- Validator is canonical-only (no SQL hydration fallback).
- Controllers handle canonical-first mapping with legacy compatibility preserved.
- No regression in:
  - claim/discard behavior
  - incident rates
  - queue latency/backlog
  - worker success rate

## Assumptions
- Runtime uses PostgreSQL-backed realtime store and jobs ledger.
- Redis Streams pipeline is active (`candidates` -> `validated`).
- `services/brain_claim/app.py` is the active claim service.
- Deprecated `core/brain/orchestrator.py` is disabled by default.

## Findings (Current Readiness)
- Phases 1-4 are complete in code.
- Migration-focused test suite is green (`30 passed`).
- Remaining work is operational rollout and monitoring (Phase 5).

## Canary Order
1. `ayunta_palma`
2. `terrassa`
3. `redsara`
4. `xaloc_girona`
5. `base_online`
6. `madrid`

## Pre-Canary Checklist (Per Site)
1. Confirm active site config in `organismo_config` with expected filters.
2. Confirm no emergency legacy runtime flags are enabled:
   - `ALLOW_LEGACY_BRAIN_ORCHESTRATOR` must be unset/`0`.
3. Confirm recent baseline window exists (last 24h) for comparison:
   - incidents by type
   - queued/processing counts
   - success/failed counts
4. Confirm worker fleet healthy and no stale processing pauses.

## Execution Steps (Per Site)
1. Start canary window (recommended 60-120 min low-risk period).
2. Process a controlled sample (recommended 20-50 resources minimum, more for `madrid`).
3. Monitor live every 5-10 min:
   - new incidents by type
   - queue depth and processing lag
   - failed/dead jobs
4. End window and compare against baseline gates.
5. Promote or rollback immediately based on gates.

## Verification Queries (PostgreSQL)

### 1) Incidents by type (last 2h, one site)
```sql
SELECT site_id, incident_type, COUNT(*) AS total
FROM realtime_incidents
WHERE site_id = :site_id
  AND created_at >= NOW() - INTERVAL '2 hours'
GROUP BY site_id, incident_type
ORDER BY total DESC;
```

### 2) Critical incident drift vs baseline (example 24h vs previous 24h)
```sql
WITH curr AS (
  SELECT incident_type, COUNT(*) c
  FROM realtime_incidents
  WHERE site_id = :site_id
    AND created_at >= NOW() - INTERVAL '24 hours'
  GROUP BY incident_type
),
prev AS (
  SELECT incident_type, COUNT(*) p
  FROM realtime_incidents
  WHERE site_id = :site_id
    AND created_at >= NOW() - INTERVAL '48 hours'
    AND created_at <  NOW() - INTERVAL '24 hours'
  GROUP BY incident_type
)
SELECT COALESCE(curr.incident_type, prev.incident_type) AS incident_type,
       COALESCE(c,0) AS current_count,
       COALESCE(p,0) AS previous_count
FROM curr
FULL OUTER JOIN prev ON prev.incident_type = curr.incident_type
ORDER BY 1;
```

### 3) Job outcomes (last 2h, one site)
```sql
SELECT
  COALESCE(payload_json->>'site_id', split_part(dedup_key, ':', 1), '') AS site_id,
  status,
  COUNT(*) AS total
FROM jobs
WHERE created_at >= NOW() - INTERVAL '2 hours'
  AND COALESCE(payload_json->>'site_id', split_part(dedup_key, ':', 1), '') = :site_id
GROUP BY 1,2
ORDER BY 2;
```

### 4) Queue health snapshot (queued+processing)
```sql
SELECT
  COALESCE(payload_json->>'site_id', split_part(dedup_key, ':', 1), '') AS site_id,
  status,
  COUNT(*) AS total
FROM jobs
WHERE status IN ('queued','processing')
GROUP BY 1,2
ORDER BY 1,2;
```

### 5) Stuck processing jobs (>30 min)
```sql
SELECT job_id, status, processing_at, updated_at,
       COALESCE(payload_json->>'site_id', split_part(dedup_key, ':', 1), '') AS site_id
FROM jobs
WHERE status = 'processing'
  AND processing_at < NOW() - INTERVAL '30 minutes'
ORDER BY processing_at ASC;
```

## Redis Stream Checks (Operational)
- Confirm streams have consumer groups and are advancing:
  - `candidates`
  - `validated`
  - `dlq:candidates`
- Watch for sudden growth in:
  - pending messages
  - unacked messages
  - DLQ writes

## Promotion Gates (Per Site)
1. No unexpected spike in `SITE_RULE_DISCARDED` or `REGEX_DISCARDED`.
2. No sustained increase in `failed`/`dead` jobs (> agreed baseline tolerance).
3. Queue backlog/latency within normal band.
4. Manual review of sampled resources shows semantic parity in outcomes.

## Rollback Strategy (Per Site)
1. Pause site processing via runtime controls/admin endpoint.
2. Revert to last known good release (container/image tag rollback).
3. Resume site processing and monitor 30-60 min.
4. Keep canary evidence:
   - incident breakdown
   - job status deltas
   - sample resource IDs affected

## Risks
- Low-frequency organism-specific edge cases may appear only under real traffic.
- Operational noise from unrelated incidents may hide migration signals.
- Canary sample too small may miss regressions.

## Recommendations
- Start with conservative sample size and extend for `madrid`.
- Enforce fixed time-box and explicit go/no-go owner per site.
- Keep rollback ready before every promotion.

## Open Questions
- Exact tolerated variance thresholds by incident type per site (set with operations).
- Whether to require two consecutive green canary windows for `madrid`.

## Exact Next Steps
1. Approve this runbook with ops owner + on-call.
2. Execute canary for `ayunta_palma` using this checklist.
3. Record evidence in a per-site canary log.
4. Promote sequentially through the defined canary order.
