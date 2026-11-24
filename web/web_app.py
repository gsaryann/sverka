"""Сервер веб-интерфейса СверкаСмет (SmartMatcher).

Запуск:
    python web_app.py
или из корня проекта:
    python web/web_app.py
"""
import os
import sys
import io
import csv
import json
import logging
import copy
import hashlib
import re
import random
import tempfile
import threading
import queue
import webbrowser
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

# Автоматическое подключение корневой папки проекта в sys.path ДО любых локальных импортов
WEB_DIR = Path(__file__).resolve().parent
ROOT_DIR = WEB_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import zipfile
import secrets
import time
import math
from functools import wraps
from flask import Flask, request, jsonify, Response, stream_with_context, session, redirect
from sqlalchemy import desc, text
from db import (
    SessionLocal, User, Project, AuditProject,
    AuditItem, MatchResult, Document, LLMLog, init_db, is_production, IS_PROD
)

logger = logging.getLogger(__name__)

from parsers import parse_vor, parse_lsr, get_parse_warnings, Item
from risk import calculate_item_risk


def _document_kind(path: Path) -> str | None:
    """Classify an uploaded workbook from its title and table headers."""
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        text = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 45), values_only=True):
                text.extend(str(v).lower().replace('ё', 'е') for v in row if v is not None)
    finally:
        wb.close()
    blob = ' '.join(text)
    cleaned_blob = re.sub(r'№\s*(?:в\s*)?лср', '', blob)

    vor_score = 0
    if re.search(r'ведомост\w* объем\w* работ', blob): vor_score += 2
    if re.search(r'дефектн\w* ведомост\w*', blob): vor_score += 2
    if re.search(r'формула расчета объемов работ', blob): vor_score += 2
    if re.search(r'\bвор\b', blob): vor_score += 1

    lsr_score = 0
    if re.search(r'локальн\w* смет\w* расчет', blob): lsr_score += 2
    if re.search(r'локальная смета', blob): lsr_score += 2
    if re.search(r'сметная стоимость', blob): lsr_score += 2
    if re.search(r'составлен\w* в ценах', blob): lsr_score += 1
    if re.search(r'\bлср\b', cleaned_blob): lsr_score += 1

    if vor_score == lsr_score:
        return None
    return 'vor' if vor_score > lsr_score else 'lsr'


def _resolve_preset_paths(preset: str | None) -> tuple[Path, Path] | None:
    """Определяет пути к файлам ВОР и ЛСР для эталонных демонстрационных комплектов."""
    if not preset:
        return None
    p = str(preset).strip().lower()
    if p in ('set1', 'palace', 'дворец'):
        return DATA_DIR / "ВОР.xlsx", DATA_DIR / "ЛСР.xlsx"
    elif p in ('crystal', 'lighting', 'кристалл', 'освещение'):
        return DATA_DIR / "ВОР освещение КОРР.xlsx", DATA_DIR / "ЛСР освещение КОРР.xlsx"
    elif p in ('kaluga', 'cabinets', 'калуга', 'кабинеты'):
        return DATA_DIR / "ВОР (1 этаж кабинеты).xlsx", DATA_DIR / "ЛСР (1 этаж кабинеты).xlsx"
    elif p in ('set2', 'room163', 'пом163'):
        return DATA_DIR / "ВЕДОМОСТЬ ОБЪЕМОВ РАБОТ.xlsx", DATA_DIR / "ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЕТ.xlsx"
    elif p in ('tea', 'anastasyevka', 'анастасьевка', 'чайная'):
        return (
            DATA_DIR / "02_01_01_чайная_Анастасьевка__Текущий_ремонт___Дефектная_ведомость_по_смете_2.xlsx",
            DATA_DIR / "02_01_01_чайная_Анастасьевка__Текущий_ремонт___ЛСР_по_Методике_2020__РИМ__2.xlsx"
        )
    return None


def _validate_document_pair(vor_path: Path, lsr_path: Path) -> str | None:
    if hashlib.sha256(vor_path.read_bytes()).digest() == hashlib.sha256(lsr_path.read_bytes()).digest():
        return 'Загружен один и тот же файл в оба поля. Выберите отдельные ВОР и ЛСР.'
    kind_v, kind_l = _document_kind(vor_path), _document_kind(lsr_path)
    if kind_v == kind_l and kind_v in ('vor', 'lsr'):
        label = 'ВОР' if kind_v == 'vor' else 'ЛСР'
        return f'В оба поля загружены документы типа {label}. Для сверки нужны одна ВОР и одна ЛСР.'
    if kind_v == 'lsr' and kind_l == 'vor':
        return 'Файлы, похоже, перепутаны: в поле ВОР загружена ЛСР, а в поле ЛСР — ВОР. Поменяйте их местами и запустите сверку снова.'
    return None


def format_parsing_error(e: Exception) -> tuple[dict, int]:
    err_str = str(e)
    # Ошибка отсутствия сметных заголовков
    if "Не удалось определить заголовки" in err_str:
        is_vor = "VOR" in err_str
        is_lsr = "LSR" in err_str
        doc_kind = "ведомости объёмов работ (ВОР)" if is_vor else ("локального сметного расчёта (ЛСР)" if is_lsr else "сметного документа")
        sheets = ""
        if "Листы книги:" in err_str:
            try:
                sheets = err_str.split("Листы книги:")[1].split(".")[0].strip()
            except Exception:
                sheets = ""
        
        return {
            'error': f"Не удалось распознать структуру {doc_kind}.",
            'error_title': f"Не удалось распознать структуру {doc_kind}",
            'error_message': (
                f"Загруженный файл не содержит обязательных колонок строительной сметы "
                f"(«Наименование работ / затрат», «Количество / Объём», «Единица измерения»)."
            ),
            'error_details': f"Обнаруженные листы в файле: {sheets}" if sheets else None,
            'error_hint': "Убедитесь, что загружаете корректную ведомость объёмов работ (ВОР), дефектную ведомость или локальную смету (по Методике 421/пр) в формате .xlsx."
        }, 400

    if "Заголовки" in err_str and "позиции не распознаны" in err_str:
        return {
            'error': "Заголовки сметы найдены, но строки с работами не распознаны.",
            'error_title': "Строки с работами не распознаны",
            'error_message': "В таблице найдены заголовки колонок, но не удалось извлечь ни одной заполненной позиции работ с объёмами.",
            'error_hint': "Проверьте, заполнены ли ячейки с наименованиями и количеством в загруженной таблице Excel."
        }, 400

    if "InvalidFileException" in type(e).__name__ or "not a valid xlsx" in err_str.lower() or "zipfile" in err_str.lower():
        return {
            'error': "Файл не является корректным документом Excel (.xlsx).",
            'error_title': "Некорректный формат файла",
            'error_message': "Файл повреждён либо имеет неподдерживаемый формат (поддерживаются только файлы .xlsx).",
            'error_hint': "Сохраните файл в Microsoft Excel как «Книга Excel (.xlsx)» и повторите загрузку."
        }, 400

    err_id = secrets.token_hex(4).upper()
    logger.exception("Internal error [%s]: %s", err_id, err_str)
    return {
        'error': f"Внутренняя ошибка сервера (код {err_id})",
        'error_id': err_id,
        'error_title': "Ошибка при обработке сметного документа",
        'error_message': "Произошла непредвиденная ошибка при обработке сметного документа.",
        'error_hint': "Проверьте корректность загруженных файлов или обратитесь к администратору с указанием кода ошибки."
    }, 500
import match
import baseline_legacy
import perturb
import evaluate

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024


