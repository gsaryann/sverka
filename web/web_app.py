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
import copy
import random
import tempfile
import threading
import queue
import webbrowser
from pathlib import Path
from typing import List, Dict, Any

from flask import Flask, request, jsonify, Response, stream_with_context

# Автоматическое подключение корневой папки проекта в sys.path
WEB_DIR = Path(__file__).resolve().parent
ROOT_DIR = WEB_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from parsers import parse_vor, parse_lsr, Item
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
    'Статус решения сметчика'
]


@app.route('/')
def index():
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
        stats[status] = stats.get(status, 0) + 1

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

        vor = parse_vor(str(vor_path))
        lsr = parse_lsr(str(lsr_path))

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

        return jsonify({'stats': stats, 'rows': rows})

    except Exception as e:
        return jsonify({'error': f'{type(e).__name__}: {str(e)}'}), 500
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

        vor = parse_vor(str(vor_path))
        lsr = parse_lsr(str(lsr_path))

    except Exception as e:
        for p in tmp_files_to_clean:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        return jsonify({'error': f'{type(e).__name__}: {str(e)}'}), 500

    def generate():
        global LAST_RESULTS, ORIG_RESULTS
        try:
            # 1. Мгновенный расчет SmartMatcher (0.05 сек)
            if mode == 'legacy':
                results = baseline_legacy.match(vor, lsr)
            elif mode == 'model_only':
                from llm_resolver import model_only_results
                results = model_only_results(vor, lsr)
            else:
                results = match.match(vor, lsr, thr=thr, min_text_threshold=0.20)

            llm_needed = mode in ('hybrid', 'arbitration', 'hybrid_weak', 'model_only')
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
            yield f"data: {json.dumps({'type': 'init', 'stats': init_stats, 'rows': init_rows, 'ambig_count': ambig_count, 'mode': mode, 'needs_llm': bool(llm_needed and ambig_count > 0)}, ensure_ascii=False)}\n\n"

            # 2. Потоковый арбитраж спорных позиций Алисой
            if llm_needed and ambig_count > 0:
                from llm_resolver import YandexClient, resolve
                client = YandexClient()
                cache_path = str(RESULTS_DIR / "llm_cache.json")
                m_mode = 'model_only' if mode == 'model_only' else ('weak_only' if mode == 'hybrid_weak' else 'arbitration')

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
                            'llm_stats': llm_stats
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
                yield f"data: {json.dumps({'type': 'done', 'rows': init_rows, 'stats': init_stats}, ensure_ascii=False)}\n\n"

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
        except Exception:
            pass

        conf_list = []
        for (t_cls, p_cls), cnt in sorted(ev_smart['conf'].items(), key=lambda x: -x[1])[:8]:
            conf_list.append({
                'true_cls': t_cls,
                'pred_cls': p_cls,
                'count': cnt
            })

        return jsonify({
            'methods': methods_data,
            'confusion': conf_list
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


def open_browser():
    webbrowser.open_new("http://127.0.0.1:5000")


if __name__ == '__main__':
    port = 5000
    print(f"\nЗапуск СверкаСмет Web: http://127.0.0.1:{port}")
    print("Нажмите Ctrl+C для остановки сервера.\n")
    threading.Timer(1.0, open_browser).start()
    app.run(host='127.0.0.1', port=port, debug=False)
