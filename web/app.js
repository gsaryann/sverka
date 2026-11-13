/* Клиентская логика СверкаСмет (SmartMatcher) */

let activePreset = null;
let tableData = [];

// Состояние сортировки
let sortCol = 'vor_num';
let sortAsc = true;

function switchTab(tabId, el) {
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.getElementById(tabId).classList.add('active');
  el.classList.add('active');
}

// Сброс выбора при ручной загрузке файлов
document.getElementById('f-vor').addEventListener('change', () => { 
  activePreset = null; 
  document.getElementById('p-label').textContent = ''; 
});
document.getElementById('f-lsr').addEventListener('change', () => { 
  activePreset = null; 
  document.getElementById('p-label').textContent = ''; 
});

function loadPreset(key) {
  activePreset = key;
  document.getElementById('f-vor').value = '';
  document.getElementById('f-lsr').value = '';
  document.getElementById('p-label').textContent = key === 'set1' ? 'выбран Комплект 1' : 'выбран Комплект 2';
  const guard = document.getElementById('w-guard-banner');
  if (guard) guard.style.display = 'none';
}

// ================== ОПРЕДЕЛЕНИЕ СПОРНОСТИ (ПО BPMN) ==================
function isRowAmbiguous(r) {
  if (r.is_ambiguous !== undefined && r.is_ambiguous !== null) {
    return Boolean(r.is_ambiguous);
  }
  const isAi = (r['Причина решения и расхождения'] || '').includes('Алиса');
  const sim = parseFloat(r['Текстовое сходство'] || 0);
  const st = r['Результат алгоритма'] || '';

  if (r['ЛСР №']) {
    if (isAi || sim < 0.40 || st.includes('Кандидат') || r['Коллизия (неоднозначность)']) return true;
  }
  if (st === 'Расхождение единиц' || st.includes('характеристик') || st === 'Нет в рассматриваемой смете') return true;

  return false;
}