@app.errorhandler(413)
def request_entity_too_large(e):
    return jsonify({
        'error': 'Размер файла превышает допустимый лимит (32 МБ)',
        'error_title': 'Файл слишком большой',
        'error_message': 'Максимальный допустимый размер сметного документа составляет 32 МБ.',
        'error_hint': 'Разбейте смету на разделы или уменьшите размер файла перед загрузкой.'
    }), 413


# Конфигурация безопасности сессий и секретного ключа
COMPROMISED_KEYS = {
    "sverkasmet-secure-key-2026-b2b",
    "your-secret-key-here",
    "change-me",
    "replace-with-a-secure-secret-key",
    "placeholder",
}

_secret = os.getenv("SECRET_KEY", "").strip()
if is_production():
    if not _secret or _secret in COMPROMISED_KEYS or len(_secret) < 32:
        raise RuntimeError("CRITICAL SECURITY ERROR: В production-окружении переменная SECRET_KEY обязательна, должна быть длиной от 32 символов и не совпадать с шаблонными/скомпрометированными ключами!")
else:
    if not _secret or _secret in COMPROMISED_KEYS or len(_secret) < 32:
        _secret = secrets.token_hex(32)
        logger.warning("SECRET_KEY не задан или ненадежен. Для разработки сгенерирован временный 256-битный ключ.")
app.secret_key = _secret

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
if is_production():
    app.config["SESSION_COOKIE_SECURE"] = True


# Декораторы контроля доступа и ролей
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Необходима авторизация', 'code': 'UNAUTHORIZED'}), 401
        return f(*args, **kwargs)
    return decorated_function


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_id = session.get('user_id')
            if not user_id:
                return jsonify({'error': 'Необходима авторизация', 'code': 'UNAUTHORIZED'}), 401
            db_sess = SessionLocal()
            try:
                user = db_sess.query(User).filter_by(id=user_id).first()
                if not user or user.role not in roles:
                    return jsonify({'error': 'Недостаточно прав для выполнения операции', 'code': 'FORBIDDEN'}), 403
            finally:
                db_sess.close()
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# Защита от формульных инъекций (=, +, -, @)
def sanitize_formula(val: Any) -> Any:
    if isinstance(val, str) and val.startswith(('=', '+', '-', '@')):
        return "'" + val
    return val


def validate_xlsx_safety(path: Path, max_uncompressed_bytes: int = 100 * 1024 * 1024) -> None:
    """Защита от zip-бомб и поврежденных архивов."""
    if not zipfile.is_zipfile(path):
        return
    total_size = 0
    with zipfile.ZipFile(path, 'r') as z:
        for info in z.infolist():
            total_size += info.file_size
            if total_size > max_uncompressed_bytes:
                raise ValueError("Файл превышает допустимый размер в распакованном виде (защита от zip-бомбы).")


# Ограничение частоты попыток входа (Rate Limiting)
_login_attempts: Dict[str, List[float]] = {}
_login_lock = threading.Lock()

def check_login_rate_limit(key: str, max_attempts: int = 5, window_seconds: int = 300) -> bool:
    now = time.time()
    with _login_lock:
        attempts = [t for t in _login_attempts.get(key, []) if now - t < window_seconds]
        if len(attempts) >= max_attempts:
            _login_attempts[key] = attempts
            return False
        attempts.append(now)
        _login_attempts[key] = attempts
        return True


@app.teardown_appcontext
def remove_db_session(exception=None):
    try:
        SessionLocal.remove()
    except Exception:
        pass

DATA_DIR = ROOT_DIR / "data"
RESULTS_DIR = ROOT_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Потокобезопасное хранение результатов сверки по пользователям (вместо глобальных списков)
_user_results_lock = threading.Lock()
_USER_RESULTS: Dict[str, Dict[str, Any]] = {}

def set_user_results(user_id: Any, rows: List[Dict[str, Any]]) -> None:
    with _user_results_lock:
        _USER_RESULTS[str(user_id)] = {
            'last': copy.deepcopy(rows),
            'orig': copy.deepcopy(rows)
        }

def get_user_results(user_id: Any) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    with _user_results_lock:
        res = _USER_RESULTS.get(str(user_id))
        if not res:
            return [], []
        return res['last'], res['orig']

def update_user_row(user_id: Any, idx: int, action: str) -> Optional[Dict[str, Any]]:
    with _user_results_lock:
        res = _USER_RESULTS.get(str(user_id))
        if not res or not (0 <= idx < len(res['last'])):
            return None
        row = res['last'][idx]
        orig = res['orig'][idx]
        if action == 'yes':
            row['Верхний статус'] = 'Совпало'
            row['Статус решения сметчика'] = 'Принято сметчиком'
        elif action == 'no':
            row['Верхний статус'] = 'Расхождение'
            row['Статус решения сметчика'] = 'В правку (отклонено)'
        elif action == 'undo':
            res['last'][idx] = copy.deepcopy(orig)
            row = res['last'][idx]
        return copy.deepcopy(row)

FIELDS = [
    'ВОР №', 'ВОР строка', 'ВОР раздел', 'ВОР: наименование', 'ВОР: единица', 'ВОР: количество',
    'ЛСР №', 'ЛСР строка', 'ЛСР раздел', 'ЛСР шифр', 'ЛСР: наименование', 'ЛСР: единица', 'ЛСР: количество',
    'unit_price', 'total_price', 'financial_risk',
    'Текстовое сходство', 'Уверенность', 'Результат алгоритма', 'Причина решения и расхождения',
    'Коллизия (неоднозначность)', 'Решение ИИ-арбитра',
    'Статус решения сметчика', 'Исходный класс', 'Верхний статус', 'Предупреждение о формулировке',
    'Причина предупреждения', 'Условие предупреждения'
]


@app.route('/favicon.ico')
@app.route('/favicon.svg')
def favicon():
    fav_path = WEB_DIR / "favicon.svg"
    return Response(fav_path.read_bytes(), mimetype="image/svg+xml")


@app.route('/app_concepts')
def app_concepts():
    c_path = WEB_DIR / "app_concepts.html"
    return Response(c_path.read_text(encoding="utf-8"), mimetype="text/html")


@app.route('/concepts')
def concepts():
    c_path = WEB_DIR / "landing_concepts.html"
    return Response(c_path.read_text(encoding="utf-8"), mimetype="text/html")


@app.route('/')
def landing():
    landing_path = WEB_DIR / "landing.html"
    return Response(landing_path.read_text(encoding="utf-8"), mimetype="text/html")


@app.route('/login')
def login():
    login_path = WEB_DIR / "login.html"
    return Response(login_path.read_text(encoding="utf-8"), mimetype="text/html")


