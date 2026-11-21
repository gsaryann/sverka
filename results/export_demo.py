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
for r in rows:
    s = r.get('s', 'none')
    cls = r.get('detail_class', '')
    vv = r.get('vv')
    lv = r.get('lv')
    sim = r.get('sim', 0)
    u = r.get('u', '')

    if s == 'ok':
        st = 'ok'
        st_text = 'Точное совпадение'
    elif s == 'part':
        st = 'part'
        st_text = cls or 'Проверка наименования'
    elif s == 'diff':
        st = 'diff'
        st_text = cls or 'Расхождение объёма'
    else:
        st = 'bad'
        st_text = cls or 'Нет в смете'

    risk_val = int(r.get('risk', 0) or 0)
    risk_str = f"{risk_val:,} ₽".replace(",", " ")

    demo_rows.append({
        'id': r.get('n', 1),
        'vor_num': str(r.get('vor_num') or ''),
        'lsr_num': str(r.get('lsr_num') or ''),
        'vor': r.get('vor', ''),
        'lsr': r.get('lsr') or '[Не осмечено]',
        'code': r.get('code') or '—',
        'vv': f"{vv} {u}" if vv is not None else '—',
        'lv': f"{lv} {u}" if lv is not None else '—',
        'status': st,
        'statusText': st_text,
        'sim': sim,
        'risk': risk_str,
        'decision': r.get('decision'),
        'reason': r.get('note', '') or 'Пара сопоставлена алгоритмом SmartMatcher v2.'
    })

with open('results/demo_86_rows.json', 'w', encoding='utf-8') as f:
    json.dump(demo_rows, f, ensure_ascii=False)

print(f"Exported {len(demo_rows)} rows successfully.")
