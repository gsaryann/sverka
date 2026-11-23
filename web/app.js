/* Клиентская логика инженерного терминала СверкаСмет (SmartMatcher · B2B SaaS · Вариант E v2) */

const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

let ROWS = [];
let currentProjectTitle = 'Сверка сметной документации';
let currentProjectId = null;
let currentUser = null;
let activePreset = null;
let TH = 55;

const S = {
  saved: [],
  dec: {},
  hist: [],
  sel: null,
  fl: 'need',
  q: '',
  sort: [{ k: 'n', d: 1 }],
  open: true
};

const fmt = n => (n == null || isNaN(n)) ? '—' : String(n).replace('.', ',');
const fm = n => String(Math.round(Math.abs(n || 0))).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const STD = [10, 100, 1000, 10000];
const mult = r => r.unit_multiplier || (r.lv ? Math.round(r.vv / r.lv) : 0);

function classifyItem(r) {
  let s = /пересчет/i.test(r.cls || '') ? 'unit' : (r.s || 'diff');
  if (s === 'none' || r.lv == null) {
    s = 'none';
  } else if (s === 'unit') {
    const f = r.unit_multiplier || (r.lv ? (r.vv / r.lv) : 1);
    const k = Math.round(f);
    if (!STD.includes(k) || Math.abs(f - k) > k * 0.01) {
      s = 'diff';
      r.unitWarn = Math.round(f * 100) / 100;
    }
  }
  r.st = s;
}

const todo = r => ['part', 'diff', 'none'].includes(r.st);
const need = r => todo(r) && !S.dec[r.n];

const LAB = r => {
  if (r.st === 'none') return 'Нет в смете';
  if (r.st === 'ok') return 'Совпало';
  if (r.st === 'unit') return 'Пересчёт ед.';
  if (r.st === 'diff') return 'Расхождение объёма';
  return (r.vv === r.lv) ? 'Проверка наименования' : 'Требует проверки';
};

const ORD = { none: 0, diff: 1, part: 2, unit: 3, ok: 4 };
const KEY = {
  n: r => r.n,
  st: r => ORD[r.st] ?? 2,
  sim: r => r.sim || 0,
  risk: r => r.risk || 0,
  vor: r => r.vor || ''
};

const PRE = {
  n: [{ k: 'n', d: 1 }],
  risk: [{ k: 'risk', d: -1 }, { k: 'st', d: 1 }],
  sim: [{ k: 'sim', d: 1 }],
  prio: [{ k: 'st', d: 1 }, { k: 'risk', d: -1 }, { k: 'sim', d: 1 }]
};

const COLS = [
  ['n', '№'],
  ['vor', 'Позиция ВОР'],
  [null, 'Расценка ЛСР'],
  [null, 'Объём: проект → смета'],
  ['st', 'Статус'],
  ['sim', 'Сход.'],
  ['risk', 'Риск'],
  [null, 'Решение']
];

const wn = w => (w || '').toLowerCase().replace(/[^а-яa-z0-9]+/g, '');
function wdiff(a, b) {
  const sa = new Set((a || '').split(/\s+/).map(wn));
  const sb = new Set((b || '').split(/\s+/).map(wn));
  const f = (t, o) => (t || '').split(/\s+/).map(w => !wn(w) || o.has(wn(w)) ? esc(w) : `<mark>${esc(w)}</mark>`).join(' ');
  return [f(a, sb), f(b, sa)];
}

function visible() {
  const q = S.q.trim().toLowerCase();
  return ROWS.filter(r => {
    if (S.fl === 'need' && !need(r)) return false;
    if (S.fl === 'done' && !S.dec[r.n]) return false;
    if (['ok', 'unit', 'part', 'diff', 'none'].includes(S.fl) && r.st !== S.fl) return false;
    if (S.fl === 'risk' && !(r.risk > 0)) return false;
    return !q || (r.vor + ' ' + (r.lsr || '') + ' ' + (r.code || '')).toLowerCase().includes(q) || String(r.n) === q;
  }).sort((a, b) => {
    for (const { k, d } of S.sort) {
      const x = KEY[k](a), y = KEY[k](b);
      const c = typeof x === 'string' ? x.localeCompare(y, 'ru') : x - y;
      if (c) return c * d;
    }
    return a.n - b.n;
  });
}

