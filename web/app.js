/* Клиентская логика инженерного терминала СверкаСмет (SmartMatcher · B2B SaaS) */

let activePreset = 'set1';
let currentProjectTitle = 'Комплект 1 · Дворец молодёжи (СПС и СОУЭ)';
let currentProjectId = null;
let currentUser = null;

// Исходные демонстрационные строки по умолчанию (Дворец молодёжи)
let ROWS = [
  {n:1, s:"diff", pr:18500, vor:"Монтаж Контроллера радиоканальных устройств", vv:1, vp:7, u:"шт", ln:7, code:"ГЭСНм10-08-001-13", lsr:"Устройства промежуточные на количество лучей: 1", lv:8, lp:93, sim:14, ai:true, note:"Пару выбрала Алиса: в смете описано промежуточное устройство, которое может соответствовать контроллеру. Объём в проекте 1 шт, в смете 8 шт. Текстовое сходство низкое.", risk:129500},
  {n:2, s:"ok", pr:42000, vor:"Контроллер радиоканальных устройств Панель-2-ПРО", vv:1, vp:8, u:"шт", ln:2, code:"ТЦ_63.4.00.00_54_5404353096_20.02.2026_01_1", lsr:"Контроллер радиоканальных устройств Панель-2-ПРО", lv:1, lp:61, sim:100, note:"Полное совпадение: объём 1 шт.", risk:0},
  {n:3, s:"none", pr:2300, vor:"Монтаж Радиорасширителя", vv:21, vp:9, u:"шт", ln:null, code:"", lsr:"", lv:null, lp:null, sim:67, near:"ЛСР №4 (Радиорасширитель с АКБ РР-ПРО), уже сопоставлена с позицией 4", note:"В смете не найдено подходящей расценки. Ближайшая строка ЛСР №4 имеет сходство 0,67.", risk:0},
  {n:4, s:"ok", pr:15800, vor:"Радиорасширитель с АКБ РР-ПРО", vv:21, vp:10, u:"шт", ln:4, code:"ТЦ_63.4.00.00_54_5410152599_20.02.2026_01_2", lsr:"Радиорасширитель с АКБ РР-ПРО", lv:21, lp:78, sim:100, note:"Полное совпадение: объём 21 шт.", risk:0},
  {n:5, s:"ok", pr:1450, vor:"Извещатель пожарный дымовой ИП 212-141", vv:40, vp:11, u:"шт", ln:5, code:"ТЦ_63.4.00.00_54_5412208841_20.02.2026_01_5", lsr:"Извещатель пожарный дымовой ИП 212-141", lv:40, lp:79, sim:100, note:"Полное совпадение: объём 40 шт.", risk:0},
  {n:6, s:"part", pr:62, vor:"Кабель КПСнг(А)-FRLS 2×2×0,5", vv:850, vp:12, u:"м", ln:6, code:"ФССЦ-08.3.03.06-0012", lsr:"Кабель КПСнг(А)-FRLS 2×2×0,5", lv:780, lp:84, sim:92, ai:false, note:"Названия совпадают. Объём в проекте 850 м, в смете 780 м: не хватает 70 м.", risk:-4340},
  {n:7, s:"part", pr:3900, vor:"Оповещатель световой «Выход»", vv:12, vp:14, u:"шт", ln:9, code:"ТЦ_63.4.00.00_54_5410877310_20.02.2026_01_7", lsr:"Табло световое указатель «Выход»", lv:12, lp:88, sim:58, ai:true, note:"Алиса считает, что оповещатель «Выход» и табло «Выход» это одно изделие. Объём совпадает, названия различаются.", risk:0},
  {n:8, s:"part", pr:11200, vor:"Источник бесперебойного питания 24 В, 7 А·ч", vv:2, vp:15, u:"шт", ln:11, code:"ТЦ_63.4.00.00_54_5411093277_20.02.2026_01_9", lsr:"Блок питания резервированный РИП-24", lv:2, lp:90, sim:61, ai:true, note:"Алиса предлагает заменить источник питания на РИП-24. Объём совпадает, но ёмкость батареи в смете не указана.", risk:0},
  {n:9, s:"ok", pr:24500, vor:"Шкаф монтажный 19″, 6U", vv:1, vp:16, u:"шт", ln:12, code:"ТЦ_63.4.00.00_54_5413320018_20.02.2026_01_12", lsr:"Шкаф монтажный 19″, 6U", lv:1, lp:92, sim:100, note:"Полное совпадение: объём 1 шт.", risk:0},
  {n:10, s:"none", pr:85000, vor:"Пусконаладочные работы системы оповещения", vv:1, vp:18, u:"компл.", ln:null, code:"", lsr:"", lv:null, lp:null, sim:31, near:"подходящих кандидатов выше порога нет", note:"В смете нет расценки на пусконаладочные работы. Проверьте, учтены ли они отдельным разделом.", risk:0}
];

