import json
import sqlite3
from pathlib import Path
import sys

# Add root directory to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from core.sqlite_db import SQLiteDatabase

def init_config():
    config_path = Path("organismo_config.json")
    if not config_path.exists():
        print(f"Error: {config_path} not found.")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    print("Loading configuration into database...")
    db = SQLiteDatabase()

    conn = db.get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO organismo_config (
                id, login_url, document_url_template, attachment_url_template,
                http_headers, timeouts, paths, selectors, updated_at
            ) VALUES (
                1, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP
            )
            ON CONFLICT(id) DO UPDATE SET
                login_url=excluded.login_url,
                document_url_template=excluded.document_url_template,
                attachment_url_template=excluded.attachment_url_template,
                http_headers=excluded.http_headers,
                timeouts=excluded.timeouts,
                paths=excluded.paths,
                selectors=excluded.selectors,
                updated_at=CURRENT_TIMESTAMP
        """, (
            config.get("login_url"),
            config.get("document_url_template"),
            config.get("attachment_url_template"),
            json.dumps(config.get("http_headers", {})),
            json.dumps(config.get("timeouts", {})),
            json.dumps(config.get("paths", {})),
            json.dumps(config.get("selectors", {}))
        ))

        conn.commit()
        print("Configuration initialized/updated successfully.")

    except Exception as e:
        print(f"Error initializing config: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    init_config()
