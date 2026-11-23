import json
import re
from pathlib import Path
import shutil

ROOT_DIR = Path(__file__).resolve().parent.parent

with open(ROOT_DIR / 'results/demo_86_rows.json', encoding='utf-8') as f:
    demo_json = json.dumps(json.load(f), ensure_ascii=False)

html_path = ROOT_DIR / 'web/app_concepts.html'
with open(html_path, encoding='utf-8') as f:
    html = f.read()

# 1. Update cdRows with real prices
html = re.sub(r'const cdRows = \[.*?\];', f'const cdRows = {demo_json};', html, flags=re.DOTALL)

# 2. Update Risk badge in Concept D
html = html.replace(
    'Риск: 1 291 000 ₽',
    'Финанс. риск: 1 003 ₽'
)

# 3. Add explicit prototype markers to button tabs
html = html.replace(
    'Вариант А: «Нижний инспектор»',
    'Вариант А: «Нижний инспектор» [Макет UX]'
)
html = html.replace(
    'Вариант B: «Двухоконный сплит ВОР ↔ ЛСР»',
    'Вариант B: «Двухоконный сплит ВОР ↔ ЛСР» [Макет UX]'
)
html = html.replace(
    'Вариант C: «Плотный Master-Detail»',
    'Вариант C: «Плотный Master-Detail» [Макет UX]'
)
html = html.replace(
    '⭐ Вариант D: «Эргономичный Микс» (Ваш оригинал + Тулбар 44px + Инлайн ✓/✕ + Сворачиваемая шторка)',
    '⭐ Вариант D: «Эргономичный Микс» (Реальные 86 строк ВОР / ЛСР + Расчёт риска по ЛСР 421/пр)'
)

# 4. Add disclaimer banners to mock screens A, B, C
banner_a = '''    <div style="background:#EFF6FF; border:1px solid #BFDBFE; padding:8px 14px; margin:10px 16px; border-radius:6px; font-size:12px; color:#1E40AF; display:flex; align-items:center; gap:8px;">
      <span>ℹ️</span>
      <div><b>Концептуальный макет интерфейса (UX Prototype):</b> Демонстрирует компоновку с нижней шторкой (Bottom Drawer в стиле Excel). Строки в таблице являются синтетическим макетом для диплома. Для просмотра работы алгоритма на реальном наборе из 86 строк ВОР / ЛСР переключитесь на <b>«⭐ Вариант D»</b>.</div>
    </div>'''

banner_b = '''    <div style="background:#EFF6FF; border:1px solid #BFDBFE; padding:8px 14px; margin:10px 16px; border-radius:6px; font-size:12px; color:#1E40AF; display:flex; align-items:center; gap:8px;">
      <span>ℹ️</span>
      <div><b>Концептуальный макет интерфейса (UX Prototype):</b> Демонстрирует компоновку со сплит-экраном (Side-by-Side). Данные в таблицах демонстрационные. Реальный набор из 86 позиций работает в <b>«⭐ Варианте D»</b>.</div>
    </div>'''

banner_c = '''    <div style="background:#EFF6FF; border:1px solid #BFDBFE; padding:8px 14px; margin:10px 16px; border-radius:6px; font-size:12px; color:#1E40AF; display:flex; align-items:center; gap:8px;">
      <span>ℹ️</span>
      <div><b>Концептуальный макет интерфейса (UX Prototype):</b> Демонстрирует компактную панель Master-Detail со статическими примерами. Полный набор из 86 позиций с независимым скроллом и сортировкой работает в <b>«⭐ Варианте D»</b>.</div>
    </div>'''

if 'id="screen-a" class="concept-screen">' in html and banner_a not in html:
    html = html.replace('id="screen-a" class="concept-screen">', 'id="screen-a" class="concept-screen">\n' + banner_a)
if 'id="screen-b" class="concept-screen">' in html and banner_b not in html:
    html = html.replace('id="screen-b" class="concept-screen">', 'id="screen-b" class="concept-screen">\n' + banner_b)
if 'id="screen-c" class="concept-screen">' in html and banner_c not in html:
    html = html.replace('id="screen-c" class="concept-screen">', 'id="screen-c" class="concept-screen">\n' + banner_c)

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)

# Also copy to Downloads for standalone opening by user
downloads_dest = Path('C:/Users/GAGIK/Downloads/Концепты_Терминала_СверкаСмет.html')
if downloads_dest.parent.exists():
    shutil.copy2(html_path, downloads_dest)
    print(f"Copied to {downloads_dest}")

print("Successfully updated web/app_concepts.html with real prices and mock banners.")
