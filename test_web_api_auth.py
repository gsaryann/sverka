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
        try:
            from sqlalchemy import text
            sess = SessionLocal()
            sess.execute(text("SELECT 1"))
            sess.close()
            init_db()
        except Exception as e:
            raise unittest.SkipTest(f"PostgreSQL недоступен: {e}")
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

        # Проверяем документы и LLM логи из новой схемы ER-диаграммы
        self.assertIn("documents", detail_data)
        self.assertEqual(len(detail_data["documents"]), 2)
        doc_types = {d["doc_type"] for d in detail_data["documents"]}
        self.assertEqual(doc_types, {"VOR", "LSR"})

        self.assertIn("llm_logs", detail_data)
        self.assertEqual(len(detail_data["llm_logs"]), 1)
        self.assertEqual(detail_data["llm_logs"][0]["vor_name"], "Монтаж Контроллера")

        # Проверяем принятие решения инженером через API
        item_id = detail_data["items"][0]["id"]
        dec_res = self.client.post("/api/projects/item_decision", json={
            "item_id": item_id,
            "decision": "no"
        })
        self.assertEqual(dec_res.status_code, 200)
        self.assertEqual(dec_res.get_json()["item"]["decision"], "no")

    def test_unrecognized_file_friendly_error(self):
        """Проверка понятного структурированного сообщения об ошибке при загрузке некорректного файла Excel."""
        import io
        import openpyxl

        # Создаем временный файл Excel со случайными листами опроса/интервью
        wb = openpyxl.Workbook()
        ws1 = wb.active
        ws1.title = "Как читать"
        ws1.append(["Инструкция", "Пояснения"])
        ws2 = wb.create_sheet("Результаты по вопросам")
        ws2.append(["Вопрос 1", "Ответ A", "Ответ B"])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        # Отправляем этот файл как ВОР, а валидную смету как ЛСР
        valid_lsr_path = ROOT_DIR / "data" / "ЛСР.xlsx"
        with open(valid_lsr_path, "rb") as f_lsr:
            data = {
                'vor': (buf, 'survey_data.xlsx'),
                'lsr': (io.BytesIO(f_lsr.read()), 'valid_lsr.xlsx')
            }
            res = self.client.post("/api/compare", data=data, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 400)
        resp_data = res.get_json()
        self.assertIn("error_title", resp_data)
        self.assertIn("error_message", resp_data)
        self.assertIn("error_hint", resp_data)
        self.assertTrue("структур" in resp_data["error_title"].lower() or "заголов" in resp_data["error_title"].lower())
        self.assertTrue("в формате .xlsx" in resp_data["error_hint"].lower())

    def test_export_discrepancy_act(self):
        """Проверка генерации официального Акта разногласий в Excel."""
        import web.web_app
        web.web_app.LAST_RESULTS = []

        # 1. Запрос без данных -> 400
        res_empty = self.client.get("/api/export_discrepancy_act")
        self.assertEqual(res_empty.status_code, 400)

        # 2. Запрос с позициями аудита
        payload = {
            "title": "Дворец молодёжи",
            "user_name": "Иванов И.И.",
            "items": [
                {
                    "n": 1,
                    "vor": "Монтаж Контроллера",
                    "lsr": "Устройства промежуточные",
                    "code": "ГЭСНм10-08-001-11",
                    "vv": 1.0,
                    "lv": 1.0,
                    "u": "шт",
                    "pr": 6592.26,
                    "risk": 0.0,
                    "status": "Требует проверки",
                    "decision": "yes",
                    "note": "Сопоставлено по объему"
                },
                {
                    "n": 2,
                    "vor": "Кабель ВВГнг-LS 3х1.5",
                    "lsr": "Кабель ВВГнг-LS 3х1.5",
                    "code": "ФСБЦ-21.2.02.00-001",
                    "vv": 100.0,
                    "lv": 150.0,
                    "u": "м",
                    "pr": 45.5,
                    "risk": 2275.0,
                    "status": "Расхождение объёма",
                    "decision": "no",
                    "note": "Объём в смете превышает ВОР на 50 м"
                }
            ]
        }
        res = self.client.post("/api/export_discrepancy_act", json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", res.content_type)
        self.assertIn("act_discrepancies.xlsx", res.headers.get("Content-Disposition", ""))
        self.assertGreater(len(res.data), 1000)

        # Проверим, что это читаемый openpyxl файл
        import openpyxl, io
        wb = openpyxl.load_workbook(io.BytesIO(res.data))
        self.assertIn("Акт разногласий", wb.sheetnames)
        ws = wb["Акт разногласий"]
        self.assertEqual(ws["A1"].value, "АКТ РАЗНОГЛАСИЙ И ВЕДОМОСТЬ РАСХОЖДЕНИЙ")
        self.assertIn("Дворец молодёжи", ws["C4"].value)
        # Проверяем строку с риском (строка 9)
        self.assertEqual(ws["J9"].value, 2275.0)

    def test_all_vkr_presets_comparison(self):
        """Проверка запуска сопоставления для всех демонстрационных комплектов ВКР."""
        presets_expected = [
            ("set1", 86),
            ("crystal", 137),
            ("kaluga", 534),
            ("set2", 83)
        ]
        for preset_key, expected_rows in presets_expected:
            res = self.client.post("/api/compare", data={"preset": preset_key, "mode": "algo", "threshold": "0.55"})
            self.assertEqual(res.status_code, 200, f"Preset {preset_key} returned {res.status_code}: {res.get_data(as_text=True)}")
            data = res.get_json()
            self.assertIn("rows", data)
            self.assertEqual(len(data["rows"]), expected_rows, f"Preset {preset_key} expected {expected_rows} rows, got {len(data['rows'])}")


if __name__ == "__main__":
    unittest.main()
