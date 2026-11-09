"""Выгружает запросы арбитража (как их формирует прототип) вместе с эталоном.

Запуск из корня проекта sverka:
    python llmbench/export_tasks.py data/ВОР.xlsx data/ЛСР.xlsx llmbench/tasks_set1.json

Эталон: колонка «№ в ЛСР» в ВОР (поле Item.ref). Модель ничего не вызывается.
"""
import sys, os, json, types
sys.path.insert(0, os.getcwd())
try:
    import openai  # noqa
except ImportError:                      # экспорт не требует настоящего openai
    m = types.ModuleType('openai'); m.OpenAI = lambda **k: None; sys.modules['openai'] = m
import tempfile
from parsers import parse_vor, parse_lsr
import match
import llm_resolver as lr

vor_path, lsr_path, out = sys.argv[1:4]
POOL_WORK = len(sys.argv) > 4 and sys.argv[4] == 'work'   # вариант Б: для «Монтаж…» показать все строки-работы (ГЭСН/ФЕР/ТЕР)
V, L = parse_vor(vor_path), parse_lsr(lsr_path)
R = match.match(V, L, thr=0.50, min_text_threshold=0.20)
lnums = {str(x.num) for x in L}

rec = []
orig_build = lr.build_prompt
def spy(v, cands, cur_cand=None, conflict_reason="", ambiguity_type=""):
    p = orig_build(v=v, cands=cands, cur_cand=cur_cand, conflict_reason=conflict_reason, ambiguity_type=ambiguity_type)
    rec.append(dict(vor_num=str(v.num), vor_name=v.name, vor_ref=str(v.ref).strip(),
                    cand_nums=[str(c.num) for c in cands], has_current=cur_cand is not None,
                    conflict=conflict_reason, prompt=p))
    return p
lr.build_prompt = spy

class Dummy:
    model = 'dummy'
    def ask(self, s, u): return '{"action":"CONFIRM","candidate":1,"confidence":0.9,"reason":"x"}'
lr.resolve(R, V, L, Dummy(), cache_path=tempfile.mktemp(suffix='.json'), verbose=False)

# группы эквивалентных строк ЛСР (одинаковые название, единица, объём): любая из них верна
groups = {}
for x in L:
    groups.setdefault((x.name.strip().lower(), x.unit.strip().lower(), round(x.qty, 6) if x.qty is not None else None), []).append(str(x.num))
eq = {n: set(g) for g in groups.values() for n in g}

if POOL_WORK:
    # вариант Б: берём позиции, начинающиеся с «Монтаж/Установка/Демонтаж», и показываем модели все строки-работы
    work = [l for l in L if (l.code or '').upper().startswith(('ГЭСН', 'ФЕР', 'ТЕР'))]
    rec = []
    for v in V:
        if v.name.strip().lower().startswith(('монтаж', 'установка', 'демонтаж')):
            spy(v, work)
    for r in rec: r['has_current'] = False
tasks = []
for i, r in enumerate(rec, 1):
    truth = r['vor_ref'] if r['vor_ref'] in lnums else None
    ok = sorted(eq.get(truth, {truth}) & set(r['cand_nums'])) if truth else []
    r.update(id=i, system=lr.SYSTEM_PROMPT_ARBITRATION, truth_lsr=truth,
             ok_idx=[r['cand_nums'].index(n) + 1 for n in ok])
    tasks.append(r)
json.dump(tasks, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
n_t = sum(1 for t in tasks if t['truth_lsr'])
n_in = sum(1 for t in tasks if t['ok_idx'])
print(f"запросов: {len(tasks)}; с эталоном в ВОР: {n_t}; из них верный ответ есть среди кандидатов: {n_in}; "
      f"без эталона (ожидается отказ): {len(tasks)-n_t}; эталон есть, но кандидатов нет: {n_t-n_in}")
