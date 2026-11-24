import sys
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text
from db import engine, Base, init_db, is_production


def run_migration(force: bool = False):
    if is_production():
        raise RuntimeError("CRITICAL ERROR: Выполнение деструктивной миграции (DROP TABLES) запрещено в production-окружении!")

    if not force:
        confirm = input("ВНИМАНИЕ: Все таблицы БД будут удалены и созданы заново. Продолжить? [y/N]: ").strip().lower()
        if confirm not in ('y', 'yes', 'да'):
            print("Миграция отменена пользователем.")
            return

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


if __name__ == "__main__":
    force_run = "--yes" in sys.argv or "-y" in sys.argv
    run_migration(force=force_run)