function volCell(r) {
  if (r.lv == null) return `${fmt(r.vv)} → —`;
  if (r.st === 'unit') {
    return `${fmt(r.vv)} → ${fmt(r.lv)} <span class="pl s-unit" title="Пересчёт единиц: ЛСР в укрупнённых единицах, объёмы эквивалентны">×${mult(r)}</span>`;
  }
  if (r.vv !== r.lv) {
    const d = +(r.lv - r.vv).toFixed(2);
    return `${fmt(r.vv)} → <b style="color:var(--diff)">${fmt(r.lv)}</b> <span class="pl s-diff">Δ ${d > 0 ? '+' : '−'}${fmt(Math.abs(d))}</span>`;
  }
  return `${fmt(r.vv)} → ${fmt(r.lv)}`;
}

function decCell(r) {
  const d = S.dec[r.n];
  if (!todo(r) && !d) {
    return '<span class="mut">Авто</span> <button class="a no" data-a="no" title="Переопределить: в правку (N)">✕</button>';
  }
  if (d) {
    return `<span class="pl ${d === 'yes' ? 's-ok' : 's-diff'}">${d === 'yes' ? '✓ Принято' : '↪ В правку'}</span> <button class="a" data-a="u" title="Отменить">↶</button>`;
  }
  return `<button class="a yes" data-a="yes" title="Принять (Y)">✓</button> <button class="a no" data-a="no" title="В правку (N)">✕</button>`;
}

function renderChips() {
  const c = f => ROWS.filter(r => f === 'all' ? 1 : f === 'need' ? need(r) : f === 'done' ? !!S.dec[r.n] : r.st === f).length;
  $('#chips').innerHTML = [
    ['need', '⏳ Ждут решения'],
    ['done', '✓ Решено'],
    ['all', 'Все'],
    ['ok', 'Совпало'],
    ['unit', 'Пересчёт ед.'],
    ['part', 'Проверка'],
    ['diff', 'Коллизия'],
    ['none', 'Нет в смете']
  ].map(([f, l]) => `<button class="chip${S.fl === f ? ' on' : ''}"${f === 'none' ? ' style="color:var(--bad)"' : ''} data-f="${f}">${l} <b>${c(f)}</b></button>`).join('');

  $('#risk').className = 'chip' + (S.fl === 'risk' ? ' on' : '');
  const ri = riskInfo();
  $('#risk').title = `Считается по расценкам ЛСР: ${ri.known} из ${ri.known + ri.unknown} расхождений объёма`;
  $('#risk').innerHTML = `💸 Финансовый риск: ${ri.known ? `<b style="color:var(--diff)">${fm(ri.sum)} ₽</b>` : ri.unknown ? '<b class="mut">не рассчитан</b>' : '<b>0 ₽</b>'}${ri.unknown ? ` <span class="mut">· без цены: ${ri.unknown}</span>` : ''}`;
}

function riskInfo() {
  const known = ROWS.filter(r => r.risk > 0);
  const unknown = ROWS.filter(r => todo(r) && r.lv != null && r.vv !== r.lv && !(r.risk > 0));
  return {
    known: known.length,
    unknown: unknown.length,
    sum: known.reduce((s, r) => s + r.risk, 0)
  };
}

function renderHead() {
  $('#hd').innerHTML = COLS.map(([k, l]) => {
    const i = S.sort.findIndex(s => s.k === k);
    return `<th class="${k ? 'so' : ''}"${k ? ` data-k="${k}"` : ''}>${l}${i < 0 ? '' : ` <span class="mono">${S.sort.length > 1 ? i + 1 : ''}${S.sort[i].d > 0 ? '▲' : '▼'}</span>`}</th>`;
  }).join('');
}

