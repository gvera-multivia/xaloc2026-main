
import os
import json
import psycopg
from pathlib import Path

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
    # (Simplified version of runtime_flags logic)
    for host in ["postgres", "redis", "auth-rbac-service", "dashboard-backend-service"]:
        dsn = dsn.replace(f"@{host}", "@localhost")
    return dsn

def find_resource():
    load_env()
    dsn = get_dsn()
    if not dsn:
        print("Error: No PG DSN found in .env")
        return

    print(f"Connecting to: {dsn}")
    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                # Use CASE to safely cast to bigint only if it's numeric, 
                # or just use text comparison for idRecurso.
                cur.execute("""
                    SELECT job_id, status, payload_json->>'site_id', payload_json->>'idRecurso', dedup_key
                    FROM jobs
                    WHERE payload_json->>'idRecurso' = '104675'
                       OR payload_json->>'idRecurso' = '104675.0'
                       OR dedup_key LIKE '%:104675:%'
                """)
                rows = cur.fetchall()
                if not rows:
                    print("Resource 104675 not found in jobs table.")
                for row in rows:
                    print(f"Found Job: {row[0]}, Status: {row[1]}, Site: {row[2]}, ResourceID: {row[3]}, DedupKey: {row[4]}")
    except Exception as e:
        print(f"Connection error: {e}")

if __name__ == "__main__":
    find_resource()
