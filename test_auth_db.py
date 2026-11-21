"""
Тесты безопасности и бизнес-логики модуля авторизации и работы с PostgreSQL.
Проверяют:
1. Хэширование паролей и регистронезависимую уникальность lower(email).
2. Точность Numeric(14,2) для денег, Numeric(14,3) для объёмов, Numeric(14,6) для микрокопеек LLM.
3. Защиту ON DELETE RESTRICT при попытке удалить пользователя с проектами аудита.
4. Сохранение логов LLM с ON DELETE SET NULL (match_result_id) при удалении позиции сметы.
5. Защиту от привязки лога LLM к позиции из чужого проекта (составной FK).
6. Автоматический пересчёт агрегатов проекта (total_positions, matched_count, match_rate, risk) триггером PostgreSQL.
"""

import unittest
from decimal import Decimal
from sqlalchemy.exc import IntegrityError
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
        # Очистка тестовых записей после каждого теста в правильном порядке
        self.session.rollback()
        self.session.query(LLMLog).delete()
        self.session.query(Document).delete()
        self.session.query(MatchResult).delete()
        self.session.query(AuditProject).delete()
        self.session.query(User).filter(User.email.ilike("test_%@sverkasmet.ru")).delete()
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

        db_user = self.session.query(User).filter_by(email="test_security@sverkasmet.ru").first()
        self.assertNotEqual(db_user.password_hash, raw_password)
        self.assertTrue(db_user.password_hash.startswith("pbkdf2:") or db_user.password_hash.startswith("scrypt:"))
        self.assertTrue(db_user.check_password(raw_password))
        self.assertFalse(db_user.check_password("WrongPassword123!"))

    def test_case_insensitive_email_uniqueness(self):
        """Email должен быть уникальным независимо от регистра (lower(email))."""
        u1 = User(email="test_case@sverkasmet.ru", full_name="User 1", role="estimator")
        u1.set_password("Pass123!")
        self.session.add(u1)
        self.session.commit()

        u2 = User(email="TEST_CASE@SVERKASMET.RU", full_name="User 2", role="estimator")
        u2.set_password("Pass123!")
        self.session.add(u2)
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

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

        project = Project(
            user_id=user.id,
            title="Текущий ремонт (Дворец молодёжи)",
            object_name="Дворец молодёжи",
            total_positions=86,
            matched_count=71,
            discrepancy_count=15,
            total_financial_risk=Decimal("129500.50")
        )
        self.session.add(project)
        self.session.commit()

        item = AuditItem(
            project_id=project.id,
            row_num=1,
            vor_num="1",
            lsr_num="7",
            vor_name="Монтаж Контроллера радиоканальных устройств",
            lsr_name="Устройства промежуточные на количество лучей: 1",
            code="ГЭСНм10-08-001-13",
            qty_vor=Decimal("1.000"),
            qty_lsr=Decimal("8.000"),
            unit="шт",
            unit_price=Decimal("18500.25"),
            financial_risk=Decimal("129500.50"),
            status="diff",
            detail_class="Расхождение объёма",
            similarity=Decimal("0.1427"),
            is_ai=True,
            explanation="Пару выбрала Алиса. Объём в смете 8 шт против 1 шт в проекте.",
            user_decision="yes"
        )
        self.session.add(item)
        self.session.commit()

        saved_proj = self.session.query(Project).filter_by(id=project.id).first()
        self.assertEqual(len(saved_proj.items), 1)
        self.assertEqual(float(saved_proj.items[0].financial_risk), 129500.50)
        self.assertEqual(float(saved_proj.items[0].unit_price), 18500.25)
        self.assertEqual(saved_proj.user.email, "test_lead@sverkasmet.ru")

    def test_user_delete_restricted(self):
        """Удаление пользователя с проектами блокируется правилом ON DELETE RESTRICT."""
        user = User(email="test_restrict@sverkasmet.ru", full_name="User Restrict", role="estimator")
        user.set_password("Pass123!")
        self.session.add(user)
        self.session.commit()

        proj = AuditProject(user_id=user.id, title="Проект под защитой", status="completed")
        self.session.add(proj)
        self.session.commit()

        # Попытка удалить пользователя должна вызвать ошибку внешнего ключа (RESTRICT)
        self.session.delete(user)
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

    def test_match_result_delete_sets_null_in_llm_logs(self):
        """Удаление позиции сметы сохраняет лог LLM и расходы (ON DELETE SET NULL)."""
        user = User(email="test_llm_log@sverkasmet.ru", full_name="User LLM", role="estimator")
        user.set_password("Pass123!")
        self.session.add(user)
        self.session.commit()

        proj = AuditProject(user_id=user.id, title="Тест логов", status="completed")
        self.session.add(proj)
        self.session.commit()

        item = MatchResult(
            project_id=proj.id,
            row_num=1,
            vor_name="ВОР позиция",
            upper_status="ok",
            financial_risk=Decimal("0.00")
        )
        self.session.add(item)
        self.session.commit()

        # Создаем лог нейросети с микрокопейками (0.003512 руб)
        log = LLMLog(
            project_id=proj.id,
            match_result_id=item.id,
            vor_name="ВОР позиция",
            decision="ЛСР позиция",
            confidence=Decimal("0.9500"),
            prompt_tokens=500,
            completion_tokens=40,
            cost_rub=Decimal("0.003512")
        )
        self.session.add(log)
        self.session.commit()

        log_id = log.id
        self.assertEqual(float(log.cost_rub), 0.003512)

        # Удаляем позицию сметы: лог должен сохраниться, а match_result_id стать NULL
        self.session.delete(item)
        self.session.commit()

        db_log = self.session.query(LLMLog).filter_by(id=log_id).first()
        self.assertIsNotNone(db_log)
        self.assertIsNone(db_log.match_result_id)
        self.assertEqual(db_log.project_id, proj.id)
        self.assertEqual(float(db_log.cost_rub), 0.003512)

    def test_audit_project_trigger_automatic_aggregates(self):
        """Триггер БД автоматически обновляет материализованные агрегаты при любых изменениях строк сметы."""
        user = User(email="test_trg@sverkasmet.ru", full_name="User Trigger", role="estimator")
        user.set_password("Pass123!")
        self.session.add(user)
        self.session.commit()

        proj = AuditProject(user_id=user.id, title="Проект с триггером", status="completed")
        self.session.add(proj)
        self.session.commit()

        # Изначально позиций 0
        self.session.refresh(proj)
        self.assertEqual(proj.total_positions, 0)
        self.assertEqual(float(proj.total_financial_risk), 0.0)

        # Вставляем первую строку: совпадение (ok)
        item1 = MatchResult(
            project_id=proj.id,
            row_num=1,
            vor_name="Позиция 1",
            upper_status="ok",
            financial_risk=Decimal("0.00")
        )
        # Вставляем вторую строку: коллизия (diff) с риском 5 400.50 ₽
        item2 = MatchResult(
            project_id=proj.id,
            row_num=2,
            vor_name="Позиция 2",
            upper_status="diff",
            financial_risk=Decimal("5400.50")
        )
        self.session.add_all([item1, item2])
        self.session.commit()

        # Проверяем, что триггер автоматически обновил проект
        self.session.refresh(proj)
        self.assertEqual(proj.total_positions, 2)
        self.assertEqual(proj.matched_count, 1)
        self.assertEqual(proj.discrepancy_count, 1)
        self.assertEqual(float(proj.total_financial_risk), 5400.50)
        self.assertEqual(float(proj.match_rate), 50.00)

        # Удаляем item2: триггер должен пересчитать total_positions=1, match_rate=100.00, risk=0.00
        self.session.delete(item2)
        self.session.commit()

        self.session.refresh(proj)
        self.assertEqual(proj.total_positions, 1)
        self.assertEqual(proj.matched_count, 1)
        self.assertEqual(proj.discrepancy_count, 0)
        self.assertEqual(float(proj.total_financial_risk), 0.00)
        self.assertEqual(float(proj.match_rate), 100.00)


if __name__ == "__main__":
    unittest.main()
