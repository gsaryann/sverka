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
from typing import List, Dict, Any

# Автоматическое подключение корневой папки проекта в sys.path ДО любых локальных импортов
WEB_DIR = Path(__file__).resolve().parent
ROOT_DIR = WEB_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from flask import Flask, request, jsonify, Response, stream_with_context, session, redirect
from sqlalchemy import desc
from db import SessionLocal, User, Project, AuditItem, init_db

logger = logging.getLogger(__name__)

from parsers import parse_vor, parse_lsr, get_parse_warnings, Item


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

    return {
        'error': f"{type(e).__name__}: {err_str}",
        'error_title': "Ошибка при обработке сметного документа",
        'error_message': err_str,
        'error_hint': "Проверьте корректность загруженных файлов или воспользуйтесь готовыми типовыми комплектами."
    }, 500
import match
import baseline_legacy
import perturb
import evaluate

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

app = Flask(
    __name__,
    static_folder=str(WEB_DIR),
    static_url_path=""
)
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024
app.secret_key = os.getenv("SECRET_KEY", "sverkasmet-secure-key-2026-b2b")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


@app.teardown_appcontext
def remove_db_session(exception=None):
    try:
        SessionLocal.remove()
    except Exception:
        pass

DATA_DIR = ROOT_DIR / "data"
RESULTS_DIR = ROOT_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

LAST_RESULTS: List[Dict[str, Any]] = []
ORIG_RESULTS: List[Dict[str, Any]] = []

FIELDS = [
    'ВОР №', 'ВОР строка', 'ВОР раздел', 'ВОР: наименование', 'ВОР: единица', 'ВОР: количество',
    'ЛСР №', 'ЛСР строка', 'ЛСР раздел', 'ЛСР шифр', 'ЛСР: наименование', 'ЛСР: единица', 'ЛСР: количество',
    'Текстовое сходство', 'Уверенность', 'Результат алгоритма', 'Причина решения и расхождения',
    'Коллизия (неоднозначность)', 'Решение ИИ-арбитра',
    'Статус решения сметчика', 'Исходный класс', 'Верхний статус', 'Предупреждение о формулировке',
    'Причина предупреждения', 'Условие предупреждения'
]


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
    return Response(html_path.read_text(encoding="utf-8"), mimetype="text/html")


@app.route('/style.css')
def style():
    css_path = WEB_DIR / "style.css"
    return Response(css_path.read_text(encoding="utf-8"), mimetype="text/css")


@app.route('/app.js')
def script():
    js_path = WEB_DIR / "app.js"
    return Response(js_path.read_text(encoding="utf-8"), mimetype="application/javascript")


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
            'Решение ИИ-арбитра': str(r.get('ai_decision') or ('Не привлекался' if not llm_active else 'Авто')),
            'is_ambiguous': bool(r.get('is_ambiguous', False)),
            'ambiguity_type': str(r.get('ambiguity_type') or ''),
            'competing_candidates': r.get('competing_candidates', []),
            'Статус решения сметчика': 'Авто'
        })
    return rows, stats


