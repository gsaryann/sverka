import unittest
import os
import json
import io
import math
import openpyxl
from pathlib import Path
from web.web_app import app, sanitize_formula, check_login_rate_limit, _login_attempts
try:
    from db import SessionLocal, User, is_production
    HAS_DB = True
except (ImportError, ModuleNotFoundError):
    HAS_DB = False
    SessionLocal = User = is_production = None

def is_db_available() -> bool:
    if not HAS_DB or SessionLocal is None:
        return False
    try:
        sess = SessionLocal()
        from sqlalchemy import text
        sess.execute(text("SELECT 1"))
        sess.close()
        return True
    except Exception:
        return False

class TestWebLayerSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        cls.client = app.test_client()

    def test_results_isolated_between_users(self):
        """Задача 3 (п. 2.4): изоляция результатов между пользователями."""
        from web.web_app import set_user_results

        # Пользователь A сохраняет результаты
        sample_row = {
            "№ ВОР": "1", "Наименование ВОР": "Секретная позиция пользователя А",
            "Ед. изм. ВОР": "м", "Объём ВОР": 10.0,
            "№ ЛСР": "1", "Наименование ЛСР": "Секретная позиция ЛСР",
            "Ед. изм. ЛСР": "м", "Объём ЛСР": 10.0,
            "Верхний статус": "Совпало", "Детальный статус": "Совпало",
            "Разница объёмов": 0.0, "Цена за единицу (руб.)": 100.0,
            "Финансовый риск (руб.)": 0.0, "Статус решения сметчика": "Автоматически",
            "Обоснование": "", "ИИ-арбитраж": "", "Коэффициент пересчета": 1.0,
            "Уверенность": 1.0, "Сметная стоимость ЛСР (руб.)": 1000.0, "Раздел": "1"
        }
        set_user_results(1001, [sample_row])

        client_b = app.test_client()
        with client_b.session_transaction() as sess:
            sess['user_id'] = 1002
            sess['user_email'] = 'user_b@sverkasmet.ru'
            sess['user_role'] = 'estimator'

        # Пользователь B не видит данных A в CSV
        resp_csv = client_b.get('/api/download_csv')
        self.assertEqual(resp_csv.status_code, 400)
        self.assertNotIn("Секретная позиция пользователя А", resp_csv.get_data(as_text=True))

        # Пользователь B не может применить решение к строкам A
        resp_act = client_b.post('/api/action_row', json={'index': 0, 'action': 'yes'})
        self.assertEqual(resp_act.status_code, 400)

    def test_unauthenticated_access_blocked_401(self):
        """2.1: Маршруты API требуют обязательной авторизации (401)."""
        endpoints = [
            ("POST", "/api/compare"),
            ("POST", "/api/compare_stream"),
            ("GET", "/api/download_csv"),
            ("POST", "/api/export_discrepancy_act"),
            ("GET", "/api/projects"),
            ("GET", "/api/projects/1"),
            ("POST", "/api/action_row"),
            ("POST", "/api/benchmark"),
            ("POST", "/api/projects/save"),
            ("POST", "/api/projects/item_decision"),
        ]
        with app.test_client() as client:
            for method, url in endpoints:
                if method == "GET":
                    resp = client.get(url)
                else:
                    resp = client.post(url, json={})
                self.assertEqual(
                    resp.status_code, 401,
                    f"Маршрут {url} должен возвращать 401 без авторизации, получен {resp.status_code}"
                )

    def test_static_source_code_not_served(self):
        """2.5: Файлы исходного кода (.py) и кэша (__pycache__) не должны отдаваться клиенту (404)."""
        with app.test_client() as client:
            resp1 = client.get("/web_app.py")
            self.assertEqual(resp1.status_code, 404, "Исходный код web_app.py не должен быть доступен по HTTP!")
            resp2 = client.get("/__pycache__")
            self.assertEqual(resp2.status_code, 404)
            resp3 = client.get("/db.py")
            self.assertEqual(resp3.status_code, 404)

    def test_formula_injection_prevention(self):
        """2.9: Значения с =, +, -, @ должны экранироваться апострофом."""
        self.assertEqual(sanitize_formula('=HYPERLINK("http://evil.com","hack")'), '\'=HYPERLINK("http://evil.com","hack")')
        self.assertEqual(sanitize_formula('+12345'), "'+12345")
        self.assertEqual(sanitize_formula('-50'), "'-50")
        self.assertEqual(sanitize_formula('@SUM(A1:A10)'), "'@SUM(A1:A10)")
        self.assertEqual(sanitize_formula('Обычный текст'), 'Обычный текст')
        self.assertEqual(sanitize_formula(123), 123)

    def test_invalid_input_validation_returns_400(self):
        """2.10: Невалидный threshold (не число, nan, <0, >1) должен возвращать 400."""
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 99999

            for bad_thr in ["not-a-number", "-0.1", "1.5", "nan", "inf"]:
                resp = client.post("/api/compare", data={"threshold": bad_thr})
                self.assertEqual(
                    resp.status_code, 400,
                    f"Threshold '{bad_thr}' должен возвращать 400, получен {resp.status_code}"
                )

    def test_action_row_invalid_index_returns_400(self):
        """2.10: Невалидный индекс строки в api_action_row должен возвращать 400."""
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 99999

            for bad_idx in ["not-a-number", None, -5, 999999]:
                resp = client.post("/api/action_row", json={"index": bad_idx, "action": "confirm"})
                self.assertEqual(
                    resp.status_code, 400,
                    f"Индекс '{bad_idx}' должен возвращать 400, получен {resp.status_code}"
                )

    def test_login_rate_limiting(self):
        """2.13: Ограничение попыток входа (Rate Limiting)."""
        key = "test_ip:test_user@example.com"
        _login_attempts.pop(key, None)

        for _ in range(5):
            self.assertTrue(check_login_rate_limit(key, max_attempts=5, window_seconds=300))
        # 6-я попытка должна быть заблокирована
        self.assertFalse(check_login_rate_limit(key, max_attempts=5, window_seconds=300))

    def test_registration_always_forces_estimator_role(self):
        """2.3: Регистрация всегда назначает роль estimator, игнорируя тело запроса."""
        if not is_db_available():
            raise unittest.SkipTest("PostgreSQL недоступен: тест регистрации пропущен.")

        with app.test_client() as client:
            import secrets
            email = f"user_{secrets.token_hex(4)}@test.ru"
            resp = client.post("/api/auth/register", json={
                "email": email,
                "password": "Password123!",
                "full_name": "Тестовый Эксперт",
                "role": "lead"  # Попытка эскалации привилегий
            })
            self.assertIn(resp.status_code, (200, 201))
            data = resp.get_json()
            self.assertEqual(data["user"]["role"], "estimator", "Роль пользователя должна быть estimator!")

    def test_registration_min_password_length(self):
        """2.13: Пароль короче 8 символов отвергается с кодом 400."""
        with app.test_client() as client:
            resp = client.post("/api/auth/register", json={
                "email": "short_pwd@test.ru",
                "password": "12345",
                "full_name": "Тест"
            })
            self.assertEqual(resp.status_code, 400)
            data = resp.get_json()
            self.assertIn("8", data.get("error", ""))

if __name__ == "__main__":
    unittest.main()