// ================== РАБОЧАЯ СВЕРКА ==================
async function runCompare() {
  const mode = document.getElementById('w-mode').value;
  const thr = document.getElementById('w-thr').value;
  const fVor = document.getElementById('f-vor').files[0];
  const fLsr = document.getElementById('f-lsr').files[0];

  const guard = document.getElementById('w-guard-banner');
  if (guard) {
    guard.style.display = 'none';
    guard.textContent = '';
  }

  if (!activePreset && (!fVor || !fLsr)) {
    alert('Пожалуйста, выберите оба файла или кликните быстрый тестовый комплект.');
    return;
  }

  const btn = document.getElementById('btn-compare');
  const load = document.getElementById('w-loading');
  btn.disabled = true;
  load.style.display = 'inline';
  load.textContent = 'SmartMatcher выполняет экспресс-сопоставление...';

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
    const resp = await fetch('/api/compare_stream', { method: 'POST', body: fd });
    if (!resp.ok) {
      const errJson = await resp.json().catch(() => ({}));
      alert('Ошибка: ' + (errJson.error || `HTTP ${resp.status}`));
      return;
    }

    if (!resp.body || !resp.body.getReader) {
      // Фолбэк на синхронный метод, если среда не поддерживает ReadableStream
      const syncResp = await fetch('/api/compare', { method: 'POST', body: fd });
      const data = await syncResp.json();
      if (!syncResp.ok || data.error) {
        alert('Ошибка: ' + (data.error || 'Не удалось выполнить'));
        return;
      }
      if (data.warning && guard) {
        guard.textContent = '⚠️ ' + data.warning;
        guard.style.display = 'block';
      }
      tableData = data.rows || [];
      renderSummary(data.stats, mode);
      sortCol = 'vor_num';
      sortAsc = true;
      applyFiltersAndSort();
      document.getElementById('w-summary').style.display = 'flex';
      document.getElementById('w-filter-bar').style.display = 'flex';
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split('\n\n');
      buffer = lines.pop(); // неполный остаток в конце

      for (const block of lines) {
        for (const line of block.split('\n')) {
          if (!line.startsWith('data: ')) continue;
          const jsonStr = line.slice(6).trim();
          if (!jsonStr) continue;

          let msg;
          try { msg = JSON.parse(jsonStr); } catch (e) { continue; }

          if (msg.warning && guard) {
            guard.textContent = '⚠️ ' + msg.warning;
            guard.style.display = 'block';
          }

          if (msg.type === 'init') {
            tableData = msg.rows || [];
            renderSummary(msg.stats || {}, mode);
            sortCol = 'vor_num';
            sortAsc = true;
            applyFiltersAndSort();
            document.getElementById('w-summary').style.display = 'flex';
            document.getElementById('w-filter-bar').style.display = 'flex';

            if (msg.needs_llm) {
              load.textContent = `SmartMatcher готов (0.05 с). ИИ-арбитр анализирует ${msg.ambig_count} спорных позиций...`;
            } else {
              load.textContent = '✓ Сопоставление SmartMatcher завершено!';
              setTimeout(() => {
                if (load.textContent.includes('завершено')) {
                  load.style.display = 'none';
                }
              }, 2000);
            }
          } else if (msg.type === 'progress') {
            load.textContent = `🤖 Алиса арбитраж: ${msg.done} из ${msg.total} (${msg.percent}%) — ${msg.item_name || ''}...`;
          } else if (msg.type === 'done') {
            tableData = msg.rows || [];
            renderSummary(msg.stats || {}, mode);
            applyFiltersAndSort();
            load.textContent = '✓ Сверка и арбитраж успешно завершены!';
            setTimeout(() => {
              if (load.textContent.includes('завершены')) {
                load.style.display = 'none';
              }
            }, 3000);
          } else if (msg.type === 'error') {
            alert('Ошибка сервера: ' + msg.error);
          }
        }
      }
    }
  } catch (err) {
    alert('Ошибка связи: ' + err.message);
  } finally {
    btn.disabled = false;
  }
}

function renderSummary(st, mode) {
  document.getElementById('ws-total').textContent = tableData.length;
  document.getElementById('ws-match').textContent = tableData.filter(r => (r['Результат алгоритма'] || '').startsWith('Совпало')).length;
  document.getElementById('ws-diff').textContent = tableData.filter(r => (r['Результат алгоритма'] || '').includes('Расхождение')).length;
  document.getElementById('ws-none').textContent = tableData.filter(r => (r['Результат алгоритма'] || '').startsWith('Нет в')).length;

  const ambigList = tableData.filter(r => isRowAmbiguous(r));
  const decidedCount = ambigList.filter(r => r['Статус решения сметчика'] === 'Подтверждено' || r['Статус решения сметчика'] === 'Отклонено').length;

  document.getElementById('ws-ambig').textContent = ambigList.length;
  document.getElementById('ws-decided').textContent = `${decidedCount} из ${ambigList.length}`;

  const aiBox = document.getElementById('ws-ai-box');
  if ((mode === 'hybrid' || mode === 'model_only') && st.llm_stats) {
    aiBox.style.display = 'inline';
    document.getElementById('ws-ai').textContent = st.llm_stats.accepted || 0;
  } else {
    aiBox.style.display = 'none';
  }
}

// ================== СОРТИРОВКА И ФИЛЬТРАЦИЯ ==================

function handleSort(columnKey) {
  if (sortCol === columnKey) {
    sortAsc = !sortAsc;
  } else {
    sortCol = columnKey;
    sortAsc = true;
  }
  applyFiltersAndSort();
}

function parseNum(val) {
  if (!val) return 99999999;
  const cleaned = String(val).replace(/[^0-9.]/g, '');
  const num = parseFloat(cleaned);
  return isNaN(num) ? 99999999 : num;
}