@app.route('/api/compare', methods=['POST'])
def api_compare():
    global LAST_RESULTS, ORIG_RESULTS
    mode = request.form.get('mode', 'algo')
    preset = request.form.get('preset')
    thr = float(request.form.get('threshold', 0.50))

    tmp_files_to_clean = []

    try:
        if preset == 'set1':
            vor_path = DATA_DIR / "ВОР.xlsx"
            lsr_path = DATA_DIR / "ЛСР.xlsx"
        elif preset == 'set2':
            vor_path = DATA_DIR / "ВЕДОМОСТЬ ОБЪЕМОВ РАБОТ.xlsx"
            lsr_path = DATA_DIR / "ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЕТ.xlsx"
        else:
            if 'vor' not in request.files or 'lsr' not in request.files:
                return jsonify({'error': 'Не переданы файлы ВОР и ЛСР'}), 400

            file_v = request.files['vor']
            file_l = request.files['lsr']

            tmp_v = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
            tmp_l = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
            file_v.save(tmp_v.name)
            file_l.save(tmp_l.name)
            tmp_v.close()
            tmp_l.close()

            vor_path = Path(tmp_v.name)
            lsr_path = Path(tmp_l.name)
            tmp_files_to_clean = [vor_path, lsr_path]

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
def api_compare_stream():
    global LAST_RESULTS, ORIG_RESULTS
    mode = request.form.get('mode', 'algo')
    preset = request.form.get('preset')
    thr = float(request.form.get('threshold', 0.50))

    tmp_files_to_clean = []

    try:
        if preset == 'set1':
            vor_path = DATA_DIR / "ВОР.xlsx"
            lsr_path = DATA_DIR / "ЛСР.xlsx"
        elif preset == 'set2':
            vor_path = DATA_DIR / "ВЕДОМОСТЬ ОБЪЕМОВ РАБОТ.xlsx"
            lsr_path = DATA_DIR / "ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЕТ.xlsx"
        else:
            if 'vor' not in request.files or 'lsr' not in request.files:
                return jsonify({'error': 'Не переданы файлы ВОР и ЛСР'}), 400

            file_v = request.files['vor']
            file_l = request.files['lsr']

            tmp_v = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
            tmp_l = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
            file_v.save(tmp_v.name)
            file_l.save(tmp_l.name)
            tmp_v.close()
            tmp_l.close()

            vor_path = Path(tmp_v.name)
            lsr_path = Path(tmp_l.name)
            tmp_files_to_clean = [vor_path, lsr_path]

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
                        yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                    except queue.Empty:
                        if not t.is_alive():
                            while not q.empty():
                                item = q.get_nowait()
                                if item is not None:
                                    if item.get('type') == 'done':
                                        LAST_RESULTS = item['rows']
                                        ORIG_RESULTS = copy.deepcopy(item['rows'])
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
def api_action_row():
    """Обработка решения сметчика по спорной строке (по BPMN)."""
    global LAST_RESULTS, ORIG_RESULTS
    data = request.get_json() or {}
    idx = data.get('index')
    act = data.get('action')  # 'confirm', 'reject', 'reset'

    if idx is None or not (0 <= idx < len(LAST_RESULTS)):
        return jsonify({'error': 'Неверный индекс строки'}), 400

    row = LAST_RESULTS[idx]
    orig = ORIG_RESULTS[idx]

    if act == 'confirm':
        row['Статус решения сметчика'] = 'Подтверждено'
        # По BPMN: подтверждённая сметчиком пара уходит на итоговую классификацию
    elif act == 'reject':
        # По BPMN Слайд 12: Сметчик отклонил -> Статус «Нет в рассматриваемой смете»
        row['Статус решения сметчика'] = 'Отклонено'
        row['Результат алгоритма'] = 'Нет в рассматриваемой смете'
        row['Верхний статус'] = match.upper_status('Нет в рассматриваемой смете')
        row['Предупреждение о формулировке'] = False
        row['Причина предупреждения'] = ''
        row['Условие предупреждения'] = ''
        row['ЛСР №'] = ''
        row['ЛСР шифр'] = ''
        row['ЛСР: наименование'] = ''
        row['ЛСР: единица'] = ''
        row['ЛСР: количество'] = ''
        row['Текстовое сходство'] = 0.0
        row['Причина решения и расхождения'] = (
            f"Отклонено сметчиком (исходный кандидат ЛСР №{orig['ЛСР №']}); "
            f"присвоен статус «Нет в рассматриваемой смете»"
        )
    elif act == 'reset':
        LAST_RESULTS[idx] = copy.deepcopy(orig)

    return jsonify({'ok': True, 'row': LAST_RESULTS[idx]})


@app.route('/api/benchmark', methods=['POST'])
def api_benchmark():
    try:
        benchmark_warnings = []
        data = request.get_json() or {}
        preset = data.get('preset', 'set1')
        shuffle = bool(data.get('shuffle', False))
        stress = bool(data.get('stress', True))

        if preset == 'set1':
            vor_path = DATA_DIR / "ВОР.xlsx"
            lsr_path = DATA_DIR / "ЛСР.xlsx"
        else:
            vor_path = DATA_DIR / "ВЕДОМОСТЬ ОБЪЕМОВ РАБОТ.xlsx"
            lsr_path = DATA_DIR / "ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЕТ.xlsx"

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
def api_download_csv():
    global LAST_RESULTS
    if not LAST_RESULTS:
        return "Нет сформированных результатов", 400

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=FIELDS, delimiter=';')
    writer.writeheader()
    writer.writerows(LAST_RESULTS)

    csv_bytes = output.getvalue().encode('utf-8-sig')
    return Response(
        csv_bytes,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=sverka_results.csv"}
    )