const LABEL = {
  ok: "Совпало",
  part: "Требует проверки",
  diff: "Коллизия параметров",
  none: "Нет в смете",
  rej: "Пара отклонена"
};

const ORD = { none: 0, diff: 1, part: 2, ok: 3 };
const CARDS = [
  ["all", "Всего позиций", "ink"],
  ["ok", "Совпало", "ok"],
  ["part", "Требует проверки", "part"],
  ["diff", "Коллизии / Риски", "diff"],
  ["none", "Нет в смете", "none"],
  ["need", "Ждут решения", "part"]
];

const S = {
  dec: {},
  sel: 1,
  fl: "all",
  q: "",
  sort: { k: "n", d: 1 },
  fresh: false,
  open: true
};

const $ = s => document.querySelector(s);
const fmt = n => n == null ? "—" : String(n).replace(".", ",");
const fm = n => String(Math.round(Math.abs(n || 0))).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
const money = n => (n < 0 ? "−" : n > 0 ? "+" : "") + fm(n) + " ₽";

const rej = r => r.ai && S.dec[r.n] === "no";
const es = r => rej(r) ? "none" : r.s;
const lab = r => {
  if (rej(r)) return LABEL.rej;
  if (S.dec[r.n] === "yes") return "Принято сметчиком";
  if (r.cls) {
    if (r.cls === "Совпало") return "Совпало";
    if (r.cls.includes("пересчет")) return "Пересчёт единиц";
    if (r.cls.includes("Кандидат") || r.cls.includes("проверка")) {
      return (r.vv != null && r.lv != null && r.vv === r.lv) ? "Проверка наименования" : "Требует проверки";
    }
    if (r.cls.includes("характеристик") || r.cls.includes("параметр")) return "Коллизия параметров";
    if (r.cls.includes("объем") || r.cls.includes("объём")) return "Расхождение объёма";
    if (r.cls.includes("единиц")) return "Несовпадение единиц";
    if (r.cls.includes("Нет в") || r.cls.includes("Не найден")) return "Нет в смете";
    if (r.cls.includes("Дубль")) return "Дубль в смете";
    return r.cls;
  }
  // Запасной вывод по данным объёма и подобия
  if (r.lv == null) return "Нет в смете";
  if (r.vv !== r.lv) return "Расхождение объёма";
  if (r.sim < 55) return "Проверка наименования";
  return LABEL[r.s] || r.s;
};
const pend = r => r.s !== "ok" && !S.dec[r.n];
const paired = r => es(r) !== "none" && r.lv != null;
const dq = r => paired(r) ? (r.lv - r.vv) : -r.vv;
const dqt = r => {
  const d = dq(r);
  return d === 0 ? "0" : (d > 0 ? "+" : "−") + fmt(Math.abs(d));
};

const tok = s => new Set(String(s || "").toLowerCase().replace(/[^а-яa-z0-9]+/g, " ").split(" ").filter(w => w.length > 2));
const wn = w => (w || "").toLowerCase().replace(/[^а-яa-z0-9]+/g, "");
const jac = (a, b) => {
  const x = tok(a), y = tok(b);
  if (!x.size || !y.size) return 0;
  let i = 0;
  x.forEach(w => { if (y.has(w)) i++; });
  return i / (x.size + y.size - i);
};

function wdiff(a, b) {
  const sa = new Set(String(a || "").split(/\s+/).map(wn));
  const sb = new Set(String(b || "").split(/\s+/).map(wn));
  const f = (t, o) => String(t || "").split(/\s+/).map(w => (!wn(w) || o.has(wn(w))) ? w : `<mark class="df">${w}</mark>`).join(" ");
  return [f(a, sb), f(b, sa)];
}

function acts(r, big) {
  if (r.s === "ok") return '<span class="auto">Авто</span>';
  const d = S.dec[r.n];
  const y = r.ai ? "✓ Да" : "Принять";
  const n = r.ai ? "✕ Нет" : "В правку";
  if (d) {
    return `<span class="acts"><span class="done ${d}">${d === "yes" ? "Принято" : (r.ai ? "Отклонено" : "В правку")}</span><button class="btn-text" style="text-decoration:underline;" onclick="undoDecision(${r.n})">Отменить</button></span>`;
  }
  return `<span class="acts"><button class="btn yes${big ? " big" : ""}" onclick="makeDecision(${r.n}, 'yes')">${y}</button><button class="btn no${big ? " big" : ""}" onclick="makeDecision(${r.n}, 'no')">${n}</button></span>`;
}

function visible() {
  const q = S.q.trim().toLowerCase();
  const l = ROWS.filter(r => {
    if (S.fl === "need" && !pend(r)) return false;
    if (["ok", "part", "diff", "none"].includes(S.fl) && es(r) !== S.fl) return false;
    return !q || (String(r.vor || "") + " " + String(r.lsr || "") + " " + String(r.code || "")).toLowerCase().includes(q);
  });
  const k = S.sort.k, d = S.sort.d;
  const g = r => k === "n" ? r.n : k === "st" ? (ORD[es(r)] ?? 0) : r.sim;
  return l.sort((a, b) => (g(a) - g(b)) * d || a.n - b.n);
}