function applyFiltersAndSort() {
  const statusFilter = document.getElementById('flt-status').value;
  const simFilter = document.getElementById('flt-sim').value;
  const aiOnly = document.getElementById('flt-ai').checked;
  const query = document.getElementById('flt-search').value.toLowerCase().trim();

  // 1. Фильтрация
  const filtered = tableData.filter(r => {
    const st = r['Результат алгоритма'] || '';
    const isAmbig = isRowAmbiguous(r);
    const isDecided = (r['Статус решения сметчика'] === 'Подтверждено' || r['Статус решения сметчика'] === 'Отклонено');
    const isAi = (r['Причина решения и расхождения'] || '').includes('Алиса');
    const sim = parseFloat(r['Текстовое сходство'] || 0);

    // Фильтр по статусу
    if (statusFilter === 'ambig' && !isAmbig) return false;
    if (statusFilter === 'collision' && !r['Коллизия (неоднозначность)']) return false;
    if (statusFilter === 'diff' && !st.includes('Расхождение')) return false;
    if (statusFilter === 'match' && !st.startsWith('Совпало')) return false;
    if (statusFilter === 'missing' && !st.startsWith('Нет в')) return false;
    if (statusFilter === 'decided' && !isDecided) return false;

    // Фильтр по сходству
    if (simFilter === 'high' && sim < 0.80) return false;
    if (simFilter === 'mid' && (sim < 0.40 || sim >= 0.80)) return false;
    if (simFilter === 'low' && sim >= 0.40) return false;

    // Только ИИ
    if (aiOnly && !isAi) return false;

    // Текстовый поиск
    if (query) {
      const text = [
        r['ВОР №'], r['ВОР: наименование'], r['ЛСР №'], r['ЛСР шифр'],
        r['ЛСР: наименование'], r['Причина решения и расхождения'], st
      ].join(' ').toLowerCase();
      if (!text.includes(query)) return false;
    }

    return true;
  });

  // 2. Сортировка
  filtered.sort((a, b) => {
    let res = 0;
    if (sortCol === 'vor_num') {
      res = parseNum(a['ВОР №']) - parseNum(b['ВОР №']);
    } else if (sortCol === 'lsr_num') {
      res = parseNum(a['ЛСР №']) - parseNum(b['ЛСР №']);
    } else if (sortCol === 'vor_name') {
      res = (a['ВОР: наименование'] || '').localeCompare(b['ВОР: наименование'] || '', 'ru');
    } else if (sortCol === 'lsr_name') {
      res = (a['ЛСР: наименование'] || '').localeCompare(b['ЛСР: наименование'] || '', 'ru');
    } else if (sortCol === 'status') {
      res = (a['Результат алгоритма'] || '').localeCompare(b['Результат алгоритма'] || '', 'ru');
    } else if (sortCol === 'sim') {
      res = (parseFloat(a['Текстовое сходство'] || 0)) - (parseFloat(b['Текстовое сходство'] || 0));
    }
    return sortAsc ? res : -res;
  });

  // 3. Обновление индикаторов в шапке
  document.querySelectorAll('th.sortable').forEach(th => {
    th.classList.remove('sort-asc', 'sort-desc');
  });
  const currentTh = document.getElementById('th-' + sortCol);
  if (currentTh) {
    currentTh.classList.add(sortAsc ? 'sort-asc' : 'sort-desc');
  }

  document.getElementById('flt-count').textContent = `${filtered.length} из ${tableData.length}`;
  renderTable(filtered);
}

function resetFilters() {
  document.getElementById('flt-status').value = 'all';
  document.getElementById('flt-sim').value = 'all';
  document.getElementById('flt-ai').checked = false;
  document.getElementById('flt-search').value = '';
  sortCol = 'vor_num';
  sortAsc = true;
  applyFiltersAndSort();
}

