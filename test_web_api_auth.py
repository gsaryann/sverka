"""
TDD тесты эндпоинтов авторизации, сессий и сохранения проектов в PostgreSQL.
"""

import unittest
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from web.web_app import app
from db import init_db, SessionLocal, User, Project, AuditItem


class TestWebApiAuthAndProjects(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-secret-key-12345"

    def setUp(self):
        self.client = app.test_client()
        self.session = SessionLocal()

    def tearDown(self):
        self.session.query(AuditItem).delete()
        self.session.query(Project).delete()
        self.session.query(User).filter(User.email.like("api_test_%@sverkasmet.ru")).delete()
        self.session.commit()
        self.session.close()

    def test_register_and_login_flow(self):
        """Проверка регистрации, входа и получения сессии текущего пользователя."""
        # 1. Регистрация нового пользователя
        reg_payload = {
            "email": "api_test_new@sverkasmet.ru",
            "password": "StrongPassword123!",
            "full_name": "Иванов Иван Иванович",
            "role": "estimator",
            "company": "АО МосСтрой"
        }
        res = self.client.post("/api/auth/register", json=reg_payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data["user"]["email"], "api_test_new@sverkasmet.ru")

        # 2. Проверка сессии /api/auth/me
        res_me = self.client.get("/api/auth/me")
        self.assertEqual(res_me.status_code, 200)
        self.assertEqual(res_me.get_json()["user"]["email"], "api_test_new@sverkasmet.ru")

        # 3. Выход из системы
        res_logout = self.client.post("/api/auth/logout")
        self.assertEqual(res_logout.status_code, 200)

        # 4. Проверка после логаута (гость)
        res_guest = self.client.get("/api/auth/me")
        self.assertEqual(res_guest.status_code, 200)
        self.assertIsNone(res_guest.get_json()["user"])

        # 5. Повторный логин
        login_res = self.client.post("/api/auth/login", json={
            "email": "api_test_new@sverkasmet.ru",
            "password": "StrongPassword123!"
        })
        self.assertEqual(login_res.status_code, 200)
        self.assertTrue(login_res.get_json()["ok"])

    def test_save_and_retrieve_project_history(self):
        """Проверка сохранения результатов сверки в PostgreSQL и их чтения."""
        # Логинимся под демо-пользователем
        login_res = self.client.post("/api/auth/login", json={
            "email": "demo@sverkasmet.ru",
            "password": "P@ssw0rd"
        })
        self.assertEqual(login_res.status_code, 200)

        # Сохраняем проект
        project_payload = {
            "title": "Сверка СПС и СОУЭ Дворец молодежи",
            "object_name": "Дворец молодежи",
            "vor_filename": "ВОР.xlsx",
            "lsr_filename": "ЛСР.xlsx",
            "total_positions": 86,
            "matched_count": 71,
            "discrepancy_count": 15,
            "total_financial_risk": 18500.0,
            "items": [
                {
                    "n": 1,
                    "vor_num": "1",
                    "lsr_num": "7",
                    "vor": "Монтаж Контроллера",
                    "lsr": "Устройства промежуточные",
                    "code": "ГЭСНм10-08-001-13",
                    "vv": 1.0,
                    "lv": 8.0,
                    "u": "шт",
                    "pr": 18500.0,
                    "risk": 129500.0,
                    "s": "diff",
                    "detail_class": "Расхождение объёма",
                    "sim": 14,
                    "ai": True,
                    "note": "Пару выбрала Алиса",
                    "decision": "yes"
                }
            ]
        }
        save_res = self.client.post("/api/projects/save", json=project_payload)
        self.assertEqual(save_res.status_code, 201)
        project_id = save_res.get_json()["project"]["id"]

        # Получаем список проектов
        list_res = self.client.get("/api/projects")
        self.assertEqual(list_res.status_code, 200)
        projects = list_res.get_json()["projects"]
        self.assertTrue(any(p["id"] == project_id for p in projects))

        # Загружаем детальные данные сохраненного проекта
        detail_res = self.client.get(f"/api/projects/{project_id}")
        self.assertEqual(detail_res.status_code, 200)
        detail_data = detail_res.get_json()
        self.assertEqual(len(detail_data["items"]), 1)
        self.assertEqual(detail_data["items"][0]["code"], "ГЭСНм10-08-001-13")


if __name__ == "__main__":
    unittest.main()
