"""
Модуль базы данных PostgreSQL 17 для системы «СверкаСмет».
Обеспечивает хранение учетных записей, проектов аудита, истории сопоставлений
и решений сметчика в контуре Human-in-the-loop.
"""

import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean,
    DateTime, Text, ForeignKey, desc
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, scoped_session

# Загрузка настроек из .env
load_dotenv(Path(__file__).parent / ".env")

DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "P@ssw0rd")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "sverka_db")


def get_pg_connection():
    import psycopg2
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        host=DB_HOST,
        port=DB_PORT
    )


engine = create_engine(
    "postgresql+psycopg2://",
    creator=get_pg_connection,
    pool_pre_ping=True,
    echo=False
)
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    full_name = Column(String(150), nullable=False)
    role = Column(String(50), default="estimator", nullable=False)  # estimator, lead, admin
    company = Column(String(150), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    projects = relationship("Project", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role,
            "company": self.company,
            "created_at": self.created_at.strftime("%d.%m.%Y %H:%M") if self.created_at else ""
        }


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(255), nullable=False)
    object_name = Column(String(255), nullable=True)
    status = Column(String(50), default="completed", nullable=False)
    vor_filename = Column(String(255), nullable=True)
    lsr_filename = Column(String(255), nullable=True)
    total_positions = Column(Integer, default=0)
    matched_count = Column(Integer, default=0)
    discrepancy_count = Column(Integer, default=0)
    total_financial_risk = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="projects")
    items = relationship("AuditItem", back_populates="project", cascade="all, delete-orphan", order_by="AuditItem.row_num")

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "object_name": self.object_name or self.title,
            "status": self.status,
            "vor_filename": self.vor_filename,
            "lsr_filename": self.lsr_filename,
            "total_positions": self.total_positions,
            "matched_count": self.matched_count,
            "discrepancy_count": self.discrepancy_count,
            "total_financial_risk": self.total_financial_risk,
            "created_at": self.created_at.strftime("%d.%m.%Y %H:%M") if self.created_at else ""
        }


class AuditItem(Base):
    __tablename__ = "audit_items"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    row_num = Column(Integer, nullable=False)
    vor_num = Column(String(50), nullable=True)
    lsr_num = Column(String(50), nullable=True)
    vor_name = Column(Text, nullable=False)
    lsr_name = Column(Text, nullable=True)
    code = Column(String(100), nullable=True)
    qty_vor = Column(Float, nullable=True)
    qty_lsr = Column(Float, nullable=True)
    unit = Column(String(50), nullable=True)
    unit_price = Column(Float, nullable=True)
    financial_risk = Column(Float, default=0.0)
    status = Column(String(50), nullable=False)  # ok, part, diff, none
    detail_class = Column(String(100), nullable=True)
    similarity = Column(Float, default=0.0)
    is_ai = Column(Boolean, default=False)
    explanation = Column(Text, nullable=True)
    user_decision = Column(String(50), nullable=True)  # 'yes', 'no', None

    project = relationship("Project", back_populates="items")

    def to_dict(self):
        return {
            "id": self.id,
            "n": self.row_num,
            "vor_num": self.vor_num,
            "lsr_num": self.lsr_num,
            "vor": self.vor_name,
            "lsr": self.lsr_name or "",
            "code": self.code or "",
            "vv": self.qty_vor,
            "lv": self.qty_lsr,
            "u": self.unit or "",
            "pr": self.unit_price or 0.0,
            "risk": self.financial_risk,
            "s": self.status,
            "detail_class": self.detail_class or "",
            "sim": round((self.similarity or 0.0) * 100),
            "ai": self.is_ai,
            "note": self.explanation or "",
            "decision": self.user_decision
        }


def init_db():
    """Создание таблиц и инициализация базовых данных."""
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        demo_user = session.query(User).filter_by(email="demo@sverkasmet.ru").first()
        if not demo_user:
            demo_user = User(
                email="demo@sverkasmet.ru",
                full_name="Саргсян Гагик (Ведущий сметчик)",
                role="lead",
                company="ООО «СтройЭкспертиза»"
            )
            demo_user.set_password("P@ssw0rd")
            session.add(demo_user)
            session.commit()
            print("Демо-пользователь успешно создан: demo@sverkasmet.ru / P@ssw0rd")
    finally:
        session.close()


if __name__ == "__main__":
    init_db()
    print("Инициализация базы данных завершена успешно!")