function renderTable(rows) {
  const tbody = document.getElementById('w-tbody');
  tbody.innerHTML = '';

  if (!rows.length) {
    document.getElementById('w-empty').style.display = 'block';
    document.getElementById('w-empty').textContent = tableData.length 
      ? 'По выбранным фильтрам ничего не найдено.' 
      : 'Выберите файлы или нажмите тестовый комплект выше и нажмите «Сверить документы».';
    document.getElementById('w-table').style.display = 'none';
    return;
  }

  document.getElementById('w-empty').style.display = 'none';
  document.getElementById('w-table').style.display = 'table';

  rows.forEach((r) => {
    const tr = document.createElement('tr');
    const isAi = (r['Причина решения и расхождения'] || '').includes('Алиса');
    const aiTag = isAi ? '<span class="tag-ai">ИИ</span>' : '';
    const st = r['Результат алгоритма'];
    const isAmbig = isRowAmbiguous(r);
    const decision = r['Статус решения сметчика'] || 'Авто';

    let statusClass = 'st-none';
    if (decision === 'Подтверждено') statusClass = 'st-confirmed';
    else if (decision === 'Отклонено') statusClass = 'st-diff';
    else if (st.startsWith('Совпало')) statusClass = 'st-ok';
    else if (st.includes('объёма')) statusClass = 'st-qty';
    else if (st.includes('единиц')) statusClass = 'st-unit';

    const originalIndex = tableData.indexOf(r);

    // Формирование ячейки действия по BPMN:
    let actionCell = '';
    if (!isAmbig) {
      // Очевидная пара: сметчику подтверждать не нужно!
      actionCell = `<span style="color:#94a3b8; font-size:11px;">Авто</span>`;
    } else {
      // Спорная пара: требуется подтверждение сметчика!
      if (decision === 'Подтверждено') {
        actionCell = `
          <span class="st-confirmed" style="font-size:11px;">✓ Принято</span>
          <button class="btn-action" style="margin-left:3px;" onclick="handleRowAction(${originalIndex}, 'reset')">Снять</button>
        `;
      } else if (decision === 'Отклонено') {
        actionCell = `
          <span style="color:#dc2626; font-size:11px; font-weight:600;">✕ Отклонено</span>
          <button class="btn-action" style="margin-left:3px;" onclick="handleRowAction(${originalIndex}, 'reset')">Снять</button>
        `;
      } else {
        // Ожидает решения инженера (BPMN Слайд 12)
        actionCell = `
          <div style="display:flex; gap:3px; justify-content:center;">
            <button class="btn-action" style="color:#166534; font-weight:700;" onclick="handleRowAction(${originalIndex}, 'confirm')" title="Подтвердить совпадение">✓ Да</button>
            <button class="btn-action" style="color:#b91c1c;" onclick="handleRowAction(${originalIndex}, 'reject')" title="Отклонить: пары в смете нет">✕ Нет</button>
          </div>
        `;
      }
    }

    const secVor = r['ВОР раздел'] ? `<div class="sec-badge">${r['ВОР раздел']}</div>` : '';
    const secLsr = r['ЛСР раздел'] ? `<div class="sec-badge">${r['ЛСР раздел']}</div>` : '';
    const collisionBadge = r['Коллизия (неоднозначность)']
      ? `<div class="collision-box">⚡ <b>Коллизия:</b> ${r['Коллизия (неоднозначность)']}</div>`
      : '';
    const aiDecisionTag = (r['Решение ИИ-арбитра'] && r['Решение ИИ-арбитра'] !== 'Не привлекался' && r['Решение ИИ-арбитра'] !== 'Авто')
      ? `<div class="tag-ai-decision">🤖 ${r['Решение ИИ-арбитра']}</div>`
      : '';

    tr.innerHTML = `
      <td>${r['ВОР №'] || '-'}</td>
      <td>
        <div><b>${r['ВОР: наименование'] || '<span style="color:#888;">(нет в ВОР)</span>'}</b></div>
        ${r['ВОР: количество'] ? `<div style="color:#555; font-size:11px;">Объем: ${r['ВОР: количество']} ${r['ВОР: единица']} (стр. ${r['ВОР строка']})</div>` : ''}
        ${secVor}
      </td>
      <td>${r['ЛСР №'] || '-'}</td>
      <td><code>${r['ЛСР шифр'] || '-'}</code></td>
      <td>
        <div><b>${r['ЛСР: наименование'] || '<span style="color:#888;">(нет в смете)</span>'}</b></div>
        ${r['ЛСР: количество'] ? `<div style="color:#555; font-size:11px;">Объем: ${r['ЛСР: количество']} ${r['ЛСР: единица']} (стр. ${r['ЛСР строка']})</div>` : ''}
        ${secLsr}
      </td>
      <td class="${statusClass}">
        ${st} ${aiTag}
        ${aiDecisionTag}
      </td>
      <td>${Math.round((r['Текстовое сходство'] || 0) * 100)}%</td>
      <td style="color:#333;">
        <div>${r['Причина решения и расхождения']}</div>
        ${collisionBadge}
      </td>
      <td style="text-align: center; vertical-align: middle;">
        ${actionCell}
      </td>
    `;
    tbody.appendChild(tr);
  });
}