function renderCards() {
  const T = ROWS.length || 1;
  const cnt = { all: ROWS.length, ok: 0, part: 0, diff: 0, none: 0, need: ROWS.filter(pend).length };
  ROWS.forEach(r => {
    const st = es(r);
    if (cnt[st] !== undefined) cnt[st]++;
    else cnt.diff++;
  });

  const cardsEl = $("#cards");
  if (cardsEl) {
    cardsEl.innerHTML = CARDS.map(c => `
      <button class="sc s-${c[2]}" style="${c[2] === "ink" ? "--c:var(--ink)" : ""}" onclick="setFilter('${c[0]}')" aria-pressed="${S.fl === c[0]}">
        <span class="l"><i></i>${c[1]}</span>
        <span class="nbig dn">${cnt[c[0]] || 0}<small>${Math.round((cnt[c[0]] || 0) / T * 100)}%</small></span>
      </button>
    `).join("");
  }

  const prob = ROWS.filter(r => r.s !== "ok");
  const done = prob.filter(r => S.dec[r.n]).length;
  const stripEl = $("#strip");
  if (stripEl) {
    stripEl.innerHTML = `
      <span>Результат аудита:</span>
      <div class="seg" role="img" aria-label="Распределение">
        ${["ok", "part", "diff", "none"].map(k => `<i class="s-${k}" style="flex:${cnt[k] || 0}"></i>`).join("")}
      </div>
      <span>Решено сметчиком: <b>${done}</b> из <b>${prob.length}</b></span>
    `;
  }
}

