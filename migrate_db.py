import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text
from db import engine, Base, init_db

print("Starting clean migration to improved senior-DBA database schema...")
with engine.connect() as conn:
    conn.execute(text("DROP TRIGGER IF EXISTS trg_match_results_aggregates ON match_results CASCADE;"))
    conn.execute(text("DROP FUNCTION IF EXISTS update_audit_project_aggregates CASCADE;"))
    conn.execute(text("DROP TABLE IF EXISTS llm_logs CASCADE;"))
    conn.execute(text("DROP TABLE IF EXISTS match_results CASCADE;"))
    conn.execute(text("DROP TABLE IF EXISTS documents CASCADE;"))
    conn.execute(text("DROP TABLE IF EXISTS audit_projects CASCADE;"))
    conn.execute(text("DROP TABLE IF EXISTS users CASCADE;"))
    conn.commit()

init_db()
print("Migration completed successfully! All tables, triggers, and constraints created.")
