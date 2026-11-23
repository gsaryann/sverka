import json
import re
from pathlib import Path

# Paths
root = Path(r"c:\Users\GAGIK\Документы\diplom\sverka")
downloads_dir = Path(r"C:\Users\GAGIK\Downloads")

# 1. Read files
with open(root / "web" / "app_concepts.html", "r", encoding="utf-8") as f:
    concepts_html = f.read()

with open(root / "web" / "index.html", "r", encoding="utf-8") as f:
    index_html = f.read()

with open(root / "web" / "style.css", "r", encoding="utf-8") as f:
    style_css = f.read()

with open(root / "web" / "app.js", "r", encoding="utf-8") as f:
    app_js = f.read()

# 2. Get real 86 rows
import sys
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from parsers import parse_vor, parse_lsr
import match
from web.web_app import format_rows
from results.export_demo import load_real_lsr_prices

vor = parse_vor(str(root / "data" / "ВОР.xlsx"))
lsr = parse_lsr(str(root / "data" / "ЛСР.xlsx"))
lsr_prices = load_real_lsr_prices(str(root / "data" / "ЛСР.xlsx"))
res = match.match(vor, lsr, thr=0.50, min_text_threshold=0.20)
raw_rows, stats = format_rows(res, vor, lsr, llm_active=False)

# Map raw_rows to app.js ROWS format
appjs_rows = []
for idx, r in enumerate(raw_rows):
    cls = r.get('Исходный класс') or r.get('Результат алгоритма') or ''
    upper = r.get('Верхний статус') or ''
    s = 'diff'
    if cls == 'Совпало':
        s = 'ok'
    elif 'пересчет' in cls.lower() or 'частичн' in cls.lower() or 'кандидат' in cls.lower() or 'проверка' in cls.lower() or 'Требует' in upper:
        s = 'part'
    elif 'нет в' in cls.lower() or 'не найден' in cls.lower() or not r.get('ЛСР: наименование'):
        s = 'none'

    vv = float(r['ВОР: количество']) if r.get('ВОР: количество') not in (None, '') else None
    lv = float(r['ЛСР: количество']) if r.get('ЛСР: количество') not in (None, '') else None

    # Real price
    lsr_n = str(r.get('ЛСР №') or '').strip()
    pr = lsr_prices.get(lsr_n) if lsr_n else None

    # Risk calculation
    if s == 'diff' and vv is not None and lv is not None and vv != lv and pr:
        # If contractor inflated volume: (lv - vv) * pr
        risk = round(abs(lv - vv) * pr)
    else:
        risk = 0

    appjs_rows.append({
        'n': idx + 1,
        'vor_num': str(r.get('ВОР №') or idx + 1),
        'lsr_num': str(r.get('ЛСР №') or ''),
        'vor': r.get('ВОР: наименование') or '',
        'lsr': r.get('ЛСР: наименование') or '',
        'code': r.get('ЛСР шифр') or '',
        'vv': vv,
        'lv': lv,
        'u': r.get('ВОР: единица') or r.get('ЛСР: единица') or 'шт',
        'pr': pr,
        'risk': risk,
        's': s,
        'cls': cls,
        'sim': round(float(r.get('Текстовое сходство') or 0) * 100),
        'ai': Boolean if False else False,
        'note': r.get('Причина решения и расхождения') or ''
    })

print(f"Mapped {len(appjs_rows)} positions for production terminal.")
# Check row 78
r78 = appjs_rows[77]
print(f"Row 78 ({r78['vor'][:30]}): status={r78['s']}, price={r78['pr']}, risk={r78['risk']} ₽")


# ==============================================================================
# BUILD FILE 1: СверкаСмет_Вариант_D_Новый.html
# ==============================================================================
style_match = re.search(r'<style>(.*?)</style>', concepts_html, re.DOTALL)
concepts_css = style_match.group(1) if style_match else ""

# Extract screen-d markup
idx_d = concepts_html.find('id="screen-d"')
idx_script = concepts_html.find('<script>', idx_d)
screen_d_open = concepts_html.rfind('<div', 0, idx_d)
screen_d_html = concepts_html[screen_d_open:idx_script].strip()

# Clean up screen-d class & inline styling
screen_d_html = screen_d_html.replace('id="screen-d" class="concept-screen active"', 'id="screen-d" class="concept-screen active" style="display:flex; flex-direction:column; flex:1;"')

# Extract script for Variant D
idx_cdrows = concepts_html.find('const cdRows =')
idx_rowdata = concepts_html.find('const rowDataA =')
script_d = concepts_html[idx_cdrows:idx_rowdata].strip()