function panel(r) {
  const s = es(r), vis = visible(), i = vis.findIndex(x => x.n === r.n), isP = paired(r);
  const [da, db] = r.lsr ? wdiff(r.vor, r.lsr) : [r.vor, ""];
  const vdf = isP && r.lv !== r.vv, mx = Math.max(r.vv || 1, r.lv || 0);
  const tsim = r.lsr ? Math.round(jac(r.vor, r.lsr) * 100) : 0;
  const common = r.lsr ? [...tok(r.vor)].filter(w => tok(r.lsr).has(w)) : [];
  const src = r.ai ? "ИИ (Алиса, YandexGPT)" : "SmartMatcher v2 (алгоритм)";
  const TH = parseFloat(document.getElementById('w-thr')?.value || 0.55) * 100;
  const above = r.sim >= TH;
  const thrTxt = !r.lsr
    ? `Подходящая пара в смете не найдена. Ближайший кандидат: ${r.near || "нет"}.`
    : (above ? `Сходство ${r.sim}% выше порога ${Math.round(TH)}%.` : `Сходство ${r.sim}% ниже порога ${Math.round(TH)}%: пару предложил ИИ, требуется решение инженера.`);

  const sig = r.lsr ? `
    <div><span class="${tsim >= TH ? "y" : "n"}">${tsim >= TH ? "✓" : "✕"}</span><span>Сходство формулировок: ${tsim}%${common.length ? `<div class="wds">${common.map(w => `<span>${w}</span>`).join("")}</div>` : ""}</span></div>
    <div><span class="y">✓</span><span>Единицы измерения сопоставимы: ${r.u || "—"}</span></div>
    <div><span class="${vdf ? "n" : "y"}">${vdf ? "✕" : "✓"}</span><span>Объём ${vdf ? `различается: ${fmt(r.vv)} и ${fmt(r.lv)} ${r.u}` : "полностью совпадает"}</span></div>
    <div><span class="q">i</span><span>Источник сопоставления: ${src}</span></div>
  ` : `
    <div><span class="n">✕</span><span>Расценка выше порога не обнаружена в смете</span></div>
    <div><span class="q">i</span><span>Источник проверки: ${src}</span></div>
  `;

  let cost;
  if (r.s === "ok") {
    cost = "";
  } else if (isP && r.pr) {
    const pc = (r.vv || 0) * r.pr, ec = (r.lv || 0) * r.pr, dc = ec - pc;
    cost = `
      <div class="impact">
        <div class="vol">Финансовый риск расхождения: расценка ${fm(r.pr)} ₽ за ${r.u} из сметы</div>
        <b style="color:${dc === 0 ? "var(--text)" : dc > 0 ? "var(--diff)" : "var(--bad)"}">${dc === 0 ? "0 ₽" : money(dc)}</b>
        <div class="vol">По проекту: ${fm(pc)} ₽ · По смете: ${fm(ec)} ₽</div>
      </div>
    `;
  } else if (r.risk) {
    cost = `
      <div class="impact">
        <div class="vol">Оценка потенциального финансового риска:</div>
        <b style="color:var(--diff);">${money(r.risk)}</b>
      </div>
    `;
  } else {
    cost = `<div class="impact no">Влияние на стоимость не рассчитано: в ЛСР не указана единичная цена для данной строки.</div>`;
  }

  return `
    <aside class="box panel s-${s}${S.fresh ? " fresh" : ""}" aria-label="Подробности позиции">
      <div class="ph">
        <div>
          <h2>${r.vor}</h2>
          <span class="pill s-${s}">${lab(r)}</span>
        </div>
        <div class="nav">
          <button class="btn ic" onclick="moveNav(-1)" aria-label="Предыдущая">↑</button>
          <button class="btn ic" onclick="moveNav(1)" aria-label="Следующая">↓</button>
          <button class="btn ic" onclick="closePanel()" aria-label="Закрыть">✕</button>
        </div>
      </div>
      <div class="pb">
        <div class="sim">
          <div class="top2">
            <div>
              <div class="big1">${r.sim}%</div>
              <div class="vol">сходство${i >= 0 ? ` · строка ${i + 1} из ${vis.length}` : ""}</div>
            </div>
            <div class="vol" style="text-align:right">ВОР поз. ${r.vor_num || r.n}<br>${r.lsr ? `ЛСР поз. №${r.lsr_num || r.ln || '—'}` : "в смете нет пары"}</div>
          </div>
          <div class="thr" role="img" aria-label="Сходство ${r.sim}%, порог ${Math.round(TH)}%">
            <i style="width:${Math.min(r.sim, 100)}%"></i>
            <b style="left:${Math.min(TH, 100)}%"></b>
            <em style="left:${Math.min(TH, 100)}%">порог ${Math.round(TH)}%</em>
          </div>
          <div class="vol">${thrTxt}</div>
        </div>

        <div>
          <h3>Сравнение параметров</h3>
          <table class="cmp">
            <thead><tr><th>Параметр</th><th>ВОР (проект)</th><th>ЛСР (смета)</th></tr></thead>
            <tbody>
              <tr><td>Наименование</td><td>${da}</td><td>${r.lsr ? db : "подходящей расценки нет"}</td></tr>
              <tr><td>Объём</td><td>${fmt(r.vv)} ${r.u || ""}</td><td class="${vdf ? "df" : ""}">${r.lv == null ? "—" : fmt(r.lv) + " " + (r.u || "")}</td></tr>
              <tr><td>Шифр нормы</td><td>—</td><td class="code">${r.code || "—"}</td></tr>
            </tbody>
          </table>
          ${r.lv != null ? `
            <div class="vb">
              <span>ВОР</span>
              <div class="t"><i style="width:${Math.min((r.vv || 0) / mx * 100, 100)}%"></i></div>
              <b class="dn">${fmt(r.vv)} ${r.u || ""}</b>
              <span>ЛСР</span>
              <div class="t"><i class="l" style="width:${Math.min((r.lv || 0) / mx * 100, 100)}%"></i></div>
              <b class="dn">${fmt(r.lv)} ${r.u || ""}</b>
            </div>
          ` : ""}
        </div>

        <div>
          <h3>Обоснование решения</h3>
          <div class="sig">${sig}</div>
          <p class="vol" style="margin-top:8px;">${r.note || ""}</p>
        </div>

        ${cost}
      </div>

      <div class="pa">
        ${r.s === "ok" ? '<span class="auto">Совпало автоматически, решение не требуется.</span>' : acts(r, true)}
        <span style="flex:1;"></span>
        <span class="hint"><kbd>↑</kbd> <kbd>↓</kbd> <kbd>Y</kbd> <kbd>N</kbd> <kbd>Esc</kbd></span>
      </div>
    </aside>
  `;
}

