"""
Модуль базы данных PostgreSQL 17 для системы «СверкаСмет».
Обеспечивает полную реализацию ER-диаграммы платформы:
- USERS (пользователи и роли)
- AUDIT_PROJECTS (проекты аудита смет)
- DOCUMENTS (исходные документы: ВОР, ЛСР и др.)
- MATCH_RESULTS (результаты сопоставления позиций, риски и решения сметчика)
- LLM_LOGS (журнал арбитража ИИ, токены и финансовые затраты)
"""

import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean,
    DateTime, Text, ForeignKey, desc, text
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
    """Сущность USERS из ER-диаграммы."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    full_name = Column(String(150), nullable=False)
    role = Column(String(50), default="estimator", nullable=False)  # estimator, lead, admin
    company = Column(String(150), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    projects = relationship("AuditProject", back_populates="user", cascade="all, delete-orphan")

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


class AuditProject(Base):
    """Сущность AUDIT_PROJECTS из ER-диаграммы (создаётся пользователем)."""
    __tablename__ = "audit_projects"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    status = Column(String(50), default="completed", nullable=False)
    match_rate = Column(Float, default=0.0)
    total_positions = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Дополнительные поля для обратной совместимости с существующим веб-интерфейсом
    object_name = Column(String(255), nullable=True)
    vor_filename = Column(String(255), nullable=True)
    lsr_filename = Column(String(255), nullable=True)
    matched_count = Column(Integer, default=0)
    discrepancy_count = Column(Integer, default=0)
    total_financial_risk = Column(Float, default=0.0)

    # Связи 1-ко-многим согласно ER-диаграмме
    user = relationship("User", back_populates="projects")
    documents = relationship("Document", back_populates="project", cascade="all, delete-orphan")
    match_results = relationship(
        "MatchResult", back_populates="project", cascade="all, delete-orphan",
        order_by="MatchResult.row_num"
    )
    llm_logs = relationship(
        "LLMLog", back_populates="project", cascade="all, delete-orphan",
        order_by="LLMLog.created_at"
    )

    # Псевдоним items для сохранения обратной совместимости
    @property
    def items(self):
        return self.match_results

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "object_name": self.object_name or self.title,
            "status": self.status,
            "match_rate": self.match_rate or (round(self.matched_count / self.total_positions * 100, 1) if self.total_positions else 0.0),
            "vor_filename": self.vor_filename,
            "lsr_filename": self.lsr_filename,
            "total_positions": self.total_positions,
            "matched_count": self.matched_count,
            "discrepancy_count": self.discrepancy_count,
            "total_financial_risk": self.total_financial_risk,
            "created_at": self.created_at.strftime("%d.%m.%Y %H:%M") if self.created_at else ""
        }


class Document(Base):
    """Сущность DOCUMENTS из ER-диаграммы (содержится в проекте аудита)."""
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("audit_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    doc_type = Column(String(50), nullable=False)  # "VOR", "LSR"
    filename = Column(String(255), nullable=False)
    row_count = Column(Integer, default=0)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("AuditProject", back_populates="documents")

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "doc_type": self.doc_type,
            "filename": self.filename,
            "row_count": self.row_count,
            "uploaded_at": self.uploaded_at.strftime("%d.%m.%Y %H:%M") if self.uploaded_at else ""
        }


class MatchResult(Base):
    """Сущность MATCH_RESULTS из ER-диаграммы (формируется проектом аудита)."""
    __tablename__ = "match_results"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("audit_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    vor_num = Column(String(50), nullable=True)
    lsr_num = Column(String(50), nullable=True)
    upper_status = Column(String(50), nullable=False)  # ok, part, diff, none
    detail_class = Column(String(100), nullable=True)  # Расхождение объёма, Точное совпадение, etc.
    text_sim = Column(Float, default=0.0)
    qty_vor = Column(Float, nullable=True)
    qty_lsr = Column(Float, nullable=True)
    unit_price = Column(Float, nullable=True)
    financial_risk = Column(Float, default=0.0)
    formulation_warn = Column(Boolean, default=False)
    user_decision = Column(String(50), nullable=True)  # 'yes', 'no', None

    # Дополнительные поля для отображения и обратной совместимости
    row_num = Column(Integer, default=1)
    vor_name = Column(Text, nullable=False, default="")
    lsr_name = Column(Text, nullable=True)
    code = Column(String(100), nullable=True)
    unit = Column(String(50), nullable=True)
    is_ai = Column(Boolean, default=False)
    explanation = Column(Text, nullable=True)

    project = relationship("AuditProject", back_populates="match_results")

    # Свойства для прозрачной совместимости со старыми вызовами
    @property
    def status(self):
        return self.upper_status

    @status.setter
    def status(self, val):
        self.upper_status = val

    @property
    def similarity(self):
        return self.text_sim

    @similarity.setter
    def similarity(self, val):
        self.text_sim = val

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
            "s": self.upper_status,
            "detail_class": self.detail_class or "",
            "sim": round((self.text_sim or 0.0) * 100),
            "text_sim": self.text_sim or 0.0,
            "ai": self.is_ai,
            "note": self.explanation or "",
            "formulation_warn": self.formulation_warn,
            "decision": self.user_decision
        }


class LLMLog(Base):
    """Сущность LLM_LOGS из ER-диаграммы (фиксирует вызовы нейросети в проекте)."""
    __tablename__ = "llm_logs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("audit_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    vor_name = Column(Text, nullable=False)
    decision = Column(String(100), nullable=False)
    confidence = Column(Float, default=0.0)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    cost_rub = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("AuditProject", back_populates="llm_logs")

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "vor_name": self.vor_name,
            "decision": self.decision,
            "confidence": self.confidence,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_rub": self.cost_rub,
            "created_at": self.created_at.strftime("%d.%m.%Y %H:%M:%S") if self.created_at else ""
        }


# Псевдонимы классов для 100% обратной совместимости
Project = AuditProject
AuditItem = MatchResult


def init_db():
    """Создание таблиц по ER-диаграмме и инициализация базовых данных."""
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
