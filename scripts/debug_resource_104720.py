import psycopg
import os
from dotenv import load_dotenv

load_dotenv()

dsn = os.getenv("REPORT_PG_DSN") or os.getenv("PG_DSN")
if not dsn:
    print("PG_DSN not found in .env.")
    exit(1)

# Handle 'postgres' host in DSN if running locally (change to localhost)
if "@postgres" in dsn:
    dsn = dsn.replace("@postgres", "@localhost")

print(f"Using DSN: {dsn}")

try:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            # Check jobs
            cur.execute("""
                SELECT id, job_id, status, created_at, updated_at, dedup_key
                FROM jobs 
                WHERE (payload_json->>'idRecurso') = '104720' 
                   OR (payload_json->>'resource_id') = '104720'
                   OR dedup_key LIKE '%:104720:%'
            """)
            rows = cur.fetchall()
            print(f"\n--- Jobs for 104720 ---\nFound {len(rows)} rows.")
            for row in rows:
                print(row)
            
            # Check incidents
            cur.execute("""
                SELECT incident_id, site_id, resource_id, incident_type, status, created_at 
                FROM realtime_incidents 
                WHERE resource_id = 104720
            """)
            incidents = cur.fetchall()
            print(f"\n--- Incidents for 104720 ---\nFound {len(incidents)} rows.")
            for inc in incidents:
                print(inc)
            
            # Check blacklist
            cur.execute("""
                SELECT site_id, resource_id, reason, created_at 
                FROM blocked_resources 
                WHERE resource_id = 104720
            """)
            blocked = cur.fetchall()
            print(f"\n--- Blacklist for 104720 ---\nFound {len(blocked)} rows.")
            for b in blocked:
                print(b)
                
except Exception as e:
    print(f"Error connecting to DB: {e}")