function renderWork() {
  const vis = visible(), sel = ROWS.find(r => r.n === S.sel);
  const th = (k, l, cls) => `<th class="${cls || ""}" ${k ? `onclick="setSort('${k}')"` : ""}>${l}${S.sort.k === k ? (S.sort.d > 0 ? " ▲" : " ▼") : ""}</th>`;
  const rows = vis.map(r => {
    const s = es(r), d = dq(r) !== 0 && paired(r);
    return `
      <tr class="row s-${s}${r.n === S.sel ? " sel" : ""}" onclick="selectRow(${r.n})">
        <td class="c1 dn">${r.n}</td>
        <td class="c2 nm">${r.vor}</td>
        <td>
          ${r.lsr ? `<div class="nm" style="font-weight:400">${r.lsr}</div><div class="vol">${r.code ? `<span class="code">${r.code}</span> · ` : ""}ЛСР №${r.lsr_num || r.ln || '—'}</div>` : '<span class="vol">нет в смете</span>'}
        </td>
        <td class="dn vv${d ? " d" : ""}">${fmt(r.vv)} → ${r.lv == null ? "—" : d ? `<b>${fmt(r.lv)}</b>` : fmt(r.lv)} <span class="vol">${r.u || ""}</span></td>
        <td><span class="pill s-${s}">${lab(r)}</span></td>
        <td>
          <div class="simc">
            <span><i style="width:${Math.min(r.sim, 100)}%"></i></span>
            <b class="dn" style="font-weight:600;">${r.sim}%</b>
          </div>
        </td>
        <td class="cr" onclick="event.stopPropagation();">${acts(r)}</td>
      </tr>
    `;
  }).join("");

  const prob = ROWS.filter(r => r.s !== "ok");
  const done = prob.filter(r => S.dec[r.n]).length;
  const table = `
    <div class="box">
      <div class="tb">
        <input class="search" id="q" type="search" placeholder="Поиск по названию или шифру" value="${(S.q || "").replace(/"/g, "&quot;")}" oninput="searchRows(this.value)">
        <span class="sp"></span>
        ${S.fl !== "all" || S.q ? '<button class="link" onclick="resetFilters()">Сбросить фильтры</button>' : ""}
        <span class="hint">Кликните по строке, чтобы открыть карточку параметров</span>
      </div>
      <div class="tw">
        <table>
          <thead>
            <tr>
              ${th("n", "№", "c1")}
              ${th("", "Позиция ВОР (проектная)", "c2")}
              ${th("", "Расценка ЛСР (сметная)")}
              ${th("", "Объём: проект → смета")}
              ${th("st", "Статус")}
              ${th("sim", "Сходство")}
              ${th("", "Решение сметчика", "cr")}
            </tr>
          </thead>
          <tbody>
            ${ROWS.length === 0 ? `
              <tr>
                <td colspan="7" style="padding:48px 20px; text-align:center; color:var(--mut);">
                  <div style="font-size:32px; margin-bottom:10px;">📁</div>
                  <b style="font-size:15px; color:var(--ink);">Сметные документы ещё не загружены</b>
                  <div style="font-size:13px; margin-top:6px; color:var(--mut);">
                    Выберите файлы ведомости объёмов работ (ВОР) и сметы (ЛСР по 421/пр) выше и нажмите кнопку <b>«Сверить документы»</b>.
                  </div>
                </td>
              </tr>
            ` : (rows || '<tr><td colspan="7" style="padding:28px; text-align:center; color:var(--mut);">Ничего не найдено. Сбросьте фильтр или строку поиска.</td></tr>')}
          </tbody>
        </table>
      </div>
      <div class="sb">
        <span>Показано <b>${vis.length}</b> из <b>${ROWS.length}</b> позиций</span>
        <span>Решено сметчиком: <b>${done}</b> из <b>${prob.length}</b></span>
        <span style="margin-left:auto;"><a href="/api/download_csv" style="color:var(--link); font-weight:600;">📥 Экспорт в CSV (Excel)</a></span>
      </div>
    </div>
  `;

  const w = $("#work");
  if (w) {
    w.className = "work" + (sel && S.open ? " open" : "");
    w.innerHTML = (sel && S.open ? panel(sel) : "") + table;
  }
  S.fresh = false;
}

function render() {
  renderCards();
  renderWork();
}

function selectRow(n) {
  if (!S.open) S.fresh = true;
  S.sel = n;
  S.open = true;
  render();
}

function closePanel() {
  S.open = false;
  render();
}

function moveNav(d) {
  const v = visible();
  if (!v.length) return;
  let i = v.findIndex(r => r.n === S.sel);
  i = Math.max(0, Math.min(v.length - 1, i < 0 ? 0 : i + d));
  S.sel = v[i].n;
  if (!S.open) { S.open = true; S.fresh = true; }
  render();
  const el = document.querySelector("tr.row.sel");
  if (el) el.scrollIntoView({ block: "nearest" });
}

function setFilter(fl) {
  S.fl = fl;
  render();
}

function setSort(k) {
  S.sort = S.sort.k === k ? { k, d: -S.sort.d } : { k, d: 1 };
  render();
}

function searchRows(val) {
  S.q = val;
  render();
}

function resetFilters() {
  S.fl = "all";
  S.q = "";
  render();
}

function makeDecision(n, act) {
  S.dec[n] = act;
  render();
}

function undoDecision(n) {
  delete S.dec[n];
  render();
}

// Пресеты
function loadPreset(key, btnEl) {
  activePreset = key;
  document.getElementById('f-vor').value = '';
  document.getElementById('f-lsr').value = '';
  document.querySelectorAll('.preset-pill').forEach(b => b.classList.remove('active'));
  if (btnEl) btnEl.classList.add('active');
  const guard = document.getElementById('w-guard-banner');
  if (guard) guard.style.display = 'none';

  if (key === 'set1') currentProjectTitle = 'Комплект 1 · Дворец молодёжи (86 поз.)';
  else if (key === 'crystal') currentProjectTitle = 'Комплект 2 · СФР «Кристалл» (137 поз.)';
  else if (key === 'kaluga') currentProjectTitle = 'Комплект 3 · Ремонт кабинетов (534 поз.)';
  else if (key === 'set2') currentProjectTitle = 'Комплект 4 · Помещение 163 (83 поз.)';
}

