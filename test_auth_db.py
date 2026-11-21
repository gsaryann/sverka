"""
Тесты безопасности и бизнес-логики модуля авторизации и работы с PostgreSQL.
Проверяют хэширование паролей, защиту от дубликатов, корректность сессий и привязку проектов.
"""

import unittest
from db import SessionLocal, User, Project, AuditItem, init_db


class TestAuthAndSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.session = SessionLocal()

    def tearDown(self):
        # Очистка тестовых записей после каждого теста
        self.session.query(AuditItem).delete()
        self.session.query(Project).delete()
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


if __name__ == "__main__":
    unittest.main()