function renderTable() {
  const v = visible();
  $('#tb').innerHTML = v.length ? v.map(r => `
    <tr class="r${r.n === S.sel ? ' sel' : ''}" data-n="${r.n}">
      <td class="mono" style="text-align:center">${r.n}</td>
      <td><div class="cl"><b>${esc(r.vor)}</b></div></td>
      <td>${r.lsr ? `<div class="cl">${esc(r.lsr)}</div><div class="mono mut" style="font-size:10.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(r.code || '')}</div>` : '<span class="mut">нет в смете</span>'}</td>
      <td class="mono" style="white-space:nowrap">${volCell(r)} <span class="mut">${esc(r.u || '')}</span></td>
      <td><span class="pl s-${r.st}">${LAB(r)}</span></td>
      <td class="mono mut">${r.sim}%</td>
      <td class="mono">${r.risk > 0 ? `<b style="color:var(--diff)">${fm(r.risk)} ₽</b>` : '<span class="mut">—</span>'}</td>
      <td style="text-align:center;white-space:nowrap">${decCell(r)}</td>
    </tr>
  `).join('') : `<tr><td colspan="8" class="mut" style="padding:30px;text-align:center">${S.fl === 'need' && !S.q ? '🎉 Все позиции, требующие решения, обработаны' : 'Ничего не найдено'}</td></tr>`;
  return v;
}

function renderInsp(v) {
  const r = ROWS.find(x => x.n === S.sel);
  const el = $('#insp');
  if (!r) { el.innerHTML = ''; return; }

  const i = v.findIndex(x => x.n === r.n);
  const d = S.dec[r.n];
  const [da, db] = r.lsr ? wdiff(r.vor, r.lsr) : [esc(r.vor), ''];
  const mx = Math.max(r.vv || 1, r.lv || 0);
  const ok = r.sim >= TH;
  const c = ok ? 'var(--ok)' : 'var(--part)';

  let vol;
  if (r.lv == null) {
    vol = 'В смете пары нет.';
  } else if (r.st === 'unit') {
    vol = `ВОР: <b>${fmt(r.vv)} ${esc(r.u)}</b> · ЛСР: <b>${fmt(r.lv)}</b> в укрупнённых единицах (×${mult(r)}). Объёмы эквивалентны, расхождения нет.`;
  } else if (r.vv === r.lv) {
    vol = `Объём совпадает: <b>${fmt(r.vv)} ${esc(r.u)}</b>`;
  } else {
    vol = `
      <div style="display:grid;grid-template-columns:34px 1fr 80px;gap:4px 8px;align-items:center">
        <span class="mut">ВОР</span>
        <div class="bk"><i style="width:${(r.vv / mx) * 100}%"></i></div>
        <b class="mono">${fmt(r.vv)}</b>
        <span class="mut">ЛСР</span>
        <div class="bk"><i style="width:${(r.lv / mx) * 100}%;background:var(--diff)"></i></div>
        <b class="mono">${fmt(r.lv)}</b>
      </div>
    `;
  }

  if (r.unitWarn) {
    vol += `<div style="color:var(--diff);margin-top:6px">⚠ Отношение объёмов ×${r.unitWarn} не равно стандартному коэффициенту пересчёта (10/100/1000/10000): возможен завышенный или заниженный объём.</div>`;
  }

  const cost = !todo(r) ? '' : r.risk > 0 ? `
    <div class="box" style="background:#FFF7ED;border-color:#FED7AA">
      <h4>Финансовый риск</h4>
      <b style="font-size:18px;color:var(--diff)">${fm(r.risk)} ₽</b>
      ${r.pr ? `<div class="mut" style="font-size:11.5px;margin-top:3px;">расценка ${fm(r.pr)} ₽ за ${esc(r.u)}: проект ${fm(r.vv * r.pr)} ₽ · смета ${fm(r.lv * r.pr)} ₽</div>` : ''}
    </div>
  ` : `
    <div class="box">
      <h4>Влияние на стоимость</h4>
      ${r.pr ? '0 ₽ — объёмы совпадают' : 'не рассчитано: в ЛСР нет единичной цены'}
    </div>
  `;

  el.innerHTML = `
    <div class="ih">
      <div>
        <b>#${r.n}</b> <span class="pl s-${r.st}">${LAB(r)}</span>
        ${i >= 0 ? `<div class="mut" style="font-size:11.5px">строка ${i + 1} из ${v.length}</div>` : ''}
      </div>
      <div style="display:flex;gap:4px">
        <button class="btn" data-nav="-1">↑</button>
        <button class="btn" data-nav="1">↓</button>
        <button class="btn" id="x">✕</button>
      </div>
    </div>
    <div class="ib">
      <div class="box">
        <h4>Наименования (отличия выделены)</h4>
        <div style="margin-bottom:6px"><span class="mut">ВОР:</span> ${da}</div>
        <div><span class="mut">ЛСР:</span> ${r.lsr ? db : 'подходящей расценки нет'}</div>
        ${r.code ? `<div class="mono" style="margin-top:6px;color:var(--ink)">${esc(r.code)}</div>` : ''}
      </div>
      <div class="box">
        <h4>Объёмы</h4>
        ${vol}
      </div>
      <div class="box">
        <h4>Сходство ${r.sim}% · порог ${TH}%</h4>
        <div class="thr"><i style="width:${Math.min(r.sim, 100)}%;background:${c}"></i><b style="left:${TH}%"></b></div>
        <div class="mut">${ok ? 'Выше порога.' : 'Ниже порога: пара предложена по шифру/объёму, нужно решение сметчика.'}</div>
        ${r.note ? `<div style="margin-top:6px;font-size:12px">${esc(r.note)}</div>` : ''}
      </div>
      ${cost}
    </div>
    <div class="if">
      ${!todo(r) && !d ? `
        <span class="mut">Авто · решение не требуется</span>
        <span style="flex:1"></span>
        <button class="btn" style="flex:none;color:#991B1B;border-color:#991B1B" data-a="no">✕ Переопределить <kbd>N</kbd></button>
      ` : d ? `
        <span class="pl ${d === 'yes' ? 's-ok' : 's-diff'}">${d === 'yes' ? '✓ Принято' : '↪ В правку'}</span>
        <span style="flex:1"></span>
        <button class="btn" data-a="u">↶ Отменить <kbd>Z</kbd></button>
      ` : `
        <button class="btn" style="color:#166534;border-color:#166534" data-a="yes">✓ Принять <kbd>Y</kbd></button>
        <button class="btn" style="color:#991B1B;border-color:#991B1B" data-a="no">✕ В правку <kbd>N</kbd></button>
      `}
    </div>
  `;
}

function renderFoot(v) {
  const t = ROWS.filter(todo).length;
  const n = ROWS.filter(r => todo(r) && S.dec[r.n]).length;
  const fl = ROWS.filter(r => !todo(r) && S.dec[r.n]).length;
  $('#foot').innerHTML = `
    <span><kbd>↑</kbd><kbd>↓</kbd> навигация · <kbd>Y</kbd> принять · <kbd>N</kbd> в правку · <kbd>Z</kbd> отмена · <kbd>/</kbd> поиск · <kbd>Esc</kbd> панель</span>
    <span style="flex:1"></span>
    <span>Показано <b>${v.length}</b> из ${ROWS.length}</span>
    ${fl ? `<span>Переопределено вручную: <b>${fl}</b></span>` : ''}
    <span>Решено <b>${n}</b> из <b>${t}</b></span>
    <span class="prog"><i style="width:${t ? (n / t * 100) : 100}%"></i></span>
  `;
}

function renderInfo() {
  const e = $('#info');
  if (S.fl !== 'need' || S.q || !ROWS.length) {
    e.innerHTML = '';
    return;
  }
  const c = f => ROWS.filter(r => r.st === f).length;
  e.innerHTML = `
    <div class="box" style="margin:8px 12px 0;display:flex;gap:10px;align-items:center;padding:5px 10px;background:#EFF7F2;border-color:#C8E6C9;flex-wrap:wrap">
      ✓ Сверено автоматически: <b>${c('ok') + c('unit')}</b> из ${ROWS.length} (точных ${c('ok')}, с пересчётом единиц ${c('unit')}). На ручной контроль: <b>${ROWS.filter(todo).length}</b>.
      <button class="btn" id="showAll">Показать все ${ROWS.length}</button>
    </div>
  `;
}

function render(sc) {
  renderInfo();
  renderChips();
  renderHead();
  const v = renderTable();
  $('#insp').classList.toggle('hide', !S.open);
  if (S.open) renderInsp(v);
  renderFoot(v);
  $('#bTog').classList.toggle('p', S.open);
  if (sc) document.querySelector('tr.sel')?.scrollIntoView({ block: 'nearest' });
}

let tt;
function toast(m) {
  const t = $('#toast');
  if (!t) return;
  t.textContent = m;
  t.classList.add('on');
  clearTimeout(tt);
  tt = setTimeout(() => t.classList.remove('on'), 2200);
}

function decide(n, act) {
  const r = ROWS.find(x => x.n === n);
  if (!r || S.dec[n] || (!todo(r) && act !== 'no')) return;
  const v = visible();
  const i = v.findIndex(x => x.n === n);
  const nx = !todo(r) ? null : [...v.slice(i + 1), ...v.slice(0, Math.max(i, 0))].find(x => x.n !== n && need(x));
  S.dec[n] = act;
  S.hist.push(n);
  S.sel = nx ? nx.n : n;
  render(true);
  toast(`#${n}: ${act === 'yes' ? 'принято' : 'в правку'} · Z — отменить`);
}

function undo(n) {
  if (n == null) n = S.hist.pop();
  else S.hist = S.hist.filter(x => x !== n);
  if (n == null) return toast('Нечего отменять');
  delete S.dec[n];
  S.sel = n;
  render(true);
  toast(`#${n}: решение отменено`);
}

function move(d) {
  const v = visible();
  if (!v.length) return;
  let i = v.findIndex(r => r.n === S.sel);
  i = Math.max(0, Math.min(v.length - 1, i < 0 ? 0 : i + d));
  S.sel = v[i].n;
  S.open = true;
  render(true);
}

const toggle = f => { S.open = (f === undefined ? !S.open : f); render(); };
const first = () => { const v = visible(); if (v.length && !v.some(r => r.n === S.sel)) S.sel = v[0].n; };

// ==================== ОБРАБОТЧИКИ СОБЫТИЙ ТАБЛИЦЫ И ИНСПЕКТОРА ====================
$('#tb').onclick = e => {
  const tr = e.target.closest('tr[data-n]');
  if (!tr) return;
  const n = +tr.dataset.n;
  const b = e.target.closest('[data-a]');
  if (b) {
    b.dataset.a === 'u' ? undo(n) : decide(n, b.dataset.a);
    return;
  }
  S.sel = n;
  S.open = true;
  render();
};

$('#insp').onclick = e => {
  const b = e.target.closest('button');
  if (!b) return;
  if (b.dataset.nav) move(+b.dataset.nav);
  else if (b.id === 'x') toggle(false);
  else if (b.dataset.a) b.dataset.a === 'u' ? undo(S.sel) : decide(S.sel, b.dataset.a);
};

$('#chips').onclick = e => {
  const b = e.target.closest('[data-f]');
  if (!b) return;
  S.fl = b.dataset.f;
  first();
  render(true);
};

$('#risk').onclick = () => {
  if (S.fl === 'risk') {
    S.fl = 'need';
    S.sort = PRE.n;
  } else {
    S.fl = 'risk';
    S.sort = PRE.risk;
  }
  $('#sortSel').value = S.fl === 'risk' ? 'risk' : 'n';
  first();
  render(true);
};

$('#sortSel').onchange = e => {
  if (e.target.value) {
    S.sort = PRE[e.target.value].map(x => ({ ...x }));
    render();
  }
};

$('#hd').onclick = e => {
  const th = e.target.closest('th[data-k]');
  if (!th) return;
  const k = th.dataset.k;
  const i = S.sort.findIndex(s => s.k === k);
  const df = k === 'risk' ? -1 : 1;
  if (e.shiftKey) {
    if (i < 0) S.sort.push({ k, d: df });
    else S.sort[i].d *= -1;
  } else {
    S.sort = [{ k, d: i >= 0 ? -S.sort[i].d : df }];
  }
  $('#sortSel').value = '';
  render();
};

$('#q').oninput = e => { S.q = e.target.value; render(); };
$('#bTog').onclick = () => toggle();
$('#info').onclick = e => { if (e.target.id === 'showAll') { S.fl = 'all'; first(); render(true); } };

// ==================== МОДАЛЬНЫЕ ОКНА ====================
const openM = id => $(id)?.classList.add('on');
const closeM = () => $$('.ov.on').forEach(m => m.classList.remove('on'));

$('#bUp').onclick = () => openM('#mUp');
$('#w-thr').onchange = e => {
  const v = Math.max(20, Math.min(95, +e.target.value || 55));
  e.target.value = v;
  TH = v;
  render();
  toast('Порог сходства: ' + v + '%');
};

$$('.ov').forEach(m => m.addEventListener('click', e => {
  if (e.target === m || e.target.hasAttribute('data-close')) closeM();
}));

// ==================== ЭКСПОРТ CSV ====================
$('#bCsv').onclick = () => {
  if (!ROWS.length) return toast('Нет данных для экспорта в CSV');
  const h = ['№', 'ВОР', 'ЛСР', 'Шифр', 'Объём ВОР', 'Объём ЛСР', 'Ед.', 'Статус', 'Сходство %', 'Риск ₽', 'Решение'];
  const rows = ROWS.map(r => [
    r.n,
    r.vor,
    r.lsr || '',
    r.code || '',
    r.vv,
    r.lv ?? '',
    r.u || '',
    LAB(r),
    r.sim,
    r.risk || 0,
    todo(r) ? (S.dec[r.n] === 'yes' ? 'Принято' : S.dec[r.n] === 'no' ? 'В правку' : 'Ждёт') : 'Авто'
  ]);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob(['\ufeff' + [h, ...rows].map(x => x.map(y => '"' + String(y).replace(/"/g, '""') + '"').join(';')).join('\r\n')], { type: 'text/csv' }));
  a.download = 'sverka_results.csv';
  a.click();
  toast('CSV файл выгружен');
};

// ==================== ОФИЦИАЛЬНЫЙ АКТ РАЗНОГЛАСИЙ (EXCEL) ====================
async function exportDiscrepancyAct() {
  if (!ROWS.length) return toast('Нет данных для формирования Акта разногласий');
  toast('Генерация Акта разногласий в Excel...');
  try {
    const payload = {
      title: currentProjectTitle || 'Сверка сметной документации',
      user_name: (currentUser && currentUser.full_name) || 'Инженер-сметчик',
      items: ROWS.map(r => ({
        n: r.n,
        vor: r.vor,
        lsr: r.lsr,
        code: r.code,
        vv: r.vv,
        lv: r.lv,
        u: r.u,
        pr: r.pr,
        risk: r.risk,
        unit_multiplier: r.unit_multiplier,
        status: LAB(r),
        decision: S.dec[r.n] || (todo(r) ? 'Ждёт решения' : 'auto'),
        note: r.note || ''
      }))
    };

    const res = await fetch('/api/export_discrepancy_act', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return toast('Ошибка формирования Акта: ' + (err.error || res.statusText));
    }

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'Акт_разногласий_СверкаСмет.xlsx';
    a.click();
    URL.revokeObjectURL(url);
    toast('✅ Акт разногласий (Excel) успешно сформирован!');
  } catch (err) {
    toast('Ошибка экспорта: ' + err.message);
  }
}
$('#bAct').onclick = exportDiscrepancyAct;

// ==================== КЛАВИАТУРНЫЙ КОНВЕЙЕР (HARDWARE CODE) ====================
addEventListener('keydown', e => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const t = e.target;
  if (t.closest && t.closest('input,select,textarea')) {
    if (e.key === 'Escape') t.blur();
    return;
  }
  if (document.querySelector('.ov.on')) {
    if (e.key === 'Escape') closeM();
    return;
  }
  const c = e.code;
  if (c === 'ArrowDown' || c === 'KeyJ') {
    e.preventDefault();
    move(1);
  } else if (c === 'ArrowUp' || c === 'KeyK') {
    e.preventDefault();
    move(-1);
  } else if (c === 'KeyY') {
    if (S.sel != null) decide(S.sel, 'yes');
  } else if (c === 'KeyN') {
    if (S.sel != null) decide(S.sel, 'no');
  } else if (c === 'KeyZ') {
    undo();
  } else if (c === 'Slash') {
    e.preventDefault();
    $('#q').focus();
  } else if (e.key === 'Escape') {
    toggle();
  }
});

// ==================== СОХРАНЕНИЕ В БАЗУ POSTGRESQL ====================
async function saveCurrentProjectToDB() {
  if (!ROWS.length) return toast('Нет данных для сохранения');
  const bSave = $('#bSave');
  bSave.disabled = true;
  bSave.textContent = 'Сохранение...';

  const ri = riskInfo();
  const payload = {
    title: currentProjectTitle || 'Сверка сметной документации',
    object_name: currentProjectTitle,
    vor_filename: activePreset ? `${activePreset}_vor.xlsx` : 'vor.xlsx',
    lsr_filename: activePreset ? `${activePreset}_lsr.xlsx` : 'lsr.xlsx',
    total_positions: ROWS.length,
    matched_count: ROWS.filter(r => !todo(r)).length,
    discrepancy_count: ROWS.filter(todo).length,
    total_financial_risk: ri.sum,
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
      toast(`✅ Проект сохранён в истории (ID #${data.project.id})!`);
      currentProjectId = data.project.id;
    } else {
      toast('Ошибка сохранения: ' + (data.error || 'Неизвестная ошибка'));
    }
  } catch (e) {
    toast('Ошибка связи с сервером: ' + e.message);
  } finally {
    bSave.disabled = false;
    bSave.textContent = '💾 Сохранить';
  }
}
$('#bSave').onclick = saveCurrentProjectToDB;

// ==================== ИСТОРИЯ ПРОВЕРОК ====================
async function openHistoryModal() {
  openM('#mHist');
  const histBody = $('#histBody');
  histBody.innerHTML = '<div class="mut">Загрузка сохранённых проверок из базы...</div>';
  try {
    const res = await fetch('/api/projects');
    const data = await res.json();
    if (!data.projects || !data.projects.length) {
      histBody.innerHTML = '<div class="mut">Пока нет сохранённых проверок. Запустите сверку и нажмите «💾 Сохранить».</div>';
      return;
    }
    histBody.innerHTML = `
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Наименование объекта</th>
            <th>Дата</th>
            <th>Позиций</th>
            <th>Сверено</th>
            <th>Финансовый риск</th>
            <th>Действие</th>
          </tr>
        </thead>
        <tbody>
          ${data.projects.map(p => `
            <tr>
              <td class="mono"><b>#${p.id}</b></td>
              <td><b>${esc(p.title)}</b></td>
              <td class="mut">${esc(p.created_at)}</td>
              <td>${p.total_positions}</td>
              <td style="color:var(--ok);font-weight:600;">${p.matched_count}</td>
              <td class="mono" style="color:var(--diff);font-weight:600;">${p.total_financial_risk > 0 ? fm(p.total_financial_risk) + ' ₽' : '0 ₽'}</td>
              <td><button class="btn btn-sm" onclick="loadProjectFromDB(${p.id})">Открыть</button></td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  } catch (e) {
    histBody.innerHTML = `<div style="color:var(--bad)">Ошибка чтения архива: ${esc(e.message)}</div>`;
  }
}
$('#bHist').onclick = openHistoryModal;

async function loadProjectFromDB(id) {
  closeM();
  try {
    const res = await fetch(`/api/projects/${id}`);
    const data = await res.json();
    if (!res.ok || data.error) return toast('Ошибка загрузки проекта: ' + (data.error || ''));

    currentProjectTitle = data.title;
    currentProjectId = data.id;
    ROWS = (data.items || []).map(it => {
      const item = {
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
      };
      classifyItem(item);
      return item;
    });

    S.dec = {};
    (data.items || []).forEach(it => {
      if (it.decision) S.dec[it.n] = it.decision;
    });

    $('#files-lbl').textContent = `${data.title} (#${data.id}) ▾`;
    first();
    S.sel = S.sel ?? visible()[0]?.n;
    render(true);
    toast(`Проект #${data.id} «${data.title}» загружен!`);
  } catch (e) {
    toast('Ошибка: ' + e.message);
  }
}

// ==================== ВЫПОЛНЕНИЕ СВЕРКИ ЧЕРЕЗ API ====================
function showErrorModal(data) {
  const m = $('#error-modal');
  if (!m) return toast(data.error_message || data.error || 'Ошибка сверки');
  $('#err-modal-title').textContent = data.error_title || 'Не удалось распознать документ';
  $('#err-modal-msg').textContent = data.error_message || data.error || 'Файл не содержит ожидаемой структуры сметной документации.';
  const detBox = $('#err-modal-details-box');
  if (data.error_details) {
    detBox.textContent = data.error_details;
    detBox.style.display = 'block';
  } else {
    detBox.style.display = 'none';
  }
  $('#err-modal-hint').textContent = data.error_hint || 'Убедитесь, что загружаете корректную ведомость объёмов работ (ВОР) и смету (по Методике 421/пр) в формате .xlsx.';
  m.classList.add('on');
}

async function runCompare() {
  const mode = $('#w-mode').value;
  const thr = $('#w-thr').value;
  const fVor = $('#f-vor').files[0];
  const fLsr = $('#f-lsr').files[0];

  const guard = $('#w-guard-banner');
  if (guard) { guard.style.display = 'none'; guard.textContent = ''; }

  if (!activePreset && (!fVor || !fLsr)) {
    return toast('Пожалуйста, выберите оба файла (ВОР и ЛСР) или выберите демонстрационный комплект');
  }

  const btn = $('#btn-compare');
  const load = $('#w-loading');
  btn.disabled = true;
  load.style.display = 'inline-flex';

  const fd = new FormData();
  fd.append('mode', mode);
  fd.append('threshold', (parseFloat(thr) / 100).toFixed(2));
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

    // Заполняем ROWS
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

      const vv = (r['ВОР: количество'] != null && r['ВОР: количество'] !== '') ? parseFloat(r['ВОР: количество']) : null;
      const lv = (r['ЛСР: количество'] != null && r['ЛСР: количество'] !== '') ? parseFloat(r['ЛСР: количество']) : null;
      const pr = (r['unit_price'] != null && r['unit_price'] !== '') ? parseFloat(r['unit_price']) : null;
      let risk = 0;
      if (r['financial_risk'] != null && r['financial_risk'] !== '') {
        risk = Math.round(parseFloat(r['financial_risk']));
      } else if (vv != null && lv != null && vv !== lv && pr != null && pr > 0) {
        risk = Math.round(Math.abs(lv - vv) * pr);
      }

      const item = {
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
      classifyItem(item);
      return item;
    });

    S.dec = {};
    S.fl = 'need';
    first();
    S.sel = S.sel ?? visible()[0]?.n;
    S.open = true;

    const vorName = fVor ? fVor.name : (
      activePreset === 'set1' ? 'ВОР_Дворец.xlsx' :
      activePreset === 'crystal' ? 'ВОР_Кристалл_освещение.xlsx' :
      activePreset === 'kaluga' ? 'ВОР_Кабинеты_1этаж.xlsx' :
      activePreset === 'set2' ? 'ВОР_Помещение_163.xlsx' : `${activePreset || 'ВОР'}.xlsx`
    );
    const lsrName = fLsr ? fLsr.name : (
      activePreset === 'set1' ? 'ЛСР_Дворец_421пр.xlsx' :
      activePreset === 'crystal' ? 'ЛСР_Кристалл_освещение.xlsx' :
      activePreset === 'kaluga' ? 'ЛСР_Кабинеты_1этаж.xlsx' :
      activePreset === 'set2' ? 'ЛСР_Помещение_163.xlsx' : `${activePreset || 'ЛСР'}.xlsx`
    );
    $('#files-lbl').textContent = `${vorName} · ${ROWS.length} → ${lsrName} ▾`;

    closeM();
    render(true);
    toast(`Сверка завершена: сопоставлено ${ROWS.length} позиций`);
  } catch (err) {
    toast('Сетевая ошибка: ' + err.message);
  } finally {
    btn.disabled = false;
    load.style.display = 'none';
  }
}

// ==================== ПРЕСЕТЫ ====================
function loadPreset(key, btnEl) {
  activePreset = key;
  $('#f-vor').value = '';
  $('#f-lsr').value = '';
  $$('.preset-pill').forEach(b => b.classList.remove('active'));
  if (btnEl) btnEl.classList.add('active');

  if (key === 'set1') currentProjectTitle = 'Комплект 1 · Дворец молодёжи (86 поз.)';
  else if (key === 'crystal') currentProjectTitle = 'Комплект 2 · СФР «Кристалл» (137 поз.)';
  else if (key === 'kaluga') currentProjectTitle = 'Комплект 3 · Ремонт кабинетов (534 поз.)';
  else if (key === 'set2') currentProjectTitle = 'Комплект 4 · Помещение 163 (83 поз.)';

  runCompare();
}

$('#f-vor').addEventListener('change', () => {
  activePreset = null;
  $$('.preset-pill').forEach(b => b.classList.remove('active'));
});
$('#f-lsr').addEventListener('change', () => {
  activePreset = null;
  $$('.preset-pill').forEach(b => b.classList.remove('active'));
});

// ==================== БЕНЧМАРК (ВКР) ====================
function openBenchmarkModal() { openM('#modal-benchmark'); }
$('#btn-benchmark').onclick = openBenchmarkModal;

async function runBenchmark() {
  const noise = $('#b-noise').value;
  const load = $('#b-loading');
  const resBox = $('#benchmark-results');
  const tbody = $('#benchmark-tbody');

  load.style.display = 'inline';
  try {
    const res = await fetch(`/api/benchmark?noise=${noise}`);
    const data = await res.json();
    load.style.display = 'none';
    if (!res.ok || data.error) return toast('Ошибка: ' + (data.error || ''));

    resBox.style.display = 'block';
    tbody.innerHTML = (data.methods || []).map(m => `
      <tr>
        <td><b>${esc(m.name)}</b></td>
        <td>${(m.precision * 100).toFixed(1)}%</td>
        <td>${(m.recall * 100).toFixed(1)}%</td>
        <td><b style="color:var(--ok);">${m.f1.toFixed(3)}</b></td>
        <td>${(m.qty_accuracy * 100).toFixed(1)}%</td>
      </tr>
    `).join('');
  } catch (e) {
    load.style.display = 'none';
    toast('Ошибка: ' + e.message);
  }
}

// ==================== АВТОРИЗАЦИЯ И ИНИЦИАЛИЗАЦИЯ ====================
async function checkAuth() {
  try {
    const res = await fetch('/api/auth/me');
    const data = await res.json();
    if (data.user) {
      currentUser = data.user;
      $('#user-name').textContent = data.user.full_name;
      const roleBadge = $('#user-role-badge');
      if (data.user.role === 'lead') {
        roleBadge.textContent = '👤 Руководитель';
      } else if (data.user.role === 'admin') {
        roleBadge.textContent = '👤 Администратор';
      } else {
        roleBadge.textContent = '👤 Сметчик';
      }

      const isLead = (data.user.role === 'lead');
      const bBtn = $('#btn-benchmark');
      if (bBtn) bBtn.style.display = isLead ? 'inline-flex' : 'none';
      const pBar = $('#presets-bar');
      if (pBar) pBar.style.display = isLead ? 'flex' : 'none';

      // Автоматическая загрузка эталонного комплекта №1 для lead / демонстрации
      if (isLead && !ROWS.length) {
        activePreset = 'set1';
        currentProjectTitle = 'Комплект 1 · Дворец молодёжи (86 поз.)';
        runCompare();
      }
    } else {
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

window.exportDecisions = () => ROWS.map(r => ({
  n: r.n,
  decision: S.dec[r.n] === 'yes' ? 'confirmed' : S.dec[r.n] === 'no' ? 'rejected' : 'auto',
  status: r.st,
  unit_multiplier: r.st === 'unit' ? mult(r) : null,
  financial_risk: r.risk || 0
}));

// Старт
checkAuth();
render();