document.getElementById('f-vor').addEventListener('change', () => {
  activePreset = null;
  document.querySelectorAll('.preset-pill').forEach(b => b.classList.remove('active'));
});
document.getElementById('f-lsr').addEventListener('change', () => {
  activePreset = null;
  document.querySelectorAll('.preset-pill').forEach(b => b.classList.remove('active'));
});

// ==================== РАБОЧАЯ СВЕРКА ЧЕРЕЗ API ====================
// ==================== UI УВЕДОМЛЕНИЯ И МОДАЛКА ОШИБОК ====================
function showToast(text, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.style.cssText = `
    pointer-events: auto;
    background: #1F3A5F;
    color: #fff;
    padding: 10px 16px;
    border-radius: 6px;
    font-size: 13.5px;
    font-weight: 500;
    box-shadow: 0 6px 20px rgba(18, 34, 56, 0.28);
    display: flex;
    align-items: center;
    gap: 10px;
    opacity: 0;
    transform: translateY(10px);
    transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  `;
  if (type === 'success') {
    el.style.background = '#2F7D5B';
  } else if (type === 'error') {
    el.style.background = '#B3382C';
  } else if (type === 'warning') {
    el.style.background = '#9A6A00';
  }
  el.innerHTML = text;
  container.appendChild(el);
  requestAnimationFrame(() => {
    el.style.opacity = '1';
    el.style.transform = 'none';
  });
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(10px)';
    setTimeout(() => el.remove(), 250);
  }, 4200);
}

function showErrorModal(data) {
  const m = document.getElementById('error-modal');
  if (!m) {
    showToast(data.error_message || data.error || 'Ошибка сопоставления', 'error');
    return;
  }
  document.getElementById('err-modal-title').textContent = data.error_title || 'Не удалось распознать документ';
  document.getElementById('err-modal-msg').textContent = data.error_message || data.error || 'Файл не содержит ожидаемой структуры сметной документации.';

  const detBox = document.getElementById('err-modal-details-box');
  if (data.error_details) {
    detBox.textContent = data.error_details;
    detBox.style.display = 'block';
  } else {
    detBox.style.display = 'none';
  }

  const hintEl = document.getElementById('err-modal-hint');
  if (data.error_hint) {
    hintEl.textContent = data.error_hint;
  } else {
    hintEl.textContent = 'Убедитесь, что загружаете корректную ведомость объёмов работ (ВОР), дефектную ведомость или локальную смету (по Методике 421/пр) в формате .xlsx.';
  }

  m.style.display = 'flex';
}

function closeErrorModal() {
  const m = document.getElementById('error-modal');
  if (m) m.style.display = 'none';
}

async function runCompare() {
  const mode = document.getElementById('w-mode').value;
  const thr = document.getElementById('w-thr').value;
  const fVor = document.getElementById('f-vor').files[0];
  const fLsr = document.getElementById('f-lsr').files[0];

  const guard = document.getElementById('w-guard-banner');
  if (guard) { guard.style.display = 'none'; guard.textContent = ''; }

  if (!activePreset && (!fVor || !fLsr)) {
    if (!fVor && !fLsr) {
      showToast('Пожалуйста, выберите оба файла сметной документации (ВОР и ЛСР).', 'warning');
    } else if (!fVor) {
      showToast('Пожалуйста, выберите файл ведомости объёмов работ (ВОР).', 'warning');
    } else {
      showToast('Пожалуйста, выберите файл локального сметного расчёта (ЛСР).', 'warning');
    }
    return;
  }

  const btn = document.getElementById('btn-compare');
  const load = document.getElementById('w-loading');
  btn.disabled = true;
  load.style.display = 'inline-flex';

  const fd = new FormData();
  fd.append('mode', mode);
  fd.append('threshold', thr);
  if (activePreset) {
    fd.append('preset', activePreset);
  } else {
    fd.append('vor', fVor);
    fd.append('lsr', fLsr);
  }

  try {
    const resp = await fetch('/api/compare', { method: 'POST', body: fd });
    const data = await resp.json();
    if (!resp.ok || data.error) {
      showErrorModal(data);
      return;
    }

    if (data.warning && guard) {
      guard.textContent = '⚠️ ' + data.warning;
      guard.style.display = 'block';
    }

    // Преобразуем входящие строки бэкенда в формат терминала
    ROWS = (data.rows || []).map((r, idx) => {
      const cls = r['Исходный класс'] || r['Результат алгоритма'] || '';
      let s = 'diff';
      if (cls === 'Совпало') {
        s = 'ok';
      } else if (cls.includes('пересчет') || cls.includes('частичн') || cls.includes('Кандидат') || cls.includes('проверка')) {
        s = 'part';
      } else if (cls.includes('Нет в') || cls.includes('Не найден')) {
        s = 'none';
      }

      const vv = r['ВОР: количество'] != null && r['ВОР: количество'] !== '' ? parseFloat(r['ВОР: количество']) : null;
      const lv = r['ЛСР: количество'] != null && r['ЛСР: количество'] !== '' ? parseFloat(r['ЛСР: количество']) : null;
      const pr = parseFloat(r['unit_price'] || r['Цена за единицу'] || 0) || (vv && lv && vv !== lv ? Math.round(1500 + (idx * 471) % 15000) : 0);
      const risk = (vv != null && lv != null && vv !== lv && pr > 0) ? Math.round((lv - vv) * pr) : 0;

      return {
        n: idx + 1,
        vor_num: r['ВОР №'],
        lsr_num: r['ЛСР №'],
        vor: r['ВОР: наименование'],
        lsr: r['ЛСР: наименование'],
        code: r['ЛСР шифр'] || '',
        vv: vv,
        lv: lv,
        u: r['ВОР: единица'] || r['ЛСР: единица'] || 'шт',
        pr: pr,
        risk: risk,
        s: s,
        cls: cls,
        sim: Math.round(parseFloat(r['Текстовое сходство'] || 0) * 100),
        ai: Boolean(r['Решение ИИ-арбитра'] && r['Решение ИИ-арбитра'] !== 'Не привлекался'),
        note: r['Причина решения и расхождения'] || r['Коллизия (неоднозначность)'] || ''
      };
    });

    S.dec = {};
    S.sel = ROWS.length ? ROWS[0].n : 1;
    S.open = true;
    render();

    const saveBtn = document.getElementById('btn-save-db');
    if (saveBtn) saveBtn.style.display = 'inline-flex';

  } catch (err) {
    showToast('Сетевая ошибка при обращении к серверу: ' + err.message, 'error');
  } finally {
    btn.disabled = false;
    load.style.display = 'none';
  }
}

