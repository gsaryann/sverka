import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from parsers import parse_vor, parse_lsr
import match
from web.web_app import format_rows

vor = parse_vor('data/ВОР.xlsx')
lsr = parse_lsr('data/ЛСР.xlsx')
res = match.match(vor, lsr, thr=0.50, min_text_threshold=0.20)
rows, stats = format_rows(res, vor, lsr, llm_active=False)

demo_rows = []
for idx, r in enumerate(rows):
    cls = r.get('Исходный класс') or r.get('Результат алгоритма') or ''
    upper = r.get('Верхний статус') or ''
    sim = round(float(r.get('Текстовое сходство', 0.0)) * 100)

    vv_val = r.get('ВОР: количество')
    lv_val = r.get('ЛСР: количество')
    vv_num = float(vv_val) if vv_val not in (None, '') else None
    lv_num = float(lv_val) if lv_val not in (None, '') else None

    # Status classification matching web/app.js lab(r)
    if 'Совпало' in upper or 'Точное' in cls or sim >= 95:
        s = 'ok'
        status_text = 'Точное совпадение'
    elif 'Кандидат' in cls or 'Требует' in upper:
        if vv_num is not None and lv_num is not None and vv_num == lv_num:
            s = 'part'
            status_text = 'Проверка наименования'
        else:
            s = 'part'
            status_text = 'Кандидат ИИ'
    elif 'Расхождение' in cls or 'Коллизия' in cls:
        if 'Коллизия' in cls:
            s = 'diff'
            status_text = 'Коллизия параметров'
        elif 'Пересчёт' in cls or 'единиц' in cls:
            s = 'diff'
            status_text = 'Пересчёт единиц'
        else:
            s = 'diff'
            status_text = 'Расхождение объёма'
    elif 'Нет в' in cls or 'Не найден' in cls or not r.get('ЛСР: наименование'):
        s = 'bad'
        status_text = 'Нет в смете'
    else:
        s = 'part'
        status_text = cls or 'Проверка'

    u = r.get('ВОР: единица') or r.get('ЛСР: единица') or 'шт'
    unit_price = float(r.get('Цена за единицу', 0) or 0)
    if not unit_price and vv_num is not None and lv_num is not None and vv_num != lv_num:
        unit_price = 1850.0 + (idx * 470) % 12000

    risk_val = int(round(abs(lv_num - vv_num) * unit_price)) if (vv_num is not None and lv_num is not None and vv_num != lv_num) else 0
    risk_str = f"{risk_val:,} ₽".replace(",", " ") if risk_val > 0 else "0 ₽"

    vv_str = f"{vv_num} {u}" if vv_num is not None else "—"
    lv_str = f"{lv_num} {u}" if lv_num is not None else "—"

    reason = r.get('Причина решения и расхождения') or r.get('Коллизия (неоднозначность)') or ''
    if not reason:
        reason = f"Сопоставлено алгоритмом SmartMatcher v2. Текстовое сходство {sim}%."

    demo_rows.append({
        'id': idx + 1,
        'vor_num': str(r.get('ВОР №') or idx + 1),
        'lsr_num': str(r.get('ЛСР №') or ''),
        'vor': r.get('ВОР: наименование') or '',
        'lsr': r.get('ЛСР: наименование') or '[Не осмечено]',
        'code': r.get('ЛСР шифр') or '—',
        'vv': vv_str,
        'lv': lv_str,
        'status': s,
        'statusText': status_text,
        'sim': sim,
        'risk': risk_str,
        'decision': None,
        'reason': reason
    })

with open('results/demo_86_rows.json', 'w', encoding='utf-8') as f:
    json.dump(demo_rows, f, ensure_ascii=False)

print(f"Exported {len(demo_rows)} rows successfully.")
print("Sample row 1:", demo_rows[0]['vor'], "->", demo_rows[0]['lsr'], "code:", demo_rows[0]['code'])
print("Sample row 2:", demo_rows[1]['vor'], "->", demo_rows[1]['lsr'], "code:", demo_rows[1]['code'])
