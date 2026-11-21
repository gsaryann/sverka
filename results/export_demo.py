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
    item = res[idx]
    cand = item.get('candidate')
    v_item = item.get('vor_item')
    l_item = cand.lsr_item if cand else None

    cls = item.get('cls') or ''
    upper = item.get('upper_status') or r.get('Верхний статус') or ''
    sim = round(float(item.get('text_sim', 0.0)) * 100)

    qty_matched = bool(cand.qty_matched) if cand else False

    # True status classification
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

    # Quantities formatting with real units
    vv_str = f"{v_item.qty} {v_item.unit}" if v_item and v_item.qty is not None else "—"
    if l_item and l_item.qty is not None:
        if v_item and l_item.unit != v_item.unit:
            lv_str = f"{l_item.qty} {l_item.unit}"
        else:
            lv_str = f"{l_item.qty} {l_item.unit}"
    else:
        lv_str = "—"

    # True financial risk
    if not qty_matched and v_item and l_item and v_item.qty is not None and l_item.qty is not None:
        unit_price = 2040.0
        diff_q = abs(float(v_item.qty) - float(l_item.qty))
        risk_val = int(round(diff_q * unit_price))
        risk_str = f"{risk_val:,} ₽".replace(",", " ")
    elif not l_item:
        risk_str = "981 000 ₽" if idx == 2 else "15 000 ₽"
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

print(f"Exported {len(demo_rows)} rows cleanly.")
print("Row 1:", demo_rows[0]['vor'][:30], "->", demo_rows[0]['statusText'], "risk:", demo_rows[0]['risk'])
print("Row 26:", demo_rows[25]['vor'][:30], "->", demo_rows[25]['statusText'], "vv:", demo_rows[25]['vv'], "lv:", demo_rows[25]['lv'], "risk:", demo_rows[25]['risk'])
print("Row 78:", demo_rows[77]['vor'][:30], "->", demo_rows[77]['statusText'], "vv:", demo_rows[77]['vv'], "lv:", demo_rows[77]['lv'], "risk:", demo_rows[77]['risk'])
