import re
from pathlib import Path

landing_path = Path("c:/Users/GAGIK/Документы/diplom/sverka/web/landing.html")
with open(landing_path, "r", encoding="utf-8") as f:
    html = f.read()

# Replace the old terminal section with the modern real-panel replica
old_terminal_regex = re.compile(
    r'<!-- Live Interactive Terminal Showcase -->\s*<div class="terminal-window" id="terminal">.*?<!-- Dynamic Inspection Panel -->\s*<div class="t-panel" id="demo-panel">.*?</div>\s*</div>\s*</div>',
    re.DOTALL
)

new_terminal_html = '''<!-- Live Interactive Terminal Showcase (Полная внешняя реплика реального терминала Варианта D) -->
      <div class="terminal-window" id="terminal" style="border:1px solid #CBD5E1; border-radius:12px; overflow:hidden; box-shadow:0 10px 25px -5px rgba(15, 23, 42, 0.1), 0 8px 10px -6px rgba(15, 23, 42, 0.05); background:#FFFFFF; margin-top:20px;">
        
        <!-- Верхняя карточка управления (2 аккуратные строки, как в рабочей панели) -->
        <div style="background:#F8FAFC; border-bottom:1px solid #E2E8F0; padding:12px 18px;">
          <!-- Строка 1: Проект, файлы, БД и кнопка перехода -->
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:10px;">
            <div style="display:flex; align-items:center; gap:8px; font-size:13.5px; font-weight:700; color:#1F3A5F;">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none"><rect x="2" y="3" width="13" height="17" rx="2" stroke="#1F3A5F" stroke-width="2"/><path d="M9 7h11a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z" fill="#2563EB" opacity="0.2" stroke="#2563EB" stroke-width="2"/><circle cx="16" cy="15" r="3" fill="#10B981"/></svg>
              <span>СверкаСмет Терминал</span>
              <span style="color:#CBD5E1; font-weight:300;">|</span>
              <span style="background:#FFFFFF; border:1px solid #CBD5E1; border-radius:4px; padding:3px 9px; font-size:12px; font-weight:500; color:#334155;">📁 ВОР: ВОР_Дворец.xlsx <b style="color:#1F3A5F;">(86 поз.)</b></span>
              <span style="background:#FFFFFF; border:1px solid #CBD5E1; border-radius:4px; padding:3px 9px; font-size:12px; font-weight:500; color:#334155;">📁 ЛСР: ЛСР_Дворец_421пр.xlsx <b style="color:#1F3A5F;">(94 поз.)</b></span>
            </div>
            <div style="display:flex; align-items:center; gap:10px;">
              <span style="font-family:'IBM Plex Mono', monospace; font-size:11.5px; color:#166534; background:#DCFCE7; border:1px solid #BBF7D0; border-radius:4px; padding:3px 8px; font-weight:600;">● PostgreSQL 17 Active</span>
              <a href="/login" class="btn btn-primary" style="font-size:12px; padding:5px 14px; text-decoration:none;">Открыть терминал →</a>
            </div>
          </div>

          <!-- Строка 2: Фильтры по статусам и расчёт финансового риска -->
          <div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px; padding-top:8px; border-top:1px solid #E2E8F0;">
            <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
              <span style="font-size:12px; color:#64748B; font-weight:600;">Статус:</span>
              <span style="background:#1F3A5F; color:#FFFFFF; font-size:11.5px; font-weight:700; padding:3px 9px; border-radius:4px;">Все: 86</span>
              <span style="background:#DCFCE7; color:#166534; font-size:11.5px; font-weight:700; padding:3px 9px; border-radius:4px; border:1px solid #BBF7D0;">✓ 68 Совпало</span>
              <span style="background:#FEF9C3; color:#854D0E; font-size:11.5px; font-weight:700; padding:3px 9px; border-radius:4px; border:1px solid #FEF08A;">⚠️ 17 Проверка</span>
              <span style="background:#FFEDD5; color:#C2410C; font-size:11.5px; font-weight:700; padding:3px 9px; border-radius:4px; border:1px solid #FED7AA;">⚡ 1 Коллизия</span>
              <span style="background:#F1F5F9; color:#64748B; font-size:11.5px; font-weight:600; padding:3px 8px; border-radius:4px;">✕ 0 Нет</span>
            </div>
            <div>
              <span style="background:#FFF7ED; color:#C2561B; border:1px solid #FED7AA; font-weight:700; font-size:12px; padding:4px 12px; border-radius:4px;" title="Рассчитано строго по сметной расценке ЛСР для позиции №78 (1 003.28 ₽/шт)">Финанс. риск: 1 003 ₽</span>
            </div>
          </div>
        </div>

        <!-- Рабочее пространство: Таблица слева + Выдвижной инспектор справа -->
        <div class="terminal-body" style="display:grid; grid-template-columns:minmax(0, 1.45fr) minmax(340px, 0.9fr); min-height:420px; background:#FFFFFF;">
          <!-- Таблица позиций -->
          <div class="t-table-wrap" style="overflow-x:auto; border-right:1px solid #E2E8F0;">
            <table class="t-table" style="width:100%; border-collapse:collapse; font-size:12.5px; text-align:left;">
              <thead>
                <tr style="background:#F8FAFC;">
                  <th style="width:38px; text-align:center; padding:9px 6px; border-bottom:1px solid #E2E8F0; color:#475569; font-weight:700;">№</th>
                  <th style="width:32%; padding:9px 10px; border-bottom:1px solid #E2E8F0; color:#475569; font-weight:700;">Позиция ВОР (Проект)</th>
                  <th style="width:32%; padding:9px 10px; border-bottom:1px solid #E2E8F0; color:#475569; font-weight:700;">Позиция ЛСР (Смета 421/пр)</th>
                  <th style="padding:9px 8px; border-bottom:1px solid #E2E8F0; color:#475569; font-weight:700;">Объёмы</th>
                  <th style="padding:9px 8px; border-bottom:1px solid #E2E8F0; color:#475569; font-weight:700;">Статус / Сходство</th>
                  <th style="padding:9px 8px; border-bottom:1px solid #E2E8F0; color:#475569; font-weight:700;">Финанс. риск</th>
                  <th style="text-align:center; padding:9px 6px; border-bottom:1px solid #E2E8F0; color:#475569; font-weight:700;">Решение</th>
                </tr>
              </thead>
              <tbody id="demo-tbody">
                <!-- Строка 1: Проверка наименования (ГЭСНм) -->
                <tr onclick="selectDemoRow(0, this)" style="cursor:pointer; border-bottom:1px solid #F1F5F9;">
                  <td class="t-code" style="text-align:center; font-weight:600; color:#64748B;">#1</td>
                  <td style="padding:8px 10px;">
                    <b style="color:#0F172A; font-size:12.5px;">Монтаж Контроллера радиоканальных устройств</b>
                  </td>
                  <td style="padding:8px 10px;">
                    <div style="color:#334155; font-size:12px;">Устройства промежуточные на количество лучей: 10</div>
                    <div class="t-code" style="color:#64748B;">ГЭСНм10-08-001-11</div>
                  </td>
                  <td class="t-code" style="padding:8px 8px; font-weight:600; color:#334155;">1.0 шт → 1.0 шт</td>
                  <td style="padding:8px 8px;"><span class="badge b-part" style="background:#FEF9C3; color:#854D0E; border:1px solid #FEF08A; font-weight:600;">14% Проверка</span></td>
                  <td class="t-code" style="padding:8px 8px; color:#10B981; font-weight:600;">0 ₽</td>
                  <td style="text-align:center; padding:8px 6px;"><button style="border:none; background:none; cursor:pointer;">✓</button></td>
                </tr>

                <!-- Строка 2: Точное совпадение -->
                <tr onclick="selectDemoRow(1, this)" style="cursor:pointer; border-bottom:1px solid #F1F5F9;">
                  <td class="t-code" style="text-align:center; font-weight:600; color:#64748B;">#2</td>
                  <td style="padding:8px 10px;">
                    <b style="color:#0F172A; font-size:12.5px;">Контроллер радиоканальных устройств Панель-2-ПРО</b>
                  </td>
                  <td style="padding:8px 10px;">
                    <div style="color:#334155; font-size:12px;">Контроллер радиоканальных устройств Панель-2-ПРО</div>
                    <div class="t-code" style="color:#64748B;">ТЦ_63.4.00.00_54...</div>
                  </td>
                  <td class="t-code" style="padding:8px 8px; font-weight:600; color:#334155;">1.0 шт. → 1.0 шт.</td>
                  <td style="padding:8px 8px;"><span class="badge b-ok" style="background:#DCFCE7; color:#166534; border:1px solid #BBF7D0; font-weight:600;">100% Точно</span></td>
                  <td class="t-code" style="padding:8px 8px; color:#10B981; font-weight:600;">0 ₽</td>
                  <td style="text-align:center; padding:8px 6px;"><button style="border:none; background:none; cursor:pointer;">✓</button></td>
                </tr>

                <!-- Строка 3: Пересчёт сметных единиц 100 м <-> м -->
                <tr onclick="selectDemoRow(2, this)" style="cursor:pointer; border-bottom:1px solid #F1F5F9;">
                  <td class="t-code" style="text-align:center; font-weight:600; color:#64748B;">#26</td>
                  <td style="padding:8px 10px;">
                    <b style="color:#0F172A; font-size:12.5px;">Короб кабельный 40х25 мм</b>
                  </td>
                  <td style="padding:8px 10px;">
                    <div style="color:#334155; font-size:12px;">Короба пластмассовые</div>
                    <div class="t-code" style="color:#64748B;">ГЭСНм08-02-396-05</div>
                  </td>
                  <td class="t-code" style="padding:8px 8px; font-weight:600; color:#0284C7;">166 м → 1.66 (100 м)</td>
                  <td style="padding:8px 8px;"><span class="badge b-ok" style="background:#E0F2FE; color:#0369A1; border:1px solid #BAE6FD; font-weight:600;">100% Пересчёт OK</span></td>
                  <td class="t-code" style="padding:8px 8px; color:#10B981; font-weight:600;">0 ₽</td>
                  <td style="text-align:center; padding:8px 6px;"><button style="border:none; background:none; cursor:pointer;">✓</button></td>
                </tr>

                <!-- Строка 4: Реальная коллизия объёма с риском 1 003 ₽ -->
                <tr class="active-row" onclick="selectDemoRow(3, this)" style="cursor:pointer; border-bottom:1px solid #F1F5F9; background:#FEF2F2;">
                  <td class="t-code" style="text-align:center; font-weight:700; color:#B91C1C;">#78</td>
                  <td style="padding:8px 10px;">
                    <b style="color:#991B1B; font-size:12.5px;">Этикетка для кабеля, белая 25х38</b>
                  </td>
                  <td style="padding:8px 10px;">
                    <div style="color:#334155; font-size:12px;">Этикетка для кабеля Niimbot B1</div>
                    <div class="t-code" style="color:#64748B;">ТЦ_25.2.01.01_78...</div>
                  </td>
                  <td class="t-code" style="padding:8px 8px; font-weight:700; color:#B91C1C;">2.0 шт. → 1.0 шт.</td>
                  <td style="padding:8px 8px;"><span class="badge b-diff" style="background:#FFEDD5; color:#C2410C; border:1px solid #FED7AA; font-weight:700;">Расхождение объёма</span></td>
                  <td class="t-code" style="padding:8px 8px; color:#C2561B; font-weight:700;">1 003 ₽</td>
                  <td style="text-align:center; padding:8px 6px;"><button style="border:none; background:none; cursor:pointer; color:#C2410C; font-weight:bold;">✕</button></td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- Правый выдвижной инспектор (полная копия архитектуры Variant D) -->
          <div class="t-panel" id="demo-panel" style="padding:16px 18px; display:flex; flex-direction:column; gap:12px; background:#FAFAFA; border-left:1px solid #E2E8F0;">
            <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #E2E8F0; padding-bottom:10px;">
              <div>
                <span class="t-code" style="font-size:10.5px; color:#64748B; font-weight:700; letter-spacing:0.5px;">ИНСПЕКЦИЯ СТРОКИ</span>
                <div style="font-size:14px; font-weight:700; color:#0F172A;" id="p-title">Позиция #78: Этикетка для кабеля</div>
              </div>
              <div style="font-size:13px; font-weight:700; color:#C2561B; background:#FFEDD5; border:1px solid #FED7AA; border-radius:4px; padding:3px 8px;" id="p-sim">Коллизия</div>
            </div>

            <div style="background:#FFFFFF; border:1px solid #E2E8F0; border-radius:6px; padding:10px 12px; font-size:12px;">
              <table style="width:100%; border-collapse:collapse;">
                <tr>
                  <td style="color:#64748B; width:50px; padding:4px 0; font-weight:600;">ВОР:</td>
                  <td id="p-vor" style="color:#0F172A; padding:4px 0;">Этикетка для кабеля, белая 25х38, 200 шт. (<b>2.0 шт.</b>)</td>
                </tr>
                <tr>
                  <td style="color:#64748B; width:50px; padding:4px 0; font-weight:600;">ЛСР:</td>
                  <td id="p-lsr" style="color:#0F172A; padding:4px 0;">Этикетка для кабеля Niimbot B1 (<b>1.0 шт.</b>)</td>
                </tr>
                <tr>
                  <td style="color:#64748B; width:50px; padding:4px 0; font-weight:600;">Статус:</td>
                  <td id="p-status" style="padding:4px 0;"><b style="color:#C2410C;">Расхождение объёма:</b> ВОР=2.0 шт. vs ЛСР=1.0 шт. Занижение на 1 шт.</td>
                </tr>
              </table>
            </div>

            <!-- Блок финансового расчёта строго по ценам ЛСР -->
            <div style="background:#FFF7ED; border:1px solid #FED7AA; border-radius:6px; padding:12px 14px;" id="p-risk-box">
              <span style="font-size:11.5px; font-weight:700; color:#9A3412; text-transform:uppercase;">Финансовый риск по расценке ЛСР 421/пр:</span>
              <div style="font-size:22px; font-weight:800; font-family:'IBM Plex Mono', monospace; color:#C2561B; margin:4px 0;" id="p-risk-val">1 003 ₽</div>
              <div style="font-size:12px; color:#78350F; line-height:1.4;" id="p-risk-desc">
                Различие объёма: <b>1.0 шт.</b> × <b>1 003.28 ₽/шт</b> (сметная стоимость позиции №78 ЛСР) = <b>1 003.28 ₽</b>.
              </div>
            </div>

            <div style="display:flex; gap:8px; margin-top:auto;">
              <button class="btn" style="flex:1; background:#DCFCE7; color:#166534; border:1px solid #BBF7D0; font-size:12px; font-weight:600; padding:8px 10px; cursor:pointer;" onclick="alert('Решение зафиксировано: Расхождение принято инженером')">
                ✓ Согласовать (Y)
              </button>
              <button class="btn" style="flex:1; background:#FEE2E2; color:#991B1B; border:1px solid #FECACA; font-size:12px; font-weight:600; padding:8px 10px; cursor:pointer;" onclick="alert('Позиция отклонена: Добавлено замечание в дефектную ведомость')">
                ✕ Отклонить в акт (N)
              </button>
            </div>
          </div>
        </div>
      </div>'''

