import psycopg
import os
import json
from dotenv import load_dotenv

load_dotenv()

dsn = os.getenv("REPORT_PG_DSN") or os.getenv("PG_DSN")
if not dsn:
    print("PG_DSN not found in .env.")
    exit(1)

if "@postgres" in dsn:
    dsn = dsn.replace("@postgres", "@localhost")

print(f"Using DSN: {dsn}")

try:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            # All jobs in any state for 104720
            print("\n--- Listing ALL jobs for 104720 ---")
            cur.execute("""
                SELECT id, job_id, status, created_at, updated_at, dedup_key, payload_json
                FROM jobs 
                WHERE (payload_json->>'idRecurso') = '104720' 
                   OR (payload_json->>'resource_id') = '104720'
                   OR dedup_key LIKE '%104720%'
            """)
            rows = cur.fetchall()
            for row in rows:
                print(f"ID: {row[0]}, Status: {row[2]}, DedupKey: {row[5]}")
            
            # Specifically check what get_active_job_resource_ids would find
            site_id = 'servei_cat_trans'
            candidate_ids = [104720]
            
            cur.execute("""
                SELECT DISTINCT COALESCE(
                    CASE 
                        WHEN (payload_json->>'idRecurso') ~ '^[0-9]+$' 
                            THEN (payload_json->>'idRecurso')::bigint 
                        WHEN (payload_json->>'idRecurso') ~ '^[0-9]+\.0+$' 
                            THEN ((payload_json->>'idRecurso')::numeric)::bigint 
                        ELSE NULL 
                    END,
                    CASE 
                        WHEN NULLIF(split_part(dedup_key, ':', 2), 'none') ~ '^[0-9]+$' 
                            THEN split_part(dedup_key, ':', 2)::bigint 
                        WHEN NULLIF(split_part(dedup_key, ':', 2), 'none') ~ '^[0-9]+\.0+$' 
                            THEN (split_part(dedup_key, ':', 2)::numeric)::bigint 
                        ELSE NULL 
                    END
                ) AS rid, id, status, dedup_key
                FROM jobs
                WHERE status IN ('queued', 'processing', 'in_progress')
                  AND COALESCE(payload_json->>'site_id', split_part(dedup_key, ':', 1), '') = %s
            """, (site_id,))
            
            active_rows = cur.fetchall()
            print(f"\n--- ACTIVE jobs for {site_id} ---")
            for row in active_rows:
                if row[0] == 104720:
                    print(f"MATCH FOUND: RID={row[0]}, ID={row[1]}, Status={row[2]}, DedupKey={row[3]}")
                else:
                    pass # print(f"Other RID={row[0]}")

except Exception as e:
    print(f"Error: {e}")