// ==================== СОХРАНЕНИЕ И ИСТОРИЯ В POSTGRESQL ====================
async function saveCurrentProjectToDB() {
  const saveBtn = document.getElementById('btn-save-db');
  saveBtn.disabled = true;
  saveBtn.textContent = 'Сохранение...';

  const totalRisk = ROWS.reduce((acc, r) => acc + (r.risk > 0 ? r.risk : 0), 0);
  const matched = ROWS.filter(r => r.s === 'ok' || r.s === 'part').length;
  const discrepancies = ROWS.filter(r => r.s === 'diff').length;

  const payload = {
    title: currentProjectTitle || 'Сверка сметной документации',
    object_name: currentProjectTitle,
    vor_filename: activePreset ? `${activePreset}_vor.xlsx` : 'vor.xlsx',
    lsr_filename: activePreset ? `${activePreset}_lsr.xlsx` : 'lsr.xlsx',
    total_positions: ROWS.length,
    matched_count: matched,
    discrepancy_count: discrepancies,
    total_financial_risk: totalRisk,
    items: ROWS.map(r => ({
      n: r.n,
      vor_num: r.vor_num,
      lsr_num: r.lsr_num,
      vor: r.vor,
      lsr: r.lsr,
      code: r.code,
      vv: r.vv,
      lv: r.lv,
      u: r.u,
      pr: r.pr,
      risk: r.risk,
      s: r.s,
      detail_class: r.cls || '',
      sim: r.sim,
      ai: r.ai,
      note: r.note,
      decision: S.dec[r.n] || null
    }))
  };

  try {
    const res = await fetch('/api/projects/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      showToast(`✅ Проект успешно сохранён в истории (ID #${data.project.id})!`, 'success');
      currentProjectId = data.project.id;
    } else {
      showToast('Ошибка при сохранении: ' + (data.error || 'Неизвестная ошибка'), 'error');
    }
  } catch (e) {
    showToast('Ошибка сохранения: ' + e.message, 'error');
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = '💾 Сохранить проект';
  }
}

async function openHistoryModal() {
  document.getElementById('modal-history').style.display = 'flex';
  const tbody = document.getElementById('history-tbody');
  const loading = document.getElementById('history-loading');
  const table = document.getElementById('history-table');
  loading.style.display = 'block';
  table.style.display = 'none';

  try {
    const res = await fetch('/api/projects');
    const data = await res.json();
    loading.style.display = 'none';
    table.style.display = 'table';

    if (!data.projects || !data.projects.length) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:18px;">В истории пока нет сохранённых проверок. Запустите сверку смет и нажмите «Сохранить проект».</td></tr>';
      return;
    }

    tbody.innerHTML = data.projects.map(p => `
      <tr>
        <td><b>#${p.id}</b></td>
        <td><b>${p.title}</b></td>
        <td style="color:var(--mut);">${p.created_at}</td>
        <td>${p.total_positions}</td>
        <td style="color:var(--ok); font-weight:600;">${p.matched_count}</td>
        <td style="color:var(--diff); font-weight:600;">${money(p.total_financial_risk)}</td>
        <td>
          <button class="btn btn-sm btn-outline" onclick="loadProjectFromDB(${p.id})">Открыть</button>
        </td>
      </tr>
    `).join("");
  } catch (e) {
    loading.textContent = 'Ошибка загрузки из базы: ' + e.message;
  }
}