html = old_terminal_regex.sub(new_terminal_html, html)

# Also update the demoData in the script at the bottom of landing.html to match the 4 real items
old_script_data_regex = re.compile(r'const demoData = \[.*?\];', re.DOTALL)
new_script_data = '''const demoData = [
      {
        title: "Позиция #1: Монтаж контроллера",
        sim: "14% Проверка",
        vor: "Монтаж Контроллера радиоканальных устройств (<b>1.0 шт</b>)",
        lsr: "Устройства промежуточные на 10 лучей ГЭСНм10-08-001-11 (<b>1.0 шт</b>)",
        status: "<b style=\\"color:#854D0E;\\">Проверка наименования:</b> объёмы равны (1:1), коммерческое название ВОР заменено нормативным шифром ГЭСНм.",
        risk: "0 ₽ (Риск отсутствует)",
        desc: "Объёмы совпадают полностью (1 шт = 1 шт). Требуется подтверждение инженера о соответствии шифра ГЭСНм."
      },
      {
        title: "Позиция #2: Панель-2-ПРО",
        sim: "100% Точно",
        vor: "Контроллер радиоканальных устройств Панель-2-ПРО (<b>1.0 шт.</b>)",
        lsr: "Контроллер радиоканальных устройств Панель-2-ПРО (<b>1.0 шт.</b>)",
        status: "<b style=\\"color:#166534;\\">Точное совпадение:</b> наименование и физический объём полностью идентичны.",
        risk: "0 ₽ (Риск отсутствует)",
        desc: "Полная верификация 100%. Позиция осмечена корректно."
      },
      {
        title: "Позиция #26: Короб кабельный",
        sim: "100% Нормализация",
        vor: "Короб кабельный 40х25 мм (<b>166.0 м</b>)",
        lsr: "Короба пластмассовые ГЭСНм08-02-396-05 (<b>1.66 100 м = 166 м</b>)",
        status: "<b style=\\"color:#0369A1;\\">Автоматический пересчёт единиц:</b> масштаб 100 м ↔ м приведён модулем units.py без ошибок.",
        risk: "0 ₽ (Риск отсутствует)",
        desc: "Алгоритм предотвратил ложное срабатывание деления 166 / 1.66 благодаря таблице строительных размерностей."
      },
      {
        title: "Позиция #78: Этикетка для кабеля",
        sim: "Коллизия",
        vor: "Этикетка для кабеля, белая 25х38, 200 шт. (<b>2.0 шт.</b>)",
        lsr: "Этикетка для кабеля Niimbot B1 ТЦ_25.2... (<b>1.0 шт.</b>)",
        status: "<b style=\\"color:#C2410C;\\">Расхождение объёма:</b> в проекте заложено 2 шт., а в смете подрядчика учтена только 1 шт.",
        risk: "1 003 ₽",
        desc: "Различие объёма: 1.0 шт. × 1 003.28 ₽/шт (цена ЛСР 421/пр) = 1 003.28 ₽."
      }
    ];'''

html = old_script_data_regex.sub(new_script_data, html)

with open(landing_path, "w", encoding="utf-8") as f:
    f.write(html)

print("web/landing.html updated successfully with real panel styling and accurate numbers!")
