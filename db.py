"""
Модуль базы данных PostgreSQL 17 для системы «СверкаСмет».
Обеспечивает промышленную реализацию ER-диаграммы платформы с учетом строгих финансовых
и нормативных требований:
- USERS (пользователи, роли, регистронезависимый email, timestamptz)
- AUDIT_PROJECTS (проекты аудита смет, BigInteger, ON DELETE RESTRICT для user_id, автосинхронизация агрегатов через триггер)
- DOCUMENTS (исходные документы: ВОР, ЛСР и др., BigInteger, timestamptz)
- MATCH_RESULTS (BigInteger, Numeric(14,3) для объемов, Numeric(14,2) для денег, CHECK, индексы)
- LLM_LOGS (BigInteger, микрокопейки Numeric(14,6), связь с match_results с защитой ON DELETE SET NULL)
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import (
    create_engine, Column, Integer, BigInteger, String, Numeric, Boolean,
    DateTime, Text, ForeignKey, desc, text, CheckConstraint, Index, UniqueConstraint
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

    id = Column(Integer, primary_key=True)
    email = Column(String(120), nullable=False)
    password_hash = Column(String(256), nullable=False)
    full_name = Column(String(150), nullable=False)
    role = Column(String(50), default="estimator", nullable=False)  # estimator, lead, admin
    company = Column(String(150), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

    __table_args__ = (
        CheckConstraint("role IN ('estimator', 'lead', 'admin')", name="check_user_role"),
        Index("ix_users_email_lower", text("lower(email)"), unique=True),
    )

    projects = relationship("AuditProject", back_populates="user")

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

    id = Column(BigInteger, primary_key=True)
    # ON DELETE RESTRICT защищает аудиты от случайного удаления пользователя
    user_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    title = Column(String(255), nullable=False)
    status = Column(String(50), default="completed", nullable=False)
    match_rate = Column(
        Numeric(5, 2), default=0.0, nullable=False,
        comment="Процент совпадения по проекту (шкала 0.00..100.00%)"
    )
    total_positions = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

    # Денормализованные материализованные агрегаты-кэш (поддерживаются триггером trg_match_results_aggregates)
    object_name = Column(String(255), nullable=True)
    vor_filename = Column(String(255), nullable=True)
    lsr_filename = Column(String(255), nullable=True)
    matched_count = Column(Integer, default=0, nullable=False)
    discrepancy_count = Column(Integer, default=0, nullable=False)
    total_financial_risk = Column(Numeric(14, 2), default=0.0, nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('completed', 'processing', 'draft', 'archived')", name="check_project_status"),
        CheckConstraint("match_rate >= 0 AND match_rate <= 100", name="check_project_match_rate"),
        CheckConstraint("total_positions >= 0", name="check_project_total_positions"),
        CheckConstraint("matched_count >= 0", name="check_project_matched_count"),
        CheckConstraint("discrepancy_count >= 0", name="check_project_discrepancy_count"),
        CheckConstraint("total_financial_risk >= 0", name="check_project_total_financial_risk"),
        # Индекс покрывает выборку проектов пользователя, упорядоченную по дате (одиночный индекс не нужен)
        Index("ix_audit_projects_user_created", "user_id", desc("created_at")),
    )

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
        mr = float(self.match_rate) if self.match_rate is not None else 0.0
        if mr == 0.0 and self.total_positions:
            mr = round(self.matched_count / self.total_positions * 100, 1)

        return {
            "id": self.id,
            "title": self.title,
            "object_name": self.object_name or self.title,
            "status": self.status,
            "match_rate": mr,
            "vor_filename": self.vor_filename,
            "lsr_filename": self.lsr_filename,
            "total_positions": self.total_positions,
            "matched_count": self.matched_count,
            "discrepancy_count": self.discrepancy_count,
            "total_financial_risk": float(self.total_financial_risk or 0.0),
            "created_at": self.created_at.strftime("%d.%m.%Y %H:%M") if self.created_at else ""
        }


class Document(Base):
    """Сущность DOCUMENTS из ER-диаграммы (содержится в проекте аудита)."""
    __tablename__ = "documents"

    id = Column(BigInteger, primary_key=True)
    project_id = Column(BigInteger, ForeignKey("audit_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    doc_type = Column(String(50), nullable=False)  # "VOR", "LSR", "ACT", "DOC"
    filename = Column(String(255), nullable=False)
    row_count = Column(Integer, default=0, nullable=False)
    uploaded_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

    __table_args__ = (
        CheckConstraint("doc_type IN ('VOR', 'LSR', 'ACT', 'DOC')", name="check_doc_type"),
        CheckConstraint("row_count >= 0", name="check_doc_row_count"),
    )

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

    id = Column(BigInteger, primary_key=True)
    project_id = Column(BigInteger, ForeignKey("audit_projects.id", ondelete="CASCADE"), nullable=False)
    vor_num = Column(String(50), nullable=True)
    lsr_num = Column(String(50), nullable=True)
    upper_status = Column(String(50), nullable=False)  # ok, part, diff, none
    detail_class = Column(String(100), nullable=True)  # Расхождение объёма, Точное совпадение, etc.
    text_sim = Column(
        Numeric(5, 4), nullable=True,
        comment="Косинусное/текстовое сходство наименований (шкала 0.0000..1.0000)"
    )
    qty_vor = Column(Numeric(14, 3), nullable=True)  # Сметные объемы: 3 знака после запятой
    qty_lsr = Column(Numeric(14, 3), nullable=True)
    unit_price = Column(Numeric(14, 2), nullable=True, comment="Цена за единицу (руб.)")
    financial_risk = Column(Numeric(14, 2), default=0.0, nullable=False)
    formulation_warn = Column(Boolean, default=False, nullable=False)
    user_decision = Column(String(50), nullable=True)  # 'yes', 'no', None

    # Дополнительные поля для отображения и обратной совместимости
    row_num = Column(Integer, default=1, nullable=False)
    vor_name = Column(Text, nullable=False, default="")
    lsr_name = Column(Text, nullable=True)
    code = Column(String(100), nullable=True)
    unit = Column(String(50), nullable=True)
    is_ai = Column(Boolean, default=False, nullable=False)
    explanation = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("upper_status IN ('ok', 'part', 'diff', 'none')", name="check_match_upper_status"),
        CheckConstraint("user_decision IN ('yes', 'no') OR user_decision IS NULL", name="check_match_user_decision"),
        CheckConstraint("text_sim IS NULL OR (text_sim >= 0 AND text_sim <= 1.0)", name="check_match_text_sim"),
        CheckConstraint("unit_price IS NULL OR unit_price >= 0", name="check_match_unit_price"),
        CheckConstraint("financial_risk >= 0", name="check_match_financial_risk"),
        Index("ix_match_results_proj_status", "project_id", "upper_status"),
        Index("ux_match_results_proj_row", "project_id", "row_num", unique=True),
        UniqueConstraint("id", "project_id", name="uq_match_results_id_project"),
    )

    project = relationship("AuditProject", back_populates="match_results")
    llm_logs = relationship("LLMLog", back_populates="match_result")

    # Свойства для прозрачной совместимости со старыми вызовами
    @property
    def status(self):
        return self.upper_status

    @status.setter
    def status(self, val):
        self.upper_status = val

    @property
    def similarity(self):
        return float(self.text_sim) if self.text_sim is not None else 0.0

    @similarity.setter
    def similarity(self, val):
        self.text_sim = val

    def to_dict(self):
        sim_val = float(self.text_sim) if self.text_sim is not None else None
        return {
            "id": self.id,
            "n": self.row_num,
            "vor_num": self.vor_num,
            "lsr_num": self.lsr_num,
            "vor": self.vor_name,
            "lsr": self.lsr_name or "",
            "code": self.code or "",
            "vv": float(self.qty_vor) if self.qty_vor is not None else None,
            "lv": float(self.qty_lsr) if self.qty_lsr is not None else None,
            "u": self.unit or "",
            "pr": float(self.unit_price) if self.unit_price is not None else 0.0,
            "risk": float(self.financial_risk or 0.0),
            "s": self.upper_status,
            "detail_class": self.detail_class or "",
            "sim": round(sim_val * 100) if sim_val is not None else 0,
            "text_sim": sim_val if sim_val is not None else 0.0,
            "ai": self.is_ai,
            "note": self.explanation or "",
            "formulation_warn": self.formulation_warn,
            "decision": self.user_decision
        }


class LLMLog(Base):
    """Сущность LLM_LOGS из ER-диаграммы (фиксирует вызовы нейросети в проекте)."""
    __tablename__ = "llm_logs"

    id = Column(BigInteger, primary_key=True)
    project_id = Column(BigInteger, ForeignKey("audit_projects.id", ondelete="CASCADE"), nullable=False)
    # match_result_id имеет внешний ключ к match_results.id с ON DELETE SET NULL,
    # а также валидируется составным внешним ключом fk_llm_logs_match_result_project
    match_result_id = Column(BigInteger, ForeignKey("match_results.id", ondelete="SET NULL"), nullable=True, index=True)
    vor_name = Column(Text, nullable=True)
    decision = Column(String(100), nullable=False)
    confidence = Column(
        Numeric(5, 4), default=0.0, nullable=False,
        comment="Уверенность LLM-модели в решении (шкала 0.0000..1.0000)"
    )
    prompt_tokens = Column(Integer, default=0, nullable=False)
    completion_tokens = Column(Integer, default=0, nullable=False)
    cost_rub = Column(
        Numeric(14, 6), default=0.0, nullable=False,
        comment="Стоимость вызова в рублях с микрокопейками (до 6 знаков)"
    )
    created_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1.0", name="check_llm_confidence"),
        CheckConstraint("prompt_tokens >= 0", name="check_llm_prompt_tokens"),
        CheckConstraint("completion_tokens >= 0", name="check_llm_completion_tokens"),
        CheckConstraint("cost_rub >= 0", name="check_llm_cost_rub"),
        Index("ix_llm_logs_proj_created", "project_id", "created_at"),
    )

    project = relationship("AuditProject", back_populates="llm_logs")
    match_result = relationship("MatchResult", back_populates="llm_logs")

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "match_result_id": self.match_result_id,
            "vor_name": self.vor_name or "",
            "decision": self.decision,
            "confidence": float(self.confidence or 0.0),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_rub": float(self.cost_rub or 0.0),
            "created_at": self.created_at.strftime("%d.%m.%Y %H:%M:%S") if self.created_at else ""
        }


# Псевдонимы классов для 100% обратной совместимости
Project = AuditProject
AuditItem = MatchResult


def init_db():
    """Создание таблиц по промышленной ER-диаграмме и инициализация базовых данных и триггеров."""
    Base.metadata.create_all(bind=engine)

    with engine.connect() as conn:
        # Удаляем дублирующиеся одиночные индексы, покрытые составными
        conn.execute(text("DROP INDEX IF EXISTS ix_audit_projects_user_id;"))
        conn.execute(text("DROP INDEX IF EXISTS ix_llm_logs_project_id;"))
        conn.execute(text("DROP INDEX IF EXISTS ix_match_results_project_id;"))

        # Составной внешний ключ в llm_logs, гарантирующий принадлежность match_result_id тому же project_id
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'fk_llm_logs_match_result_project'
                ) THEN
                    ALTER TABLE llm_logs ADD CONSTRAINT fk_llm_logs_match_result_project
                        FOREIGN KEY (match_result_id, project_id)
                        REFERENCES match_results (id, project_id)
                        ON DELETE SET NULL (match_result_id);
                END IF;
            END $$;
        """))

        # Триггер автосинхронизации материализованных агрегатов в audit_projects
        conn.execute(text("""
            CREATE OR REPLACE FUNCTION update_audit_project_aggregates()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $func$
            DECLARE
                v_project_id bigint;
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    v_project_id := OLD.project_id;
                ELSE
                    v_project_id := NEW.project_id;
                END IF;

                UPDATE audit_projects
                SET
                    total_positions = sub.total_pos,
                    matched_count = sub.matched_cnt,
                    discrepancy_count = sub.disc_cnt,
                    total_financial_risk = sub.tot_risk,
                    match_rate = CASE WHEN sub.total_pos > 0 
                                      THEN ROUND((sub.matched_cnt::numeric / sub.total_pos::numeric) * 100, 2)
                                      ELSE 0.00 END
                FROM (
                    SELECT 
                        COUNT(*) AS total_pos,
                        COUNT(*) FILTER (WHERE upper_status = 'ok') AS matched_cnt,
                        COUNT(*) FILTER (WHERE upper_status IN ('diff', 'part')) AS disc_cnt,
                        COALESCE(SUM(financial_risk), 0.00) AS tot_risk
                    FROM match_results
                    WHERE project_id = v_project_id
                ) sub
                WHERE id = v_project_id;

                RETURN NULL;
            END;
            $func$;

            DROP TRIGGER IF EXISTS trg_match_results_aggregates ON match_results;
            CREATE TRIGGER trg_match_results_aggregates
            AFTER INSERT OR UPDATE OR DELETE ON match_results
            FOR EACH ROW EXECUTE FUNCTION update_audit_project_aggregates();
        """))
        conn.commit()

    session = SessionLocal()
    try:
        demo_user = session.query(User).filter(text("lower(email) = 'demo@sverkasmet.ru'")).first()
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
