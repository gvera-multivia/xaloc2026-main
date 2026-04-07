
import os
import json
import psycopg
from pathlib import Path
from datetime import datetime, timezone

def load_env():
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

def get_dsn():
    dsn = os.getenv("REPORT_PG_DSN") or os.getenv("PG_DSN")
    if dsn and "postgres:" in dsn and os.name == "nt":
        dsn = dsn.replace("postgres:", "localhost:")
    # Replace docker hostnames with localhost if on Windows
    for host in ["postgres", "redis", "auth-rbac-service", "dashboard-backend-service"]:
        dsn = dsn.replace(f"@{host}", "@localhost")
    return dsn

def execute_action():
    load_env()
    dsn = get_dsn()
    if not dsn:
        print("Error: No PG DSN found in .env")
        return

    job_id = "5ce7f809-1fcf-48e1-ba8c-e65588c0cfba"
    site_id = "ayunta_palma"
    resource_id = 104675
    reason = "Manual block request by user"
    source = "Antigravity/manual-fix"

    print(f"Connecting to: {dsn}")
    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                # 1. Cancel the current job
                print(f"Cancelling job: {job_id}...")
                cur.execute("""
                    UPDATE jobs
                    SET status = 'cancelled',
                        finished_at = NOW(),
                        updated_at = NOW(),
                        error_message = %s
                    WHERE job_id = %s AND status = 'queued'
                """, (reason, job_id))
                if cur.rowcount > 0:
                    print(f"Job {job_id} cancelled successfully.")
                else:
                    print(f"Job {job_id} not found or already in a non-queued status.")

                # 2. Add to blocked_resources
                print(f"Blocking resource {resource_id} in site {site_id}...")
                cur.execute("""
                    INSERT INTO blocked_resources (site_id, resource_id, reason, source, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (site_id, resource_id) DO UPDATE SET
                        reason = EXCLUDED.reason,
                        source = EXCLUDED.source,
                        updated_at = NOW()
                """, (site_id, resource_id, reason, source))
                print(f"Resource {resource_id} blocked successfully.")
            
            conn.commit()
            print("Transaction committed.")
    except Exception as e:
        print(f"Database error: {e}")

if __name__ == "__main__":
    execute_action()