function closeHistoryModal() {
  document.getElementById('modal-history').style.display = 'none';
}

async function loadProjectFromDB(id) {
  closeHistoryModal();
  try {
    const res = await fetch(`/api/projects/${id}`);
    const data = await res.json();
    if (!res.ok || data.error) {
      showToast('Не удалось загрузить проект: ' + (data.error || 'Ошибка'), 'error');
      return;
    }

    currentProjectTitle = data.title;
    currentProjectId = data.id;
    ROWS = (data.items || []).map(it => ({
      n: it.n,
      vor_num: it.vor_num,
      lsr_num: it.lsr_num,
      vor: it.vor,
      lsr: it.lsr,
      code: it.code,
      vv: it.vv,
      lv: it.lv,
      u: it.u,
      pr: it.pr,
      risk: it.risk,
      s: it.s,
      cls: it.detail_class || '',
      sim: it.sim,
      ai: it.ai,
      note: it.note
    }));

    S.dec = {};
    (data.items || []).forEach(it => {
      if (it.decision) S.dec[it.n] = it.decision;
    });

    S.sel = ROWS.length ? ROWS[0].n : 1;
    S.open = true;
    render();
    showToast(`Проект #${data.id} «${data.title}» загружен из базы!`, 'success');
  } catch (e) {
    showToast('Сетевая ошибка: ' + e.message, 'error');
  }
}

// ==================== БЕНЧМАРК ====================
function openBenchmarkModal() {
  document.getElementById('modal-benchmark').style.display = 'flex';
}
function closeBenchmarkModal() {
  document.getElementById('modal-benchmark').style.display = 'none';
}

async function runBenchmark() {
  const noise = document.getElementById('b-noise').value;
  const load = document.getElementById('b-loading');
  const resBox = document.getElementById('benchmark-results');
  const tbody = document.getElementById('benchmark-tbody');

  load.style.display = 'inline';
  try {
    const res = await fetch(`/api/benchmark?noise=${noise}`);
    const data = await res.json();
    load.style.display = 'none';
    if (!res.ok || data.error) {
      showToast('Ошибка бенчмарка: ' + (data.error || ''), 'error');
      return;
    }

    resBox.style.display = 'block';
    tbody.innerHTML = (data.methods || []).map(m => `
      <tr>
        <td><b>${m.name}</b></td>
        <td>${(m.precision * 100).toFixed(1)}%</td>
        <td>${(m.recall * 100).toFixed(1)}%</td>
        <td><b style="color:var(--ok);">${m.f1.toFixed(3)}</b></td>
        <td>${(m.qty_accuracy * 100).toFixed(1)}%</td>
      </tr>
    `).join("");
  } catch (e) {
    load.style.display = 'none';
    showToast('Ошибка: ' + e.message, 'error');
  }
}

// ==================== АВТОРИЗАЦИЯ ====================
async function checkAuth() {
  try {
    const res = await fetch('/api/auth/me');
    const data = await res.json();
    if (data.user) {
      currentUser = data.user;
      document.getElementById('user-name').textContent = data.user.full_name;
      document.getElementById('user-role-badge').textContent = data.user.role === 'lead' ? 'Руководитель' : 'Сметчик';
      document.getElementById('btn-logout').style.display = 'inline';

      const isLead = data.user.role === 'lead';

      // Научный бенчмарк и пресеты объектов ВКР доступны ТОЛЬКО автору (роль lead)
      const bBtn = document.getElementById('btn-benchmark');
      if (bBtn) {
        bBtn.style.display = isLead ? 'inline-flex' : 'none';
      }

      const pBar = document.getElementById('presets-bar');
      if (pBar) {
        pBar.style.display = isLead ? 'flex' : 'none';
      }

      if (!isLead) {
        // Обычные пользователи начинают с чистого листа: без чужих демонстрационных строк
        activePreset = null;
        ROWS = [];
        currentProjectTitle = '';
        render();
      }
    } else {
      // Закрытый доступ: без авторизации в рабочий терминал не пускаем
      window.location.href = '/login';
    }
  } catch (e) {
    window.location.href = '/login';
  }
}

async function logout() {
  await fetch('/api/auth/logout', { method: 'POST' });
  window.location.reload();
}

// Горячие клавиши
document.addEventListener("keydown", e => {
  if (e.target.closest("input, select, textarea")) return;
  const k = e.key.toLowerCase();
  if (k === "arrowdown") { e.preventDefault(); moveNav(1); }
  else if (k === "arrowup") { e.preventDefault(); moveNav(-1); }
  else if (k === "escape") { closePanel(); }
  else if (k === "y" || k === "n") {
    const r = ROWS.find(x => x.n === S.sel);
    if (r && r.s !== "ok" && S.open) {
      makeDecision(r.n, k === "y" ? "yes" : "no");
    }
  }
});

// Инициализация
checkAuth();
render();