standalone_variant_d = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>СверкаСмет — Вариант D: Эргономичный терминал (86 позиций)</title>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Golos+Text:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
  <style>
{concepts_css}

    /* Отдельный автономный экран для Варианта D */
    html, body {{
      height: 100%;
      margin: 0;
      padding: 0;
      background: #F8FAFC;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      font-family: 'Golos Text', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }}
    .concept-screen {{
      display: flex !important;
      flex-direction: column;
      flex: 1;
      height: 100%;
      overflow: hidden;
    }}
    .variant-banner {{
      background: #1E293B;
      color: #fff;
      padding: 8px 18px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 13px;
      flex-shrink: 0;
      box-shadow: 0 1px 3px rgba(0,0,0,0.12);
      border-bottom: 1px solid #334155;
    }}
    .variant-banner b {{
      color: #38BDF8;
      font-weight: 700;
    }}
    .variant-banner .tag {{
      background: rgba(56, 189, 248, 0.15);
      border: 1px solid rgba(56, 189, 248, 0.4);
      color: #7DD3FC;
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 600;
      margin-left: 8px;
    }}
  </style>
</head>
<body>

  <!-- Верхний информационный бандл-баннер -->
  <div class="variant-banner">
    <div style="display:flex; align-items:center;">
      <b>⭐ СверкаСмет · Вариант D (Новый эргономичный концепт)</b>
      <span class="tag">Плотный Topbar 44px · Быстрые решения ✓/✕ · Боковая шторка [Esc] · Независимый скролл</span>
    </div>
    <div style="color:#94A3B8; font-size:12px;">
      Документы: <b>ВОР.xlsx vs ЛСР.xlsx (86 поз.)</b> · Финанс. риск по методике 421/пр (РИМ)
    </div>
  </div>

  {screen_d_html}

  <script>
{script_d}

    function cdInit() {{
      cdRenderTable();
      if (typeof cdRows !== 'undefined' && cdRows.length > 0) {{
        cdSelectRow(0);
      }}
    }}
    if (document.readyState === 'complete' || document.readyState === 'interactive') {{
      cdInit();
    }} else {{
      document.addEventListener('DOMContentLoaded', cdInit);
    }}
  </script>
</body>
</html>
"""

file_d_path = downloads_dir / "СверкаСмет_Вариант_D_Новый.html"
with open(file_d_path, "w", encoding="utf-8") as f:
    f.write(standalone_variant_d)
print(f"Saved: {file_d_path} ({len(standalone_variant_d)} bytes)")


# ==============================================================================
# BUILD FILE 2: СверкаСмет_Текущий_Вариант.html
# ==============================================================================
app_js_clean = app_js

# Replace ROWS = []; with appjs_rows JSON
appjs_rows_json = json.dumps(appjs_rows, ensure_ascii=False)
app_js_clean = re.sub(r'let ROWS = \[.*?\];', f'let ROWS = {appjs_rows_json};', app_js_clean)

# Add startup initialization to app.js
init_appjs = """
// Standalone initial rendering on startup
document.addEventListener('DOMContentLoaded', () => {
  const badge = document.getElementById('user-name');
  if (badge) badge.textContent = 'Инженер-сметчик (Демо)';
  const guard = document.getElementById('w-guard-banner');
  if (guard) guard.style.display = 'none';

  const presetsBar = document.getElementById('presets-bar');
  if (presetsBar) presetsBar.style.display = 'flex';
  const pills = document.querySelectorAll('.preset-pill');
  if (pills.length > 0) pills[0].classList.add('active');

  // Trigger render of the 86 real positions
  if (typeof render === 'function') {
    render();
    if (typeof selectRow === 'function' && ROWS.length > 0) {
      selectRow(ROWS[0].n);
    }
  }
});
"""
app_js_clean += "\n" + init_appjs

# Replace external css/js with inlined versions
standalone_curr = index_html
standalone_curr = standalone_curr.replace(
    '<link rel="stylesheet" href="/style.css">',
    f"""<style>
{style_css}

.variant-banner {{
  background: #1E293B;
  color: #fff;
  padding: 8px 18px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.12);
  border-radius: 8px;
  margin-bottom: 12px;
}}
.variant-banner b {{
  color: #F59E0B;
  font-weight: 700;
}}
.variant-banner .tag {{
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid rgba(245, 158, 11, 0.4);
  color: #FCD34D;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  margin-left: 8px;
}}
</style>"""
)

standalone_curr = standalone_curr.replace(
    '<script src="/app.js"></script>',
    f"<script>\n{app_js_clean}\n</script>"
)

# Add banner in app header
banner_header = """
  <!-- Баннер демонстрационного файла -->
  <div class="variant-banner">
    <div style="display:flex; align-items:center;">
      <b>📋 СверкаСмет · Текущий интерфейс (Оригинал)</b>
      <span class="tag">Классическая компоновка · Панель выбора файлов · Master-Detail карточка</span>
    </div>
    <div style="color:#94A3B8; font-size:12px;">
      Документы: <b>ВОР.xlsx vs ЛСР.xlsx (86 поз.)</b> · Предзагружен для прямого сравнения
    </div>
  </div>
"""
standalone_curr = standalone_curr.replace('<div class="app">', '<div class="app">\n' + banner_header)

file_curr_path = downloads_dir / "СверкаСмет_Текущий_Вариант.html"
with open(file_curr_path, "w", encoding="utf-8") as f:
    f.write(standalone_curr)
print(f"Saved: {file_curr_path} ({len(standalone_curr)} bytes)")
