"""
Экспорт реального набора из 86 позиций (ВОР vs ЛСР Дворец молодёжи)
с реальными сметными ценами из ЛСР.xlsx для демонстрационного режима.
"""

import json
import sys
from pathlib import Path
import openpyxl

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from parsers import parse_vor, parse_lsr
import match
from web.web_app import format_rows


def load_real_lsr_prices(lsr_excel_path: str):
    """
    Извлекает реальные сметные цены (колонка 16 «Всего в текущем уровне цен» / «Всего по позиции»)
    из официального сметного расчёта ЛСР по Методике 421/пр (РИМ).
    """
    wb = openpyxl.load_workbook(lsr_excel_path, data_only=True)
    ws = wb.active
    prices = {}
    current_num = None

    for r in range(45, ws.max_row + 1):
        num_val = ws.cell(r, 1).value
        code_val = ws.cell(r, 2).value
        name_val = str(ws.cell(r, 3).value or '').strip()
        tot_val = ws.cell(r, 16).value

        if num_val and str(num_val).strip().isdigit() and code_val:
            current_num = str(num_val).strip()

        if 'всего по позиции' in name_val.lower() and tot_val is not None:
            if current_num:
                prices[current_num] = float(tot_val)
                current_num = None

    return prices


vor = parse_vor('data/ВОР.xlsx')
lsr = parse_lsr('data/ЛСР.xlsx')
lsr_prices = load_real_lsr_prices('data/ЛСР.xlsx')

res = match.match(vor, lsr, thr=0.50, min_text_threshold=0.20)
rows, stats = format_rows(res, vor, lsr, llm_active=False)

demo_rows = []
for idx, r in enumerate(rows):
    item = res[idx]
    cand = item.get('candidate')
    v_item = item.get('vor_item')
    l_item = cand.lsr_item if cand else None

    cls = item.get('cls') or ''
    upper = item.get('upper_status') or r.get('Верхний статус') or ''
    sim = round(float(item.get('text_sim', 0.0)) * 100)

    qty_matched = bool(cand.qty_matched) if cand else False

    # Классификация статуса
    if 'Совпало' in cls or (qty_matched and sim >= 50):
        s = 'ok'
        if 'пересчет' in cls.lower() or (v_item and l_item and v_item.unit != l_item.unit):
            status_text = 'Пересчёт единиц (OK)'
        else:
            status_text = 'Точное совпадение'
    elif 'Кандидат' in cls or 'Требует' in upper:
        s = 'part'
        if qty_matched:
            status_text = 'Проверка наименования'
        else:
            status_text = 'Кандидат — требуется проверка'
    elif 'Расхождение' in cls or (cand and not qty_matched):
        s = 'diff'
        status_text = 'Расхождение объёма'
    elif 'Нет в' in cls or not l_item:
        s = 'bad'
        status_text = 'Нет в смете'
    else:
        s = 'part'
        status_text = cls or 'Проверка'

    # Форматирование объемов с единицами измерения
    vv_str = f"{v_item.qty} {v_item.unit}" if v_item and v_item.qty is not None else "—"
    lv_str = f"{l_item.qty} {l_item.unit}" if l_item and l_item.qty is not None else "—"

    # Расчет финансового риска строго по реальным ценам ЛСР
    unit_price = 0.0
    if l_item and str(l_item.num) in lsr_prices and l_item.qty and float(l_item.qty) > 0:
        total_p = lsr_prices[str(l_item.num)]
        unit_price = round(total_p / float(l_item.qty), 2)

    if not qty_matched and v_item and l_item and v_item.qty is not None and l_item.qty is not None:
        diff_q = abs(float(v_item.qty) - float(l_item.qty))
        if unit_price > 0:
            risk_val = int(round(diff_q * unit_price))
            risk_str = f"{risk_val:,} ₽".replace(",", " ")
        else:
            risk_str = "Требуется расценка"
    elif not l_item:
        # В ВОР цены отсутствуют — поэтому финансовая оценка неосмеченных работ возможна
        # только после конъюнктурного анализа или коммерческого предложения.
        risk_str = "Не оценено (нет в ЛСР)"
    else:
        risk_str = "0 ₽"

    reason = item.get('explanation') or r.get('Причина решения и расхождения') or ''
    if not reason:
        reason = f"Сопоставлено алгоритмом SmartMatcher v2. Текстовое сходство {sim}%."

    demo_rows.append({
        'id': idx + 1,
        'vor_num': str(v_item.num if v_item else idx + 1),
        'lsr_num': str(l_item.num if l_item else ''),
        'vor': v_item.name if v_item else (r.get('ВОР: наименование') or ''),
        'lsr': l_item.name if l_item else '[Не осмечено]',
        'code': (l_item.code if l_item and l_item.code else (r.get('ЛСР шифр') or '—')),
        'unit_price': unit_price if unit_price > 0 else None,
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
    json.dump(demo_rows, f, ensure_ascii=False, indent=2)

print(f"Exported {len(demo_rows)} rows cleanly with real prices from ЛСР.xlsx.")
pos78 = [x for x in demo_rows if x['id'] == 78][0]
print(f"Row 78 ({pos78['vor'][:30]}):")
print(f"  Status: {pos78['statusText']}, Qty: {pos78['vv']} vs {pos78['lv']}")
print(f"  Real LSR Unit Price: {pos78['unit_price']} ₽/шт")
print(f"  Financial Risk: {pos78['risk']}")

unmatched = [x for x in demo_rows if x['status'] == 'bad']
print(f"\nUnmatched positions count: {len(unmatched)}")
for u in unmatched[:3]:
    print(f"  Pos #{u['id']}: {u['vor'][:35]} -> Risk: {u['risk']}")
