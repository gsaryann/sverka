import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text
from db import engine, Base, init_db

print("Starting clean migration to improved database schema...")
with engine.connect() as conn:
    conn.execute(text("DROP TABLE IF EXISTS llm_logs CASCADE;"))
    conn.execute(text("DROP TABLE IF EXISTS match_results CASCADE;"))
    conn.execute(text("DROP TABLE IF EXISTS documents CASCADE;"))
    conn.execute(text("DROP TABLE IF EXISTS audit_projects CASCADE;"))
    conn.execute(text("DROP TABLE IF EXISTS users CASCADE;"))
    conn.commit()

init_db()
print("Migration completed successfully! All 5 tables created with strict types, checks and indexes.")
