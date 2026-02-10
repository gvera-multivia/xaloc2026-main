# Queue System Study And Proposal

## 1. Current System (As Implemented Today)

### Components
- `brain.py`: discovers candidates in SQL Server, claims in XVIA, builds payloads, and enqueues.
- `worker.py`: polls SQLite, reserves one pending task, executes automation, updates final status.
- `core/sqlite_db.py`: queue persistence + dedupe + lock policy + pending authorization queue.
- `db/schema.sql`: physical model (`tramite_queue`, `pending_authorization_queue`, `organismo_config`).

### Current Queue Model
- Main queue in SQLite table `tramite_queue`.
- Authorization-gated queue in SQLite table `pending_authorization_queue`.
- Worker reservation is SQL-based:
  - `SELECT ... WHERE status='pending' ORDER BY created_at LIMIT 1`
  - then `UPDATE status='processing'` inside transaction.
- Dedupe:
  - Unique partial index by `(site_id, resource_id)` for active rows.
  - Similar unique partial index for pending authorizations.

### Scheduling Behavior
- `brain.run_tick()` chooses a single locked site at a time (`get_locked_site_by_priority`).
- Refill is controlled by:
  - `target_queue_depth` per adapter.
  - `max_refill_batch` per adapter.
  - global `MAX_CLAIMS_PER_CYCLE`.
- Claims are currently sequential (non-concurrent), as requested.

## 2. Problems In The Current Design

### Structural Problems
- SQLite is being used as queue broker, state machine, and history store at once.
- Queue semantics are implemented manually (polling, locking, dedupe, retries).
- Tight coupling between scheduler rules and SQL implementation details.

### Operational Problems
- Polling model (`worker` every N seconds) increases latency and idle churn.
- Global site lock causes starvation/mixing constraints that are hard to tune.
- Repeated candidate fetch loops can re-hit already known resources unless explicitly filtered.
- Queue depth behavior is implicit and adapter-specific; hard to reason globally.

### Scalability/Resilience Problems
- SQLite write contention risk if multiple producers/workers increase.
- No broker-level visibility (ready/inflight/dead-letter) beyond custom SQL queries.
- Recovery/lease semantics are custom and fragile vs broker-native patterns.

## 3. Target Architecture (No Concurrency For Now)

## Objective
- Use Redis as queue/broker for active job flow.
- Keep SQLite as final ledger/audit/tracking of lifecycle and results.
- Preserve sequential processing (1 worker, 1 job at a time) in first stage.

### Logical Components
- `brain-producer`:
  - discovers + claims in XVIA
  - writes job to Redis queue
  - writes/updates SQLite ledger row (`queued` state)
- `worker-consumer`:
  - pops next Redis job
  - executes automation
  - updates SQLite ledger (`processing` -> `completed/failed/retry/dead`)
- `authorization-manager`:
  - controls jobs requiring GESDOC
  - only publishes to Redis once authorized

## 4. Proposed Data Model

### Redis (Runtime)
- `queue:jobs:ready` (LIST): main FIFO queue.
- `queue:jobs:inflight` (ZSET): leased jobs with lease expiration timestamp.
- `queue:jobs:dead` (LIST): dead-letter job ids.
- `job:{job_id}` (HASH/JSON): runtime payload and metadata.
- `dedupe:resource:{site_id}:{resource_id}` (STRING with TTL): fast duplicate guard in producer.

### SQLite (Final Registry / Audit)
- New table `job_runs` (or evolve `tramite_queue` into ledger-only):
  - `job_id` (text/uuid, primary key)
  - `site_id`, `resource_id`, `protocol`
  - `state` (`created|queued|processing|completed|failed|dead|cancelled|awaiting_auth`)
  - `attempt`, `max_attempts`
  - `error_code`, `error_message`
  - `payload_snapshot` (JSON)
  - `result_snapshot` (JSON)
  - timestamps: `created_at`, `queued_at`, `started_at`, `finished_at`
  - `worker_id`, `trace_id`

SQLite stops being "the queue"; it becomes source of truth for historical state and reporting.

## 5. State Machine (Sequential v1)

1. `created`
2. `awaiting_auth` (if GESDOC needed) OR `queued`
3. `processing`
4. `completed` OR `failed`
5. `retry` path:
   - `failed` with retryable error -> `queued` (attempt+1)
6. `dead` after `max_attempts`

No parallelism required; only one consumer loop processes one leased job at a time.

## 6. Runtime Flow (v1, Non-Concurrent)

1. Brain finds candidate and claims XVIA.
2. Brain checks dedupe key in Redis (`SETNX dedupe...`).
3. Brain writes ledger row in SQLite (`queued` or `awaiting_auth`).
4. If queueable, brain pushes `job_id` into `queue:jobs:ready`.
5. Worker blocks on Redis pop (`BRPOP`) for low-latency pickup.
6. Worker moves job to inflight with lease and updates SQLite to `processing`.
7. Worker runs automation.
8. Worker updates SQLite to terminal state.
9. Worker removes inflight lease.
10. If crash/restart, reaper returns expired inflight jobs to ready.

## 7. Why This Fixes The Current Pain

- Removes queue orchestration burden from SQLite.
- Eliminates poll loops in worker (`BRPOP` is event-driven).
- Makes retries, dead-letter, and leases explicit.
- Keeps full auditability in SQLite.
- Supports future concurrency by only changing worker count/lease policy, not architecture.

## 8. Migration Plan (Low Risk)

### Phase 0: Preparation
- Introduce `QueueGateway` abstraction:
  - `enqueue(job)`, `reserve()`, `ack()`, `nack()`, `requeue()`.
- Keep existing SQLite queue as current backend.

### Phase 1: Redis Backend (Feature Flag)
- Implement `RedisQueueGateway`.
- Add env switch:
  - `QUEUE_BACKEND=sqlite|redis`.
- Mirror-write ledger in SQLite from both backends.

### Phase 2: Cutover
- Producer writes to Redis.
- Worker consumes Redis only.
- Keep read-only compatibility views from old `tramite_queue` if needed.

### Phase 3: Cleanup
- Deprecate SQLite queue semantics.
- Keep only ledger tables + reporting queries.

## 9. Rules For "No Concurrency For Now"

- Single worker process.
- Single reserve at a time (`BRPOP` -> process -> ack).
- No `asyncio.gather` for job execution.
- Retries remain sequential.

This gives architectural correctness now, without introducing race complexity.

## 10. Implementation Notes For Your Codebase

- Keep adapters (`madrid`, `xaloc_girona`, `base_online`) unchanged for payload construction.
- Move current dedupe checks from `SQLiteDatabase` queue insert path into producer pre-enqueue logic (Redis + ledger check).
- Replace `worker.py` loop source:
  - from `db.get_pending_task()`
  - to `queue_gateway.reserve()`.
- Maintain `pending_authorization_queue` semantics, but authorization should publish to Redis instead of inserting active queue rows.

## 11. Suggested Next Deliverables

1. `core/queue_gateway.py` (interface + SQLite current implementation).
2. `core/redis_queue_gateway.py` (ready/inflight/dead + lease recovery).
3. `db/schema_job_runs.sql` (ledger schema).
4. Brain/worker integration behind `QUEUE_BACKEND`.