# ==========================================
# API АВТОРИЗАЦИИ И ПРОЕКТОВ (PostgreSQL 17)
# ==========================================

@app.route('/api/auth/register', methods=['POST'])
def api_register():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    full_name = data.get('full_name', '').strip()
    role = data.get('role', 'estimator')
    company = data.get('company', '').strip()

    if not email or not password or not full_name:
        return jsonify({'error': 'Заполните обязательные поля: Email, пароль и ФИО'}), 400

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

        session['user_id'] = user.id
        return jsonify({'ok': True, 'user': user.to_dict()}), 201
    finally:
        db_sess.close()


@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    db_sess = SessionLocal()
    try:
        user = db_sess.query(User).filter_by(email=email).first()
        if not user or not user.check_password(password):
            return jsonify({'error': 'Неверный email или пароль'}), 401

        session['user_id'] = user.id
        return jsonify({'ok': True, 'user': user.to_dict()})
    finally:
        db_sess.close()


@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    session.pop('user_id', None)
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
def api_projects_list():
    user_id = session.get('user_id')
    db_sess = SessionLocal()
    try:
        q = db_sess.query(Project)
        if user_id:
            user = db_sess.query(User).filter_by(id=user_id).first()
            if user and user.role != 'lead':
                q = q.filter((Project.user_id == user_id) | (Project.user_id == None))
        projects = q.order_by(desc(Project.created_at)).all()
        return jsonify({'projects': [p.to_dict() for p in projects]})
    finally:
        db_sess.close()


@app.route('/api/projects/<int:project_id>', methods=['GET'])
def api_project_detail(project_id):
    db_sess = SessionLocal()
    try:
        project = db_sess.query(Project).filter_by(id=project_id).first()
        if not project:
            return jsonify({'error': 'Проект не найден'}), 404
        items = [it.to_dict() for it in project.items]
        res = project.to_dict()
        res['items'] = items
        return jsonify(res)
    finally:
        db_sess.close()


@app.route('/api/projects/save', methods=['POST'])
def api_project_save():
    data = request.get_json() or {}
    user_id = session.get('user_id')

    title = data.get('title', 'Новая сверка')
    object_name = data.get('object_name', title)
    items_data = data.get('items', [])

    db_sess = SessionLocal()
    try:
        project = Project(
            user_id=user_id,
            title=title,
            object_name=object_name,
            vor_filename=data.get('vor_filename'),
            lsr_filename=data.get('lsr_filename'),
            total_positions=data.get('total_positions', len(items_data)),
            matched_count=data.get('matched_count', 0),
            discrepancy_count=data.get('discrepancy_count', 0),
            total_financial_risk=float(data.get('total_financial_risk', 0.0))
        )
        db_sess.add(project)
        db_sess.flush()

        for item in items_data:
            audit_item = AuditItem(
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
                status=item.get('s', 'none'),
                detail_class=item.get('detail_class', ''),
                similarity=float(item.get('sim', 0)) / 100.0 if item.get('sim') is not None else 0.0,
                is_ai=bool(item.get('ai', False)),
                explanation=item.get('note', ''),
                user_decision=item.get('decision')
            )
            db_sess.add(audit_item)

        db_sess.commit()
        return jsonify({'ok': True, 'project': project.to_dict()}), 201
    finally:
        db_sess.close()


@app.route('/api/projects/item_decision', methods=['POST'])
def api_item_decision():
    data = request.get_json() or {}
    item_id = data.get('item_id')
    decision = data.get('decision')

    if not item_id:
        return jsonify({'error': 'item_id обязателен'}), 400

    db_sess = SessionLocal()
    try:
        item = db_sess.query(AuditItem).filter_by(id=item_id).first()
        if not item:
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