async function handleRowAction(rowIndex, action) {
  const row = tableData[rowIndex];
  if (!row) return;

  const resp = await fetch('/api/action_row', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ index: rowIndex, action: action })
  });

  const data = await resp.json();
  if (data.ok && data.row) {
    tableData[rowIndex] = data.row;
    renderSummary({}, document.getElementById('w-mode').value);
    applyFiltersAndSort();
  }
}


// ================== НАУЧНЫЙ ЭКСПЕРИМЕНТ (ВКР) ==================
async function runBenchmark() {
  const preset = document.getElementById('exp-preset').value;
  const shuffle = document.getElementById('chk-shuffle').checked;
  const stress = document.getElementById('chk-stress').checked;

  const btn = document.getElementById('btn-exp');
  const load = document.getElementById('exp-loading');
  btn.disabled = true;
  load.style.display = 'inline';

  try {
    const resp = await fetch('/api/benchmark', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset, shuffle, stress })
    });
    const data = await resp.json();
    if (!resp.ok || data.error) {
      alert('Ошибка: ' + (data.error || 'Сбой эксперимента'));
      return;
    }

    renderBenchmarkResults(data);
    document.getElementById('exp-results').style.display = 'block';
    if (data.warnings && data.warnings.length) {
      alert(data.warnings.join('\n'));
    }
  } catch (e) {
    alert('Ошибка эксперимента: ' + e.message);
  } finally {
    btn.disabled = false;
    load.style.display = 'none';
  }
}

function renderBenchmarkResults(data) {
  const tbody = document.getElementById('exp-tbody');
  tbody.innerHTML = '';

  data.methods.forEach(m => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><b>${m.name}</b></td>
      <td><span class="metric-badge">${(m.prec * 100).toFixed(1)}%</span></td>
      <td><span class="metric-badge">${(m.rec * 100).toFixed(1)}%</span></td>
      <td><span class="metric-badge" style="color:#2563eb;">${(m.f1 * 100).toFixed(1)}%</span></td>
      <td>${(m.cls_acc * 100).toFixed(1)}%</td>
      <td>P=${(m.nv_prec * 100).toFixed(0)}%, R=${(m.nv_rec * 100).toFixed(0)}%</td>
    `;
    tbody.appendChild(tr);
  });

  const confBody = document.getElementById('conf-tbody');
  confBody.innerHTML = '';
  (data.confusion || []).forEach(c => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${c.true_cls}</td>
      <td><b>${c.pred_cls}</b></td>
      <td style="text-align: right; font-weight: 700;">${c.count}</td>
    `;
    confBody.appendChild(tr);
  });
}
