import unittest
import os
import json
import io
import math
import openpyxl
from pathlib import Path
from unittest.mock import patch
from web.web_app import app, sanitize_formula, check_login_rate_limit, _login_attempts, set_user_results
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

    def test_no_exception_text_leaks(self):
        """Задача 4: сервер не должен отдавать клиенту текст исключений (/secret/path SELECT password)."""
        from unittest.mock import patch

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 9999
            sess['user_email'] = 'test_leak@sverkasmet.ru'
            sess['user_role'] = 'lead'

        # 1. /api/compare при неожиданном исключении
        with patch('web.web_app._validate_document_pair', return_value=None), \
             patch('web.web_app.parse_vor', side_effect=Exception("/secret/path SELECT password")):
            data = {
                'vor': (io.BytesIO(b'dummy vor content'), 'vor.xlsx'),
                'lsr': (io.BytesIO(b'dummy lsr content'), 'lsr.xlsx')
            }
            resp = client.post('/api/compare', data=data, content_type='multipart/form-data')
            self.assertEqual(resp.status_code, 500)
            json_data = resp.get_json()
            self.assertNotIn("secret", str(json_data).lower())
            self.assertIn("error_id", json_data)

        # 2. /api/compare_stream при неожиданном исключении
        with patch('web.web_app._validate_document_pair', return_value=None), \
             patch('web.web_app.parse_vor', side_effect=Exception("/secret/path SELECT password")):
            data = {
                'vor': (io.BytesIO(b'dummy vor content'), 'vor.xlsx'),
                'lsr': (io.BytesIO(b'dummy lsr content'), 'lsr.xlsx')
            }
            resp_stream = client.post('/api/compare_stream', data=data, content_type='multipart/form-data')
            stream_body = resp_stream.get_data(as_text=True)
            self.assertNotIn("secret", stream_body.lower())
            self.assertIn("error_id", stream_body)

        # 3. Файл > 32 МБ -> ответ 413 в формате JSON
        huge_file = io.BytesIO(b"0" * (33 * 1024 * 1024))
        resp_413 = client.post('/api/compare', data={'vor': (huge_file, 'huge.xlsx')}, content_type='multipart/form-data')
        self.assertEqual(resp_413.status_code, 413)
        self.assertTrue(resp_413.is_json)
        self.assertIn("32 МБ", resp_413.get_json().get("error", ""))

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

    def test_demo_account_blocked_in_production_and_no_login_button(self):
        """2.6: В login.html отсутствует кнопка автовхода demo, а в production demo заблокирован (403)."""
        login_html_path = Path(__file__).resolve().parent / "web" / "login.html"
        if login_html_path.exists():
            html_text = login_html_path.read_text(encoding="utf-8")
            self.assertNotIn("demo@sverkasmet.ru", html_text, "Кнопка демо-входа с паролем не должна присутствовать в login.html")

        with app.test_client() as client:
            with patch("web.web_app.is_production", return_value=True):
                resp = client.post("/api/auth/login", json={
                    "email": "demo@sverkasmet.ru",
                    "password": "AnyPassword123!"
                })
                self.assertEqual(resp.status_code, 403)
                data = resp.get_json()
                self.assertIn("заблокирован", data.get("error", ""))

    def test_export_discrepancy_act_isolated_and_empty_rejected(self):
        """2.8: Акт разногласий строится из серверных результатов пользователя; пустой запрос дает 400."""
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 88888

            # Без данных на сервере и без items в теле -> 400
            resp_empty = client.post("/api/export_discrepancy_act", json={})
            self.assertEqual(resp_empty.status_code, 400)
            self.assertIn("Нет данных", resp_empty.get_json().get("error", ""))

            # С сохраненными серверными данными пользователя -> 200 Excel
            user_items = [{
                'ВОР №': '1', 'ВОР: наименование': 'Тестовая работа', 'ВОР: единица': 'м2', 'ВОР: количество': 10,
                'ЛСР №': '1', 'ЛСР: наименование': 'Тестовая работа', 'ЛСР: единица': 'м2', 'ЛСР: количество': 12,
                'financial_risk': 1500.0, 'unit_price': 750.0, 'Верхний статус': 'Расхождение', 'Исходный класс': 'Расхождение объема',
                'Причина решения и расхождения': 'Тестовое расхождение'
            }]
            set_user_results(88888, user_items)
            resp_ok = client.post("/api/export_discrepancy_act", json={"title": "Тестовый акт"})
            self.assertEqual(resp_ok.status_code, 200)
            self.assertEqual(resp_ok.mimetype, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def test_project_save_strict_validation(self):
        """2.10: Строгая валидация входных данных при сохранении проекта (400 при NaN, inf, мусоре)."""
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 77777

            # items не список или содержит не-словари
            resp1 = client.post("/api/projects/save", json={"items": "not-a-list"})
            self.assertEqual(resp1.status_code, 400)

            resp2 = client.post("/api/projects/save", json={"items": ["not-a-dict"]})
            self.assertEqual(resp2.status_code, 400)

            # Числовые поля с NaN или inf
            resp3 = client.post("/api/projects/save", json={"items": [], "total_financial_risk": float("nan")})
            self.assertEqual(resp3.status_code, 400)

            resp4 = client.post("/api/projects/save", json={"items": [], "total_positions": "invalid-int"})
            self.assertEqual(resp4.status_code, 400)

    def test_zip_bomb_safety_check(self):
        """2.12: Защита от zip-бомб отвергает архивы с превышением допустимого распакованного размера."""
        from web.web_app import validate_xlsx_safety
        import tempfile
        import zipfile

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tf:
            tf_path = Path(tf.name)

        try:
            with zipfile.ZipFile(tf_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                # Создаем файл с 200 КБ нулей, но лимит проверки ставим 100 КБ
                large_bytes = b"0" * (200 * 1024)
                zf.writestr("xl/worksheets/sheet1.xml", large_bytes)

            with self.assertRaises(ValueError) as cm:
                validate_xlsx_safety(tf_path, max_uncompressed_bytes=100 * 1024)
            self.assertIn("защита от zip-бомбы", str(cm.exception).lower())
        finally:
            tf_path.unlink(missing_ok=True)

    def test_max_items_limit_enforced(self):
        """Проверка ограничения MAX_ITEMS (400 при превышении лимита)."""
        from web.web_app import MAX_ITEMS
        self.assertEqual(MAX_ITEMS, 10000)

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 66666

            oversized_items = [{"n": i} for i in range(MAX_ITEMS + 1)]
            resp = client.post("/api/projects/save", json={"items": oversized_items})
            self.assertEqual(resp.status_code, 400)
            self.assertIn("10000", resp.get_json().get("error", ""))

    def test_session_clear_on_logout(self):
        """2.13: session.clear() полностью сбрасывает данные сессии при выходе."""
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user_id'] = 55555
                sess['custom_flag'] = 'secret'

            resp = client.post("/api/auth/logout")
            self.assertEqual(resp.status_code, 200)

            with client.session_transaction() as sess:
                self.assertNotIn('user_id', sess)
                self.assertNotIn('custom_flag', sess)


    def test_compare_hybrid_local_unreachable_returns_clear_error(self):
        """Задача 2: при выключенной Ollama режим hybrid_local возвращает 503 и понятную ошибку."""
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 9999
            sess['user_email'] = 'test_local@sverkasmet.ru'
            sess['user_role'] = 'user'

        vor_path = Path(__file__).parent / "data" / "ВОР.xlsx"
        lsr_path = Path(__file__).parent / "data" / "ЛСР.xlsx"
        with patch.dict(os.environ, {"LOCAL_LLM_BASE_URL": "http://127.0.0.1:59999/v1"}), \
             open(vor_path, "rb") as f_v, open(lsr_path, "rb") as f_l:
            data = {
                "vor": (f_v, "ВОР.xlsx"),
                "lsr": (f_l, "ЛСР.xlsx"),
                "mode": "hybrid_local",
                "threshold": "0.55"
            }
            resp = client.post("/api/compare", data=data, content_type="multipart/form-data")
            self.assertEqual(resp.status_code, 503)
            res_json = resp.get_json()
            self.assertIn("error", res_json)
            self.assertIn("error_id", res_json)
            self.assertIn("ollama", res_json["error"].lower())

    def test_compare_hybrid_local_uses_local_client(self):
        """Задача 2: режим hybrid_local использует LocalClient, provider=='local', cost_rub==0, без YandexClient."""
        import pytest
        openai_mod = pytest.importorskip("openai")
        if not hasattr(openai_mod, "OpenAI"):
            raise unittest.SkipTest("Требуется установленная библиотека openai")
        import http.server
        import threading
        from test_llm_resolver import _FakeOllamaHandler

        httpd = http.server.HTTPServer(("127.0.0.1", 0), _FakeOllamaHandler)
        port = httpd.server_port
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            client = app.test_client()
            with client.session_transaction() as sess:
                sess['user_id'] = 9999
                sess['user_email'] = 'test_local@sverkasmet.ru'
                sess['user_role'] = 'user'

            vor_path = Path(__file__).parent / "data" / "ВОР.xlsx"
            lsr_path = Path(__file__).parent / "data" / "ЛСР.xlsx"
            with patch.dict(os.environ, {
                "LOCAL_LLM_BASE_URL": f"http://127.0.0.1:{port}/v1",
                "LOCAL_LLM_MODEL": "qwen2.5:7b-instruct"
            }), patch("llm_resolver.YandexClient") as mock_yandex, \
                 open(vor_path, "rb") as f_v, open(lsr_path, "rb") as f_l:
                data = {
                    "vor": (f_v, "ВОР.xlsx"),
                    "lsr": (f_l, "ЛСР.xlsx"),
                    "mode": "hybrid_local",
                    "threshold": "0.55"
                }
                resp = client.post("/api/compare", data=data, content_type="multipart/form-data")
                self.assertEqual(resp.status_code, 200)
                res_json = resp.get_json()
                self.assertIn("stats", res_json)
                llm_stats = res_json["stats"].get("llm_stats")
                self.assertIsNotNone(llm_stats)
                self.assertEqual(llm_stats.get("provider"), "local")
                self.assertEqual(llm_stats.get("cost_rub"), 0)
                # Убеждаемся, что YandexClient не создавался и внешних запросов не было
                mock_yandex.assert_not_called()
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_compare_hybrid_local_without_openai_returns_503(self):
        """При отсутствии пакета openai режим hybrid_local возвращает 503 в формате error_response."""
        import sys
        import http.server
        import threading
        from test_llm_resolver import _FakeOllamaHandler

        httpd = http.server.HTTPServer(("127.0.0.1", 0), _FakeOllamaHandler)
        port = httpd.server_port
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            client = app.test_client()
            with client.session_transaction() as sess:
                sess['user_id'] = 9999
                sess['user_email'] = 'test_local@sverkasmet.ru'
                sess['user_role'] = 'user'

            vor_path = Path(__file__).parent / "data" / "ВОР.xlsx"
            lsr_path = Path(__file__).parent / "data" / "ЛСР.xlsx"
            with patch.dict(os.environ, {
                "LOCAL_LLM_BASE_URL": f"http://127.0.0.1:{port}/v1",
                "LOCAL_LLM_MODEL": "qwen2.5:7b-instruct"
            }), patch.dict(sys.modules, {"openai": None}), \
                 open(vor_path, "rb") as f_v, open(lsr_path, "rb") as f_l:
                data = {
                    "vor": (f_v, "ВОР.xlsx"),
                    "lsr": (f_l, "ЛСР.xlsx"),
                    "mode": "hybrid_local",
                    "threshold": "0.55"
                }
                resp = client.post("/api/compare", data=data, content_type="multipart/form-data")
                self.assertEqual(resp.status_code, 503)
                res_json = resp.get_json()
                self.assertIn("error", res_json)
                self.assertIn("error_id", res_json)
                self.assertIn("не установлена библиотека openai", res_json["error"].lower())
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_compare_stream_ping_interval(self):
        """В /api/compare_stream комментарий : ping отправляется не чаще раза в 10 секунд (< 3 за 1 секунду)."""
        import time

        def slow_resolve(results, vor, lsr, cli, **kwargs):
            time.sleep(1.1)
            return results, {"provider": "yandex", "cost_rub": 0}

        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 9999
            sess['user_email'] = 'test_ping@sverkasmet.ru'
            sess['user_role'] = 'user'

        vor_path = Path(__file__).parent / "data" / "ВОР.xlsx"
        lsr_path = Path(__file__).parent / "data" / "ЛСР.xlsx"
        with patch("llm_resolver.make_client", return_value=object()), \
             patch("llm_resolver.resolve", side_effect=slow_resolve), \
             open(vor_path, "rb") as f_v, open(lsr_path, "rb") as f_l:
            data = {
                "vor": (f_v, "ВОР.xlsx"),
                "lsr": (f_l, "ЛСР.xlsx"),
                "mode": "hybrid",
                "threshold": "0.55"
            }
            resp = client.post("/api/compare_stream", data=data, content_type="multipart/form-data")
            self.assertEqual(resp.status_code, 200)
            body = resp.get_data(as_text=True)
            ping_count = body.count(": ping")
            self.assertLess(ping_count, 3)

    def _make_failing_session_factory(self, secret_exc_msg: str, exc_cls=OSError):
        class FailingSession:
            def query(self, *args, **kwargs):
                raise exc_cls(secret_exc_msg)

            def execute(self, *args, **kwargs):
                raise exc_cls(secret_exc_msg)

            def close(self):
                pass

        return lambda: FailingSession()

    def test_login_returns_503_json_when_db_unavailable(self):
        """При недоступной БД POST /api/auth/login возвращает 503 JSON с error_id и без утечки исключения."""
        secret_msg = "FATAL: password authentication failed for user secret_pg_pass"
        client = app.test_client()
        with patch("web.web_app.SessionLocal", self._make_failing_session_factory(secret_msg)):
            resp = client.post("/api/auth/login", json={"email": "u@example.com", "password": "Password123!"})
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.content_type, "application/json")
        data = resp.get_json()
        self.assertIn("error", data)
        self.assertIn("error_id", data)
        self.assertIn("postgresql", data["error"].lower())
        self.assertNotIn(secret_msg, json.dumps(data, ensure_ascii=False))

    def test_register_returns_503_json_when_db_unavailable(self):
        """При недоступной БД POST /api/auth/register возвращает 503 JSON с error_id и без утечки исключения."""
        secret_msg = "could not connect to server: secret_db_host:5432"
        client = app.test_client()
        with patch("web.web_app.SessionLocal", self._make_failing_session_factory(secret_msg)):
            resp = client.post("/api/auth/register", json={
                "email": "u2@example.com",
                "password": "Password123!",
                "full_name": "Тестов Тест"
            })
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.content_type, "application/json")
        data = resp.get_json()
        self.assertIn("error", data)
        self.assertIn("error_id", data)
        self.assertIn("postgresql", data["error"].lower())
        self.assertNotIn(secret_msg, json.dumps(data, ensure_ascii=False))

    def test_me_returns_503_json_when_db_unavailable(self):
        """При недоступной БД GET /api/auth/me (с сессией) возвращает 503 JSON с error_id."""
        secret_msg = "connection refused secret_db_host:5432"
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = 123
        with patch("web.web_app.SessionLocal", self._make_failing_session_factory(secret_msg)):
            resp = client.get("/api/auth/me")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.content_type, "application/json")
        data = resp.get_json()
        self.assertIn("error", data)
        self.assertIn("error_id", data)
        self.assertIn("postgresql", data["error"].lower())
        self.assertNotIn(secret_msg, json.dumps(data, ensure_ascii=False))

    def test_unhandled_exception_in_api_returns_json_500(self):
        """Необработанное исключение под /api/* возвращает JSON 500 с error_id, а не HTML."""
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = 9999
        with patch("web.web_app.SessionLocal", side_effect=RuntimeError("boom_secret_detail")):
            resp = client.get("/api/projects")
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.content_type, "application/json")
        data = resp.get_json()
        self.assertIn("error", data)
        self.assertIn("error_id", data)
        self.assertNotIn("boom_secret_detail", json.dumps(data, ensure_ascii=False))

    def test_check_db_connection_reports_unreachable(self):
        """При недоступной БД check_db_connection() возвращает (False, текст) без пароля из DB_PASS."""
        from web.web_app import check_db_connection
        secret_pass = "SuperSecretDbPass987!"
        with patch.dict(os.environ, {"DB_PASS": secret_pass}), \
             patch("web.web_app.SessionLocal", self._make_failing_session_factory(f"auth failed for {secret_pass}")):
            ok, msg = check_db_connection()
        self.assertFalse(ok)
        self.assertTrue(len(msg) > 0)
        self.assertNotIn(secret_pass, msg)

    def test_health_endpoint_reports_db_state(self):
        """GET /api/health возвращает 200 с db: false при недоступной БД и без секретов."""
        secret_pass = "AnotherSecretDbPass123!"
        client = app.test_client()
        with patch.dict(os.environ, {"DB_PASS": secret_pass}), \
             patch("web.web_app.SessionLocal", self._make_failing_session_factory(f"bad pass {secret_pass}")):
            resp = client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("ok"))
        self.assertFalse(data.get("db"))
        self.assertNotIn(secret_pass, json.dumps(data, ensure_ascii=False))

    def test_login_returns_503_on_psycopg2_operational_error(self):
        """Реальная ошибка psycopg2.OperationalError (fe_sendauth) возвращает 503 JSON с error_id."""
        import pytest
        psycopg2 = pytest.importorskip("psycopg2")
        secret_msg = "fe_sendauth: no password supplied"
        client = app.test_client()
        with patch("web.web_app.SessionLocal", self._make_failing_session_factory(secret_msg, psycopg2.OperationalError)):
            resp = client.post("/api/auth/login", json={"email": "u@example.com", "password": "Password123!"})
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.content_type, "application/json")
        data = resp.get_json()
        self.assertIn("error", data)
        self.assertIn("error_id", data)
        self.assertNotIn(secret_msg, json.dumps(data, ensure_ascii=False))

    def test_login_non_db_exception_returns_json_500(self):
        """Постороннее исключение (ValueError) внутри api_login уходит в общий обработчик 500, а не 503."""
        client = app.test_client()
        with patch("web.web_app.SessionLocal", self._make_failing_session_factory("unexpected_logic_bug", ValueError)):
            resp = client.post("/api/auth/login", json={"email": "u@example.com", "password": "Password123!"})
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.content_type, "application/json")
        data = resp.get_json()
        self.assertIn("error", data)
        self.assertIn("error_id", data)
        self.assertNotIn("unexpected_logic_bug", json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