@app.route('/app')
def app_view():
    if not session.get('user_id'):
        return redirect('/login')
    html_path = WEB_DIR / "index.html"
    resp = Response(html_path.read_text(encoding="utf-8"), mimetype="text/html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route('/style.css')
def style():
    css_path = WEB_DIR / "style.css"
    resp = Response(css_path.read_text(encoding="utf-8"), mimetype="text/css")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route('/app.js')
def script():
    js_path = WEB_DIR / "app.js"
    resp = Response(js_path.read_text(encoding="utf-8"), mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


def format_rows(results: List[Dict[str, Any]], vor: List[Item], lsr: List[Item], llm_active: bool = False):
    vor_by_num = {str(x.num): x for x in vor}
    lsr_by_num = {str(x.num): x for x in lsr}

    rows: List[Dict[str, Any]] = []
    stats: Dict[str, int] = {}

    for r in results:
        v = r.get('vor_item') or (vor_by_num.get(str(r.get('vor'))) if r.get('vor') is not None else None)
        l = r.get('lsr_item') or (lsr_by_num.get(str(r.get('lsr'))) if r.get('lsr') is not None else None)

        status = str(r.get('cls') or '')
        high_status = r.get('upper_status') or match.upper_status(
            status, r.get('formulation_warning', False)
        )
        stats[high_status] = stats.get(high_status, 0) + 1

        unit_price = getattr(l, 'unit_price', None) if l else None
        total_price = getattr(l, 'total_price', None) if l else None

        # Расчёт финансового риска по реальной расценке ЛСР через единый модуль risk:
        delta_v, risk_rub, risk_status = calculate_item_risk(
            v.qty if v else None,
            v.unit if v else '',
            l.qty if l else None,
            l.unit if l else '',
            unit_price
        )

        rows.append({
            'ВОР №': str(v.num) if v else '',
            'ВОР строка': v.row if v else (r.get('vor_row') or ''),
            'ВОР раздел': getattr(v, 'section', '') if v else '',
            'ВОР: наименование': v.name if v else '',
            'ВОР: единица': v.unit if v else '',
            'ВОР: количество': v.qty if v else '',
            'ЛСР №': str(l.num) if l else '',
            'ЛСР строка': l.row if l else (r.get('lsr_row') or ''),
            'ЛСР раздел': getattr(l, 'section', '') if l else '',
            'ЛСР шифр': l.code if l else '',
            'ЛСР: наименование': l.name if l else '',
            'ЛСР: единица': l.unit if l else '',
            'ЛСР: количество': l.qty if l else '',
            'unit_price': unit_price,
            'total_price': total_price,
            'financial_risk': risk_rub,
            'delta_v': delta_v,
            'risk_status': risk_status,
            'Текстовое сходство': round(float(r.get('text_sim', 0.0)), 4),
            'Уверенность': round(float(r.get('score', 0.0)), 4),
            'Результат алгоритма': status,
            'Исходный класс': status,
            'Верхний статус': high_status,
            'Предупреждение о формулировке': bool(r.get('formulation_warning', False)),
            'Причина предупреждения': str(r.get('formulation_warning_reason') or ''),
            'Условие предупреждения': '; '.join(r.get('formulation_warning_conditions', [])),
            'Причина решения и расхождения': str(r.get('explanation') or ''),
            'Коллизия (неоднозначность)': str(r.get('conflict_reason') or ''),
            'Решение ИИ-арбитра': str(r.get('ai_decision') or 'Не привлекался'),
            'is_ambiguous': bool(r.get('is_ambiguous', False)),
            'ambiguity_type': str(r.get('ambiguity_type') or ''),
            'competing_candidates': r.get('competing_candidates', []),
            'Статус решения сметчика': 'Авто'
        })
    return rows, stats


@app.route('/api/compare', methods=['POST'])
@login_required
def api_compare():
    global LAST_RESULTS, ORIG_RESULTS
    user_id = session.get('user_id')
    mode = request.form.get('mode', 'algo')
    preset = request.form.get('preset')

    if preset:
        # 2.1: Пресеты только для роли lead на сервере
        db_sess = SessionLocal()
        try:
            u = db_sess.query(User).filter_by(id=user_id).first()
            if not u or u.role != 'lead':
                return jsonify({'error': 'Доступ к эталонным пресетам разрешен только для роли lead', 'code': 'FORBIDDEN'}), 403
        finally:
            db_sess.close()

    thr_raw = request.form.get('threshold', 0.50)
    try:
        thr = float(thr_raw)
        if math.isnan(thr) or math.isinf(thr) or not (0.0 <= thr <= 1.0):
            return jsonify({'error': 'Порог сходства (threshold) должен быть числом от 0.0 до 1.0'}), 400
    except (ValueError, TypeError):
        return jsonify({'error': 'Некорректное значение порога сходства (threshold)'}), 400

    tmp_files_to_clean = []

    try:
        preset_paths = _resolve_preset_paths(preset)
        if preset_paths:
            vor_path, lsr_path = preset_paths
        else:
            if 'vor' not in request.files or 'lsr' not in request.files:
                return jsonify({'error': 'Не переданы файлы ВОР и ЛСР'}), 400

            file_v = request.files['vor']
            file_l = request.files['lsr']

            tmp_v = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
            tmp_files_to_clean.append(Path(tmp_v.name))
            file_v.save(tmp_v.name)
            tmp_v.close()

            tmp_l = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
            tmp_files_to_clean.append(Path(tmp_l.name))
            file_l.save(tmp_l.name)
            tmp_l.close()

            vor_path = Path(tmp_v.name)
            lsr_path = Path(tmp_l.name)

            # Защита от zip-бомб
            validate_xlsx_safety(vor_path)
            validate_xlsx_safety(lsr_path)

        if not vor_path.exists() or not lsr_path.exists():
            return jsonify({'error': 'Файлы документов не найдены'}), 404

        pair_error = _validate_document_pair(vor_path, lsr_path)
        if pair_error:
            return jsonify({
                'error': pair_error,
                'error_title': 'Несоответствие пары документов',
                'error_message': pair_error,
                'error_hint': 'Для сверки требуется одна ведомость объёмов работ (ВОР) и один локальный сметный расчёт (ЛСР).'
            }), 400

        vor = parse_vor(str(vor_path))
        parse_warnings = get_parse_warnings()
        lsr = parse_lsr(str(lsr_path))
        parse_warnings += get_parse_warnings()

        is_compat, overlap_ratio, compat_msg = match.check_document_compatibility(vor, lsr)
        warning_msg = None
        if not is_compat:
            warning_msg = (
                f"{compat_msg} Обращение к ИИ-арбитру заблокировано: "
                "предотвращен нецелевой расход бюджета токенов на несогласованные документы."
            )
            if mode in ('hybrid', 'arbitration', 'hybrid_weak', 'model_only'):
                mode = 'algo'

        llm_stats = None

        if mode == 'model_only':
            from llm_resolver import YandexClient, resolve, model_only_results
            client = YandexClient()
            cache_path = str(RESULTS_DIR / "llm_cache.json")
            init_res = model_only_results(vor, lsr)
            results, llm_stats = resolve(init_res, vor, lsr, client, mode='model_only', cache_path=cache_path, verbose=False)
        elif mode == 'legacy':
            results = baseline_legacy.match(vor, lsr)
        else:
            results = match.match(vor, lsr, thr=thr, min_text_threshold=0.20)

            if mode in ('hybrid', 'arbitration'):
                from llm_resolver import YandexClient, resolve
                client = YandexClient()
                cache_path = str(RESULTS_DIR / "llm_cache.json")
                results, llm_stats = resolve(results, vor, lsr, client, mode='arbitration', cache_path=cache_path, verbose=False)
            elif mode == 'hybrid_weak':
                from llm_resolver import YandexClient, resolve
                client = YandexClient()
                cache_path = str(RESULTS_DIR / "llm_cache.json")
                results, llm_stats = resolve(results, vor, lsr, client, mode='weak_only', cache_path=cache_path, verbose=False)

        llm_needed = mode in ('hybrid', 'arbitration', 'hybrid_weak', 'model_only')
        rows, stats = format_rows(results, vor, lsr, llm_active=llm_needed)

        LAST_RESULTS = rows
        ORIG_RESULTS = copy.deepcopy(rows)
        set_user_results(user_id, rows)

        if llm_stats:
            stats['llm_stats'] = llm_stats

        resp_payload = {'stats': stats, 'rows': rows, 'parse_warnings': parse_warnings}
        if warning_msg:
            resp_payload['warning'] = warning_msg

        return jsonify(resp_payload)

    except Exception as e:
        resp, status = format_parsing_error(e)
        return jsonify(resp), status
    finally:
        for p in tmp_files_to_clean:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass


@app.route('/api/compare_stream', methods=['POST'])
@login_required
def api_compare_stream():
    global LAST_RESULTS, ORIG_RESULTS
    user_id = session.get('user_id')
    mode = request.form.get('mode', 'algo')
    preset = request.form.get('preset')

    if preset:
        # 2.1: Пресеты только для роли lead на сервере
        db_sess = SessionLocal()
        try:
            u = db_sess.query(User).filter_by(id=user_id).first()
            if not u or u.role != 'lead':
                return jsonify({'error': 'Доступ к эталонным пресетам разрешен только для роли lead', 'code': 'FORBIDDEN'}), 403
        finally:
            db_sess.close()

    thr_raw = request.form.get('threshold', 0.50)
    try:
        thr = float(thr_raw)
        if math.isnan(thr) or math.isinf(thr) or not (0.0 <= thr <= 1.0):
            return jsonify({'error': 'Порог сходства (threshold) должен быть числом от 0.0 до 1.0'}), 400
    except (ValueError, TypeError):
        return jsonify({'error': 'Некорректное значение порога сходства (threshold)'}), 400

    tmp_files_to_clean = []

    try:
        preset_paths = _resolve_preset_paths(preset)
        if preset_paths:
            vor_path, lsr_path = preset_paths
        else:
            if 'vor' not in request.files or 'lsr' not in request.files:
                return jsonify({'error': 'Не переданы файлы ВОР и ЛСР'}), 400

            file_v = request.files['vor']
            file_l = request.files['lsr']

            tmp_v = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
            tmp_files_to_clean.append(Path(tmp_v.name))
            file_v.save(tmp_v.name)
            tmp_v.close()

            tmp_l = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
            tmp_files_to_clean.append(Path(tmp_l.name))
            file_l.save(tmp_l.name)
            tmp_l.close()

            vor_path = Path(tmp_v.name)
            lsr_path = Path(tmp_l.name)

            # Защита от zip-бомб
            validate_xlsx_safety(vor_path)
            validate_xlsx_safety(lsr_path)

        if not vor_path.exists() or not lsr_path.exists():
            for p in tmp_files_to_clean:
                p.unlink(missing_ok=True)
            return jsonify({'error': 'Файлы документов не найдены'}), 404

        pair_error = _validate_document_pair(vor_path, lsr_path)
        if pair_error:
            for p in tmp_files_to_clean:
                p.unlink(missing_ok=True)
            return jsonify({
                'error': pair_error,
                'error_title': 'Несоответствие пары документов',
                'error_message': pair_error,
                'error_hint': 'Для сверки требуется одна ведомость объёмов работ (ВОР) и один локальный сметный расчёт (ЛСР).'
            }), 400

        vor = parse_vor(str(vor_path))
        parse_warnings = get_parse_warnings()
        lsr = parse_lsr(str(lsr_path))
        parse_warnings += get_parse_warnings()

        is_compat, overlap_ratio, compat_msg = match.check_document_compatibility(vor, lsr)
        warning_msg = None
        if not is_compat:
            warning_msg = (
                f"{compat_msg} Обращение к ИИ-арбитру заблокировано: "
                "предотвращен нецелевой расход бюджета токенов на несогласованные документы."
            )

    except Exception as e:
        for p in tmp_files_to_clean:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        resp, status = format_parsing_error(e)
        return jsonify(resp), status

    def generate():
        global LAST_RESULTS, ORIG_RESULTS
        try:
            stream_mode = mode
            if not is_compat and stream_mode in ('hybrid', 'arbitration', 'hybrid_weak', 'model_only'):
                stream_mode = 'algo'

            # 1. Мгновенный расчет SmartMatcher (0.05 сек)
            if stream_mode == 'legacy':
                results = baseline_legacy.match(vor, lsr)
            elif stream_mode == 'model_only':
                from llm_resolver import model_only_results
                results = model_only_results(vor, lsr)
            else:
                results = match.match(vor, lsr, thr=thr, min_text_threshold=0.20)

            llm_needed = (stream_mode in ('hybrid', 'arbitration', 'hybrid_weak', 'model_only')) and is_compat
            init_rows, init_stats = format_rows(results, vor, lsr, llm_active=llm_needed)
            LAST_RESULTS = init_rows
            ORIG_RESULTS = copy.deepcopy(init_rows)
            set_user_results(user_id, init_rows)

            ambig_count = sum(
                1 for r in results
                if (r.get('is_ambiguous') or
                    r.get('cls') == 'Нет в рассматриваемой смете' or
                    (float(r.get('text_sim', 1.0)) < 0.40 and r.get('cls') != 'Дубль'))
            )

            # Передаем первичное состояние сопоставления клиенту мгновенно
            yield f"data: {json.dumps({'type': 'init', 'stats': init_stats, 'rows': init_rows, 'ambig_count': ambig_count, 'mode': stream_mode, 'needs_llm': bool(llm_needed and ambig_count > 0), 'warning': warning_msg, 'parse_warnings': parse_warnings}, ensure_ascii=False)}\n\n"

            # 2. Потоковый арбитраж спорных позиций Алисой
            if llm_needed and ambig_count > 0:
                from llm_resolver import YandexClient, resolve
                client = YandexClient()
                cache_path = str(RESULTS_DIR / "llm_cache.json")
                m_mode = 'model_only' if stream_mode == 'model_only' else ('weak_only' if stream_mode == 'hybrid_weak' else 'arbitration')

                q = queue.Queue()

                def on_progress(done, total, info):
                    pct = int(done / max(total, 1) * 100)
                    q.put({
                        'type': 'progress',
                        'done': done,
                        'total': total,
                        'percent': pct,
                        'item_name': info.get('name', ''),
                        'vor_num': info.get('vor_num', '')
                    })

                def worker():
                    try:
                        res, llm_stats = resolve(
                            results, vor, lsr, client,
                            mode=m_mode,
                            cache_path=cache_path,
                            verbose=False,
                            progress_callback=on_progress
                        )
                        fin_rows, fin_stats = format_rows(res, vor, lsr, llm_active=True)
                        fin_stats['llm_stats'] = llm_stats
                        q.put({
                            'type': 'done',
                            'rows': fin_rows,
                            'stats': fin_stats,
                            'llm_stats': llm_stats,
                            'warning': warning_msg
                        })
                    except Exception as err:
                        q.put({'type': 'error', 'error': str(err)})
                    finally:
                        q.put(None)

                t = threading.Thread(target=worker, daemon=True)
                t.start()

                while True:
                    try:
                        item = q.get(timeout=0.25)
                        if item is None:
                            break
                        if item.get('type') == 'done':
                            LAST_RESULTS = item['rows']
                            ORIG_RESULTS = copy.deepcopy(item['rows'])
                            set_user_results(user_id, item['rows'])
                        yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                    except queue.Empty:
                        if not t.is_alive():
                            while not q.empty():
                                item = q.get_nowait()
                                if item is not None:
                                    if item.get('type') == 'done':
                                        LAST_RESULTS = item['rows']
                                        ORIG_RESULTS = copy.deepcopy(item['rows'])
                                        set_user_results(user_id, item['rows'])
                                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                            break
                        yield ": ping\n\n"
            else:
                yield f"data: {json.dumps({'type': 'done', 'rows': init_rows, 'stats': init_stats, 'warning': warning_msg}, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"
        finally:
            for p in tmp_files_to_clean:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@app.route('/api/action_row', methods=['POST'])
@login_required
def api_action_row():
    """Обработка решения сметчика по спорной строке (по BPMN)."""
    user_id = session.get('user_id')
    data = request.get_json(silent=True) or {}
    idx_raw = data.get('index')
    act = data.get('action')

    try:
        idx = int(idx_raw)
    except (ValueError, TypeError):
        return jsonify({'error': 'Индекс строки должен быть целым числом'}), 400

    row = update_user_row(user_id, idx, act)
    if row is None:
        return jsonify({'error': 'Неверный индекс строки или отсутствуют данные сверки'}), 400

    return jsonify({'ok': True, 'row': row})


@app.route('/api/benchmark', methods=['POST'])
@login_required
@role_required('lead')
def api_benchmark():
    try:
        benchmark_warnings = []
        data = request.get_json() or {}
        preset = data.get('preset', 'set1')
        shuffle = bool(data.get('shuffle', False))
        stress = bool(data.get('stress', True))

        preset_paths = _resolve_preset_paths(preset)
        if preset_paths:
            vor_path, lsr_path = preset_paths
        else:
            vor_path = DATA_DIR / "ВОР.xlsx"
            lsr_path = DATA_DIR / "ЛСР.xlsx"

        vor = parse_vor(str(vor_path))
        lsr = parse_lsr(str(lsr_path))

        if stress:
            pv, truth = perturb.make_set(vor, lsr, seed=1, shuffle_order=shuffle)
        else:
            lnums = {str(x.num) for x in lsr}
            if shuffle:
                rnd = random.Random(1)
                pv = list(vor)
                rnd.shuffle(pv)
            else:
                pv = list(vor)
            
            # Проверяем наличие явных ссылок на номера ЛСР
            has_refs = any(v.ref and str(v.ref).strip() in lnums for v in pv)
            if has_refs:
                truth = [dict(vor=v.num, lsr=v.ref, cls='Совпало') for v in pv if str(v.ref).strip() in lnums]
            elif len(vor) == len(lsr) and all(str(v.num) in lnums for v in pv):
                # Для комплектов 1-к-1 без отдельного столбца ссылок (например, Комплект 2)
                truth = [dict(vor=v.num, lsr=v.num, cls='Совпало') for v in pv]
            else:
                # Поиск точных текстовых соответствий
                lsr_by_name = {l.name.strip().lower(): str(l.num) for l in lsr}
                truth = []
                for v in pv:
                    k = v.name.strip().lower()
                    if k in lsr_by_name:
                        truth.append(dict(vor=v.num, lsr=lsr_by_name[k], cls='Совпало'))

        if not truth:
            return jsonify({
                'error': 'В исходном документе ВОР отсутствуют эталонные ссылки («№ в ЛСР»). '
                         'Включите опцию «Синтетический стресс-тест» для объективной оценки качества на искажениях.'
            }), 400

        methods_data = []

        # 1. Legacy Baseline
        preds_legacy = baseline_legacy.match(pv, lsr, thr=0.55, w_q=0.3, w_o=0.4)
        ev_legacy = evaluate.evaluate(preds_legacy, truth, lsr)
        methods_data.append({
            'name': 'Базовый TF-IDF (Legacy Baseline)',
            'prec': ev_legacy['prec'],
            'rec': ev_legacy['rec'],
            'f1': ev_legacy['f1'],
            'cls_acc': ev_legacy['cls_acc'],
            'nv_prec': ev_legacy['nv_prec'],
            'nv_rec': ev_legacy['nv_rec']
        })

        # 2. SmartMatcher v2
        preds_smart = match.match(pv, lsr, thr=0.50, min_text_threshold=0.20)
        ev_smart = evaluate.evaluate(preds_smart, truth, lsr)
        methods_data.append({
            'name': 'SmartMatcher v2 (Разработанный алгоритм)',
            'prec': ev_smart['prec'],
            'rec': ev_smart['rec'],
            'f1': ev_smart['f1'],
            'cls_acc': ev_smart['cls_acc'],
            'nv_prec': ev_smart['nv_prec'],
            'nv_rec': ev_smart['nv_rec']
        })

        # 3. SmartMatcher + Алиса (Двухуровневый арбитраж коллизий)
        try:
            from llm_resolver import YandexClient, resolve
            cache_path = str(RESULTS_DIR / "llm_cache.json")
            client = YandexClient()
            preds_llm, st_llm = resolve(
                copy.deepcopy(preds_smart), pv, lsr, client,
                mode="arbitration", cache_path=cache_path, verbose=False
            )
            ev_llm = evaluate.evaluate(preds_llm, truth, lsr)
            methods_data.append({
                'name': 'SmartMatcher + Алиса (Арбитраж коллизий)',
                'prec': ev_llm['prec'],
                'rec': ev_llm['rec'],
                'f1': ev_llm['f1'],
                'cls_acc': ev_llm['cls_acc'],
                'nv_prec': ev_llm['nv_prec'],
                'nv_rec': ev_llm['nv_rec']
            })
        except Exception as e:
            logger.exception("Не удалось выполнить LLM-арбитраж в бенчмарке")
            benchmark_warnings.append(f"LLM-арбитраж не выполнен: {e}")

        conf_list = []
        for (t_cls, p_cls), cnt in sorted(ev_smart['conf'].items(), key=lambda x: -x[1])[:8]:
            conf_list.append({
                'true_cls': t_cls,
                'pred_cls': p_cls,
                'count': cnt
            })

        return jsonify({
            'methods': methods_data,
            'confusion': conf_list,
            'warnings': benchmark_warnings
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/download_csv')
@login_required
def api_download_csv():
    user_id = session.get('user_id')
    last_res, _ = get_user_results(user_id)
    if not last_res:
        return jsonify({'error': 'Нет сформированных результатов сверки для выгрузки'}), 400

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=FIELDS, delimiter=';')
    writer.writeheader()
    sanitized_rows = []
    for r in last_res:
        sr = {}
        for k, v in r.items():
            sr[k] = sanitize_formula(v)
        sanitized_rows.append(sr)
    writer.writerows(sanitized_rows)

    csv_bytes = output.getvalue().encode('utf-8-sig')
    return Response(
        csv_bytes,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=sverka_results.csv"}
    )


def generate_discrepancy_act_excel(items: List[Dict[str, Any]], title: str = "Сверка сметной документации", user_name: str = "Инженер-сметчик") -> io.BytesIO:
    """Генерация официального Акта разногласий (Дефектной ведомости расхождений) в формате Excel."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from datetime import datetime

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Акт разногласий"
    ws.views.sheetView[0].showGridLines = True

    c_navy = "1F3A5F"
    c_diff_bg = "FFF3E0"  # фон для расхождений объёма / коллизий
    c_none_bg = "FFEBEE"  # фон для отсутствующих в смете
    c_total_bg = "E6EBF1"

    font_title = Font(name="Calibri", size=15, bold=True, color="1F3A5F")
    font_sub = Font(name="Calibri", size=10, italic=True, color="5F6F84")
    font_meta = Font(name="Calibri", size=10, bold=False, color="1D2733")
    font_meta_b = Font(name="Calibri", size=10, bold=True, color="1F3A5F")
    font_th = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    font_td = Font(name="Calibri", size=10, color="1D2733")
    font_diff = Font(name="Calibri", size=10, bold=True, color="C2561B")
    font_total = Font(name="Calibri", size=11, bold=True, color="1F3A5F")

    fill_th = PatternFill(start_color=c_navy, end_color=c_navy, fill_type="solid")
    fill_diff = PatternFill(start_color=c_diff_bg, end_color=c_diff_bg, fill_type="solid")
    fill_none = PatternFill(start_color=c_none_bg, end_color=c_none_bg, fill_type="solid")
    fill_total = PatternFill(start_color=c_total_bg, end_color=c_total_bg, fill_type="solid")

    thin_border = Side(border_style="thin", color="D3DAE3")
    border_cell = Border(left=thin_border, right=thin_border, top=thin_border, bottom=thin_border)
    border_total = Border(top=Side(border_style="double", color="1F3A5F"), bottom=thin_border, left=thin_border, right=thin_border)

    # 1. Шапка документа
    ws.merge_cells("A1:M1")
    ws["A1"] = "АКТ РАЗНОГЛАСИЙ И ВЕДОМОСТЬ РАСХОЖДЕНИЙ"
    ws["A1"].font = font_title
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")

    ws.merge_cells("A2:M2")
    ws["A2"] = "по результатам сопоставления Ведомости объёмов работ (ВОР) и Локального сметного расчёта (ЛСР по Методике 421/пр)"
    ws["A2"].font = font_sub
    ws["A2"].alignment = Alignment(horizontal="left", vertical="center")

    date_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    ws["A4"] = "Объект строительства:"
    ws["A4"].font = font_meta_b
    ws["C4"] = sanitize_formula(title or "Объект сметного аудита")
    ws["C4"].font = font_meta

    ws["A5"] = "Дата формирования:"
    ws["A5"].font = font_meta_b
    ws["C5"] = date_str
    ws["C5"].font = font_meta

    ws["G4"] = "Ответственный сметчик:"
    ws["G4"].font = font_meta_b
    ws["I4"] = sanitize_formula(user_name or "Инженер-сметчик")
    ws["I4"].font = font_meta

    # 2. Заголовки таблицы
    headers = [
        "№ п/п",
        "Позиция ВОР (Проект)",
        "Позиция / Расценка ЛСР (Смета)",
        "Сметный шифр",
        "Объём ВОР",
        "Объём ЛСР",
        "Разница ΔV",
        "Ед. изм.",
        "Сметная цена за ед., ₽",
        "Финансовый риск, ₽",
        "Статус сопоставления",
        "Решение сметчика",
        "Обоснование / Примечание"
    ]

    header_row = 7
    ws.row_dimensions[header_row].height = 28
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col_idx, value=h)
        cell.font = font_th
        cell.fill = fill_th
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border_cell

    current_row = header_row + 1
    total_risk = 0.0

    for idx, it in enumerate(items, 1):
        ws.row_dimensions[current_row].height = 22

        n = it.get('n', idx)
        vor_name = sanitize_formula(it.get('vor') or it.get('ВОР: наименование') or '')
        lsr_name = sanitize_formula(it.get('lsr') or it.get('ЛСР: наименование') or '')
        code = sanitize_formula(it.get('code') or it.get('ЛСР шифр') or '')

        vv = it.get('vv') if it.get('vv') is not None else it.get('ВОР: количество')
        lv = it.get('lv') if it.get('lv') is not None else it.get('ЛСР: количество')
        try:
            vv_val = float(vv) if vv is not None and vv != '' else None
            if vv_val is not None and (math.isnan(vv_val) or math.isinf(vv_val)):
                vv_val = None
        except (ValueError, TypeError):
            vv_val = None
        try:
            lv_val = float(lv) if lv is not None and lv != '' else None
            if lv_val is not None and (math.isnan(lv_val) or math.isinf(lv_val)):
                lv_val = None
        except (ValueError, TypeError):
            lv_val = None

        vor_u = it.get('ВОР: единица') or it.get('vor_u') or it.get('u') or ''
        lsr_u = it.get('ЛСР: единица') or it.get('lsr_u') or it.get('u') or ''
        # Колонка «Цена» подписывается единицей цены (единица ЛСР):
        u = sanitize_formula(lsr_u or vor_u or '')

        pr = it.get('pr') if it.get('pr') is not None else it.get('unit_price')
        try:
            pr_val = float(pr) if pr is not None and pr != '' else None
            if pr_val is not None and (math.isnan(pr_val) or math.isinf(pr_val)):
                pr_val = None
        except (ValueError, TypeError):
            pr_val = None

        calc_dv, calc_risk, _ = calculate_item_risk(vv_val, vor_u, lv_val, lsr_u, pr_val)
        dv = calc_dv
        if dv is not None and (math.isnan(dv) or math.isinf(dv)):
            dv = None
        if calc_risk is not None:
            risk_val = calc_risk
        else:
            try:
                risk_val = float(it.get('risk') or it.get('financial_risk') or 0.0)
            except (ValueError, TypeError):
                risk_val = 0.0
        if math.isnan(risk_val) or math.isinf(risk_val):
            risk_val = 0.0
        total_risk += risk_val

        status = sanitize_formula(it.get('status') or it.get('Результат алгоритма') or it.get('cls') or '')
        dec = it.get('decision') or it.get('Статус решения сметчика') or 'Не обработано'
        if dec == 'yes':
            dec = 'Принято сметчиком'
        elif dec == 'no':
            dec = 'В правку (отклонено)'
        elif dec == 'auto':
            dec = 'Автоматически'
        dec = sanitize_formula(dec)

        note = sanitize_formula(it.get('note') or it.get('Причина решения и расхождения') or '')

        row_fill = None
        st_str = str(status).lower()
        if status in ['Нет в смете', 'none'] or 'нет в' in st_str:
            row_fill = fill_none
        elif risk_val > 0 or (dv is not None and abs(dv) > 1e-4) or 'коллизия' in st_str or 'расхожд' in st_str or 'дифф' in st_str:
            row_fill = fill_diff

        ws.cell(row=current_row, column=1, value=n).alignment = Alignment(horizontal="center", vertical="center")
        ws.cell(row=current_row, column=2, value=vor_name).alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws.cell(row=current_row, column=3, value=lsr_name).alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws.cell(row=current_row, column=4, value=code).alignment = Alignment(horizontal="center", vertical="center")

        c_vv = ws.cell(row=current_row, column=5, value=vv_val)
        c_vv.number_format = "#,##0.00"
        c_vv.alignment = Alignment(horizontal="right", vertical="center")

        c_lv = ws.cell(row=current_row, column=6, value=lv_val)
        c_lv.number_format = "#,##0.00"
        c_lv.alignment = Alignment(horizontal="right", vertical="center")

        c_dv = ws.cell(row=current_row, column=7, value=dv if dv is not None else "")
        c_dv.number_format = "+#,##0.00;-#,##0.00;0.00"
        c_dv.alignment = Alignment(horizontal="right", vertical="center")
        if dv is not None and abs(dv) > 1e-4:
            c_dv.font = font_diff

        ws.cell(row=current_row, column=8, value=u).alignment = Alignment(horizontal="center", vertical="center")

        c_pr = ws.cell(row=current_row, column=9, value=pr_val if pr_val is not None else "")
        if pr_val is not None:
            c_pr.number_format = "#,##0.00 ₽"
        c_pr.alignment = Alignment(horizontal="right", vertical="center")

        c_rk = ws.cell(row=current_row, column=10, value=risk_val if risk_val > 0 else "")
        if risk_val > 0:
            c_rk.number_format = "#,##0.00 ₽"
            c_rk.font = font_diff
        c_rk.alignment = Alignment(horizontal="right", vertical="center")

        ws.cell(row=current_row, column=11, value=status).alignment = Alignment(horizontal="center", vertical="center")
        ws.cell(row=current_row, column=12, value=dec).alignment = Alignment(horizontal="center", vertical="center")
        ws.cell(row=current_row, column=13, value=note).alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

        for col_idx in range(1, 14):
            c = ws.cell(row=current_row, column=col_idx)
            c.border = border_cell
            if not c.font or c.font.name != "Calibri":
                c.font = font_td
            if row_fill:
                c.fill = row_fill

        current_row += 1

    # Итоговая строка
    ws.row_dimensions[current_row].height = 24
    ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=9)
    tot_label = ws.cell(row=current_row, column=1, value="ИТОГО совокупный финансовый риск расхождений:")
    tot_label.font = font_total
    tot_label.alignment = Alignment(horizontal="right", vertical="center")

    tot_val = ws.cell(row=current_row, column=10, value=total_risk)
    tot_val.font = font_diff
    tot_val.number_format = "#,##0.00 ₽"
    tot_val.alignment = Alignment(horizontal="right", vertical="center")

    for c_i in range(1, 14):
        ws.cell(row=current_row, column=c_i).border = border_total
        ws.cell(row=current_row, column=c_i).fill = fill_total

    # Блок подписей сторон
    sig_row = current_row + 3
    ws.cell(row=sig_row, column=2, value="От Заказчика:").font = font_meta_b
    ws.cell(row=sig_row, column=6, value="От Подрядчика:").font = font_meta_b
    ws.cell(row=sig_row, column=10, value="Сверку выполнил:").font = font_meta_b

    ws.cell(row=sig_row + 1, column=2, value="Должность: ____________________").font = font_meta
    ws.cell(row=sig_row + 1, column=6, value="Должность: ____________________").font = font_meta
    ws.cell(row=sig_row + 1, column=10, value="Должность: Инженер-сметчик").font = font_meta

    ws.cell(row=sig_row + 3, column=2, value="Подпись:   _______ / __________ /").font = font_meta
    ws.cell(row=sig_row + 3, column=6, value="Подпись:   _______ / __________ /").font = font_meta
    ws.cell(row=sig_row + 3, column=10, value=f"Подпись:   _______ / {user_name} /").font = font_meta

    ws.cell(row=sig_row + 4, column=2, value="«___» ____________ 2026 г.").font = font_sub
    ws.cell(row=sig_row + 4, column=6, value="«___» ____________ 2026 г.").font = font_sub
    ws.cell(row=sig_row + 4, column=10, value="«___» ____________ 2026 г.").font = font_sub

    col_widths = {
        1: 6,    # №
        2: 38,   # ВОР
        3: 38,   # ЛСР
        4: 24,   # Шифр
        5: 14,   # Объём ВОР
        6: 14,   # Объём ЛСР
        7: 14,   # Разница
        8: 10,   # Ед.
        9: 20,   # Цена
        10: 20,  # Риск
        11: 22,  # Статус
        12: 20,  # Решение
        13: 35   # Примечание
    }
    for col_idx, width in col_widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


@app.route('/api/export_discrepancy_act', methods=['GET', 'POST'])
@login_required
def api_export_discrepancy_act():
    """Экспорт официального Акта разногласий (Дефектной ведомости) в Excel."""
    user_id = session.get('user_id')
    last_res, _ = get_user_results(user_id)

    items = []
    title = "Сверка сметной документации"
    user_name = "Инженер-сметчик"

    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        req_items = data.get('items')
        title = data.get('title') or title
        user_name = data.get('user_name') or user_name
        if req_items is not None:
            if not isinstance(req_items, list) or len(req_items) > 10000:
                return jsonify({"error": "Некорректный формат списка позиций (максимум 10 000 позиций)"}), 400
            for it in req_items:
                if not isinstance(it, dict):
                    return jsonify({"error": "Элементы списка позиций должны быть объектами"}), 400
            items = req_items

    # 2.8: Если результаты есть у текущего пользователя на сервере, строим акт из них
    if last_res:
        items = last_res

    if not items:
        return jsonify({"error": "Нет данных для формирования Акта разногласий"}), 400

    if user_id:
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.id == user_id).first()
            if u and u.full_name:
                user_name = u.full_name
        finally:
            db.close()

    excel_buf = generate_discrepancy_act_excel(items, title=title, user_name=user_name)
    from urllib.parse import quote
    filename = "Акт_разногласий_СверкаСмет.xlsx"

    return Response(
        excel_buf.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=\"act_discrepancies.xlsx\"; filename*=UTF-8''{quote(filename)}"
        }
    )


# ==========================================
# API АВТОРИЗАЦИИ И ПРОЕКТОВ (PostgreSQL 17)
# ==========================================

@app.route('/api/auth/register', methods=['POST'])
def api_register():
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    full_name = data.get('full_name', '').strip()
    company = data.get('company', '').strip()

    if not email or not password or not full_name:
        return jsonify({'error': 'Заполните обязательные поля: Email, пароль и ФИО'}), 400

    if len(password) < 8:
        return jsonify({'error': 'Пароль должен содержать не менее 8 символов'}), 400

    # 2.3: Роль из тела запроса игнорируется, всегда estimator.
    # Администратор и lead назначаются только вручную администратором БД.
    role = 'estimator'

    db_sess = SessionLocal()
    try:
        if db_sess.query(User).filter_by(email=email).first():
            return jsonify({'error': 'Пользователь с таким email уже зарегистрирован'}), 400

        user = User(
            email=email,
            full_name=full_name,
            role=role,
            company=company
        )
        user.set_password(password)
        db_sess.add(user)
        db_sess.commit()
        db_sess.refresh(user)

        session.clear()
        session['user_id'] = user.id
        return jsonify({'ok': True, 'user': user.to_dict()}), 201
    finally:
        db_sess.close()


@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    # 2.13: Ограничение частоты попыток входа (Rate Limiting)
    client_ip = request.remote_addr or "127.0.0.1"
    rate_key = f"{client_ip}:{email}"
    if not check_login_rate_limit(rate_key, max_attempts=5, window_seconds=300):
        return jsonify({'error': 'Слишком много попыток входа. Попробуйте через 5 минут.', 'code': 'TOO_MANY_REQUESTS'}), 429

    # 2.6: В production демо-вход строго заблокирован
    if is_production() and email == 'demo@sverkasmet.ru':
        return jsonify({'error': 'Вход под демонстрационным аккаунтом заблокирован в production-окружении'}), 403

    db_sess = SessionLocal()
    try:
        user = db_sess.query(User).filter_by(email=email).first()
        if not user or not user.check_password(password):
            return jsonify({'error': 'Неверный email или пароль'}), 401

        session.clear()
        session['user_id'] = user.id
        return jsonify({'ok': True, 'user': user.to_dict()})
    finally:
        db_sess.close()


@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'ok': True})


@app.route('/api/auth/me', methods=['GET'])
def api_me():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'user': None})

    db_sess = SessionLocal()
    try:
        user = db_sess.query(User).filter_by(id=user_id).first()
        return jsonify({'user': user.to_dict() if user else None})
    finally:
        db_sess.close()


@app.route('/api/projects', methods=['GET'])
@login_required
def api_projects_list():
    user_id = session.get('user_id')
    db_sess = SessionLocal()
    try:
        user = db_sess.query(User).filter_by(id=user_id).first()
        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 401
        q = db_sess.query(Project)
        # Архитектурное решение безопасности: роль lead видит все проекты организации
        # для сквозного аудита и контроля сметного отдела; инженеры-сметчики (estimator)
        # имеют строго изолированный доступ только к собственным проектам.
        if user.role != 'lead':
            q = q.filter(Project.user_id == user_id)
        projects = q.order_by(desc(Project.created_at)).all()
        return jsonify({'projects': [p.to_dict() for p in projects]})
    finally:
        db_sess.close()


@app.route('/api/projects/<int:project_id>', methods=['GET'])
@login_required
def api_project_detail(project_id):
    user_id = session.get('user_id')
    db_sess = SessionLocal()
    try:
        user = db_sess.query(User).filter_by(id=user_id).first()
        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 401
        project = db_sess.query(AuditProject).filter_by(id=project_id).first()
        if not project:
            return jsonify({'error': 'Проект не найден'}), 404
        # Контроль доступа к ресурсу: доступ разрешен только владельцу или роли lead
        if user.role != 'lead' and project.user_id != user_id:
            return jsonify({'error': 'Проект не найден'}), 404

        items = [it.to_dict() for it in project.match_results]
        documents = [doc.to_dict() for doc in project.documents]
        llm_logs = [log.to_dict() for log in project.llm_logs]
        res = project.to_dict()
        res['items'] = items
        res['match_results'] = items
        res['documents'] = documents
        res['llm_logs'] = llm_logs
        return jsonify(res)
    finally:
        db_sess.close()


@app.route('/api/projects/save', methods=['POST'])
@login_required
def api_project_save():
    data = request.get_json(silent=True) or {}
    user_id = session.get('user_id')

    title = data.get('title', 'Новая сверка')
    object_name = data.get('object_name', title)
    items_data = data.get('items', [])
    vor_fn = data.get('vor_filename')
    lsr_fn = data.get('lsr_filename')
    total_pos = int(data.get('total_positions', len(items_data)))
    matched_cnt = int(data.get('matched_count', 0))
    match_rate = float(data.get('match_rate', round(matched_cnt / total_pos * 100, 1) if total_pos else 0.0))

    db_sess = SessionLocal()
    try:
        if not user_id:
            if os.getenv("ENV", "development").lower() == "production":
                return jsonify({'error': 'Необходима авторизация для сохранения проекта'}), 401
            demo_user = db_sess.query(User).filter(text("lower(email) = 'demo@sverkasmet.ru'")).first()
            if demo_user:
                user_id = demo_user.id
            else:
                return jsonify({'error': 'Пользователь не найден. Пожалуйста, выполните вход.'}), 401

        project = AuditProject(
            user_id=user_id,
            title=title,
            object_name=object_name,
            status=data.get('status', 'completed'),
            match_rate=match_rate,
            vor_filename=vor_fn,
            lsr_filename=lsr_fn,
            total_positions=total_pos,
            matched_count=matched_cnt,
            discrepancy_count=int(data.get('discrepancy_count', 0)),
            total_financial_risk=float(data.get('total_financial_risk', 0.0))
        )
        db_sess.add(project)
        db_sess.flush()

        # Сохранение исходных документов (DOCUMENTS)
        custom_docs = data.get('documents')
        if custom_docs and isinstance(custom_docs, list):
            for cd in custom_docs:
                db_sess.add(Document(
                    project_id=project.id,
                    doc_type=cd.get('doc_type', 'DOC'),
                    filename=cd.get('filename', 'doc.xlsx'),
                    row_count=int(cd.get('row_count', 0))
                ))
        else:
            if vor_fn:
                db_sess.add(Document(
                    project_id=project.id,
                    doc_type="VOR",
                    filename=vor_fn,
                    row_count=data.get('vor_row_count', len(items_data))
                ))
            if lsr_fn:
                db_sess.add(Document(
                    project_id=project.id,
                    doc_type="LSR",
                    filename=lsr_fn,
                    row_count=data.get('lsr_row_count', len(items_data))
                ))

        # Сохранение результатов сопоставления (MATCH_RESULTS)
        for item in items_data:
            sim_val = float(item.get('sim', 0)) / 100.0 if item.get('sim') is not None else float(item.get('text_sim', 0.0))
            is_ai_item = bool(item.get('ai', False))
            formulation_warn = bool(
                item.get('formulation_warn', False) or
                (sim_val < 0.55 and item.get('s') not in ('none', 'ok') and item.get('detail_class') == 'Проверка наименования')
            )

            audit_item = MatchResult(
                project_id=project.id,
                row_num=item.get('n', 0),
                vor_num=str(item.get('vor_num') or ''),
                lsr_num=str(item.get('lsr_num') or ''),
                vor_name=item.get('vor', ''),
                lsr_name=item.get('lsr', ''),
                code=item.get('code', ''),
                qty_vor=float(item['vv']) if item.get('vv') is not None else None,
                qty_lsr=float(item['lv']) if item.get('lv') is not None else None,
                unit=item.get('u', ''),
                unit_price=float(item['pr']) if item.get('pr') is not None else 0.0,
                financial_risk=float(item.get('risk', 0.0)),
                upper_status=item.get('s', 'none'),
                detail_class=item.get('detail_class', ''),
                text_sim=sim_val,
                formulation_warn=formulation_warn,
                is_ai=is_ai_item,
                explanation=item.get('note', ''),
                user_decision=item.get('decision')
            )
            db_sess.add(audit_item)
            db_sess.flush()

            # Если позиция обрабатывалась ИИ-арбитром, фиксируем в LLM_LOGS
            if is_ai_item:
                p_tok = int(item['prompt_tokens']) if item.get('prompt_tokens') is not None else None
                c_tok = int(item['completion_tokens']) if item.get('completion_tokens') is not None else None
                c_rub = float(item['cost_rub']) if item.get('cost_rub') is not None else None
                db_sess.add(LLMLog(
                    project_id=project.id,
                    match_result_id=audit_item.id,
                    vor_name=item.get('vor', ''),
                    decision=str(item.get('lsr', '') or item.get('detail_class', 'Арбитраж'))[:500],
                    confidence=sim_val,
                    prompt_tokens=p_tok,
                    completion_tokens=c_tok,
                    cost_rub=c_rub
                ))

        # Дополнительные логи ИИ из статистики, если переданы
        custom_llm_logs = data.get('llm_logs')
        if custom_llm_logs and isinstance(custom_llm_logs, list):
            for log_entry in custom_llm_logs:
                p_tok = int(log_entry['prompt_tokens']) if log_entry.get('prompt_tokens') is not None else None
                c_tok = int(log_entry['completion_tokens']) if log_entry.get('completion_tokens') is not None else None
                c_rub = float(log_entry['cost_rub']) if log_entry.get('cost_rub') is not None else None
                db_sess.add(LLMLog(
                    project_id=project.id,
                    vor_name=log_entry.get('vor_name', ''),
                    decision=str(log_entry.get('decision', ''))[:500],
                    confidence=float(log_entry.get('confidence', 0.0)),
                    prompt_tokens=p_tok,
                    completion_tokens=c_tok,
                    cost_rub=c_rub
                ))

        db_sess.commit()
        return jsonify({'ok': True, 'project': project.to_dict()}), 201
    finally:
        db_sess.close()


@app.route('/api/projects/item_decision', methods=['POST'])
@login_required
def api_item_decision():
    user_id = session.get('user_id')
    data = request.get_json(silent=True) or {}
    item_id = data.get('item_id')
    decision = data.get('decision')

    if not item_id:
        return jsonify({'error': 'item_id обязателен'}), 400

    db_sess = SessionLocal()
    try:
        user = db_sess.query(User).filter_by(id=user_id).first()
        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 401

        item = db_sess.query(AuditItem).filter_by(id=item_id).first()
        if not item:
            return jsonify({'error': 'Строка не найдена'}), 404

        # Проверка прав доступа к связанному проекту:
        project = db_sess.query(AuditProject).filter_by(id=item.project_id).first()
        if not project or (user.role != 'lead' and project.user_id != user_id):
            return jsonify({'error': 'Строка не найдена'}), 404

        item.user_decision = decision
        db_sess.commit()
        return jsonify({'ok': True, 'item': item.to_dict()})
    finally:
        db_sess.close()


def open_browser():
    webbrowser.open_new("http://127.0.0.1:5000")


if __name__ == '__main__':
    port = 5000
    print(f"\nЗапуск СверкаСмет Web: http://127.0.0.1:{port}")
    print("Нажмите Ctrl+C для остановки сервера.\n")
    threading.Timer(1.0, open_browser).start()
    app.run(host='127.0.0.1', port=port, debug=False)
