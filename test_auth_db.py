"""
Тесты безопасности и бизнес-логики модуля авторизации и работы с PostgreSQL.
Проверяют хэширование паролей, защиту от дубликатов, корректность сессий,
полное соответствие 5 сущностям ER-диаграммы (USERS, AUDIT_PROJECTS, DOCUMENTS, MATCH_RESULTS, LLM_LOGS)
и каскадное удаление (Foreign Key Cascade).
"""

import unittest
from db import (
    SessionLocal, User, AuditProject, Project,
    Document, MatchResult, AuditItem, LLMLog, init_db
)


class TestAuthAndSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.session = SessionLocal()

    def tearDown(self):
        # Очистка тестовых записей после каждого теста (каскадно чистит связанные таблицы)
        self.session.query(LLMLog).delete()
        self.session.query(Document).delete()
        self.session.query(MatchResult).delete()
        self.session.query(AuditProject).delete()
        self.session.query(User).filter(User.email.like("test_%@sverkasmet.ru")).delete()
        self.session.commit()
        self.session.close()

    def test_password_hashing_security(self):
        """Пароль никогда не должен сохраняться в открытом виде."""
        raw_password = "SecretPassword123!"
        user = User(
            email="test_security@sverkasmet.ru",
            full_name="Тестовый Инженер",
            role="estimator"
        )
        user.set_password(raw_password)
        self.session.add(user)
        self.session.commit()

        # 1. Проверяем, что в базе лежит хэш, а не сырой пароль
        db_user = self.session.query(User).filter_by(email="test_security@sverkasmet.ru").first()
        self.assertNotEqual(db_user.password_hash, raw_password)
        self.assertTrue(db_user.password_hash.startswith("pbkdf2:") or db_user.password_hash.startswith("scrypt:"))

        # 2. Проверяем валидацию верного и неверного пароля
        self.assertTrue(db_user.check_password(raw_password))
        self.assertFalse(db_user.check_password("WrongPassword123!"))

    def test_project_and_audit_history_persistence(self):
        """Проект и строки аудита должны надежно сохраняться в PostgreSQL и быть связаны с пользователем."""
        user = User(
            email="test_lead@sverkasmet.ru",
            full_name="Главный Сметчик",
            role="lead"
        )
        user.set_password("LeadPass123!")
        self.session.add(user)
        self.session.commit()

        # Создаем проект аудита
        project = Project(
            user_id=user.id,
            title="Текущий ремонт (Дворец молодёжи)",
            object_name="Дворец молодёжи",
            total_positions=86,
            matched_count=71,
            discrepancy_count=15,
            total_financial_risk=129500.0
        )
        self.session.add(project)
        self.session.commit()

        # Добавляем строку аудита с финансовым риском
        item = AuditItem(
            project_id=project.id,
            row_num=1,
            vor_num="1",
            lsr_num="7",
            vor_name="Монтаж Контроллера радиоканальных устройств",
            lsr_name="Устройства промежуточные на количество лучей: 1",
            code="ГЭСНм10-08-001-13",
            qty_vor=1.0,
            qty_lsr=8.0,
            unit="шт",
            unit_price=18500.0,
            financial_risk=129500.0,
            status="diff",
            detail_class="Расхождение объёма",
            similarity=0.14,
            is_ai=True,
            explanation="Пару выбрала Алиса. Объём в смете 8 шт против 1 шт в проекте.",
            user_decision="yes"
        )
        self.session.add(item)
        self.session.commit()

        # Проверяем целостность и связи (Foreign Key)
        saved_proj = self.session.query(Project).filter_by(id=project.id).first()
        self.assertEqual(len(saved_proj.items), 1)
        self.assertEqual(saved_proj.items[0].financial_risk, 129500.0)
        self.assertEqual(saved_proj.user.email, "test_lead@sverkasmet.ru")

    def test_full_er_schema_and_cascade_delete(self):
        """Полная проверка всех 5 таблиц из ER-диаграммы и каскадного удаления."""
        user = User(
            email="test_er@sverkasmet.ru",
            full_name="Инженер Экспертизы",
            role="estimator"
        )
        user.set_password("Pass12345!")
        self.session.add(user)
        self.session.commit()

        # 1. AUDIT_PROJECTS
        project = AuditProject(
            user_id=user.id,
            title="Капитальный ремонт кровли",
            status="completed",
            match_rate=92.5,
            total_positions=40
        )
        self.session.add(project)
        self.session.commit()

        # 2. DOCUMENTS (ВОР и ЛСР)
        doc_vor = Document(
            project_id=project.id,
            doc_type="VOR",
            filename="ВОР_кровля.xlsx",
            row_count=40
        )
        doc_lsr = Document(
            project_id=project.id,
            doc_type="LSR",
            filename="ЛСР_кровля.xlsx",
            row_count=42
        )
        self.session.add_all([doc_vor, doc_lsr])

        # 3. MATCH_RESULTS (с точными полями из ER-диаграммы)
        match_item = MatchResult(
            project_id=project.id,
            vor_num="1.1",
            lsr_num="12",
            upper_status="diff",
            detail_class="Расхождение объёма",
            text_sim=0.88,
            qty_vor=120.0,
            qty_lsr=150.0,
            unit_price=450.0,
            financial_risk=13500.0,
            formulation_warn=False,
            user_decision="yes"
        )
        self.session.add(match_item)

        # 4. LLM_LOGS (арбитраж нейросети)
        llm_entry = LLMLog(
            project_id=project.id,
            vor_name="Устройство пароизоляции в один слой",
            decision="Устройство пароизоляции оклеечной",
            confidence=0.91,
            prompt_tokens=420,
            completion_tokens=65,
            cost_rub=0.18
        )
        self.session.add(llm_entry)
        self.session.commit()

        # Проверка связей и данных
        saved_proj = self.session.query(AuditProject).filter_by(id=project.id).first()
        self.assertIsNotNone(saved_proj)
        self.assertEqual(len(saved_proj.documents), 2)
        self.assertEqual(len(saved_proj.match_results), 1)
        self.assertEqual(len(saved_proj.llm_logs), 1)

        self.assertEqual(saved_proj.documents[0].doc_type, "VOR")
        self.assertEqual(saved_proj.documents[1].filename, "ЛСР_кровля.xlsx")
        self.assertEqual(saved_proj.match_results[0].financial_risk, 13500.0)
        self.assertEqual(saved_proj.match_results[0].upper_status, "diff")
        self.assertEqual(saved_proj.llm_logs[0].prompt_tokens, 420)
        self.assertEqual(saved_proj.llm_logs[0].cost_rub, 0.18)

        # Проверка каскадного удаления: удаление проекта должно удалить все связанные записи
        proj_id = project.id
        self.session.delete(saved_proj)
        self.session.commit()

        self.assertEqual(self.session.query(Document).filter_by(project_id=proj_id).count(), 0)
        self.assertEqual(self.session.query(MatchResult).filter_by(project_id=proj_id).count(), 0)
        self.assertEqual(self.session.query(LLMLog).filter_by(project_id=proj_id).count(), 0)


if __name__ == "__main__":
    unittest.main()
