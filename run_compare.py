"""Основной сценарий сопоставления произвольной пары ВОР и ЛСР с формированием объяснимого отчета.

Запуск:
    python run_compare.py "ВОР.xlsx" "ЛСР.xlsx" [результат.csv] [--llm]

--llm: спорные пары дополнительно уточняет YandexGPT (нужны переменные окружения
YANDEX_API_KEY и YANDEX_FOLDER_ID, см. llm_resolver.py).
"""
import sys
import csv
from collections import Counter
from pathlib import Path
from typing import List, Dict, Any

from parsers import parse_vor, parse_lsr, Item
import match

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

FIELDS = [
    'ВОР №', 'ВОР строка', 'ВОР: наименование', 'ВОР: единица', 'ВОР: количество',
    'ЛСР №', 'ЛСР строка', 'ЛСР шифр', 'ЛСР: наименование', 'ЛСР: единица', 'ЛСР: количество',
    'Текстовое сходство', 'Уверенность', 'Результат алгоритма', 'Причина решения и расхождения',
    'Коллизия (неоднозначность)', 'Решение ИИ-арбитра', 'Исходный класс', 'Верхний статус',
    'Предупреждение о формулировке', 'Причина предупреждения', 'Условие предупреждения'
]


def _warn_duplicates(items: List[Item], title: str):
    dups = [n for n, c in Counter(str(x.num) for x in items).items() if c > 1]
    if dups:
        print(f"ВНИМАНИЕ: в документе {title} повторяются номера позиций: {', '.join(dups[:8])}"
              f"{'...' if len(dups) > 8 else ''}. Использована уникальная идентификация по строкам.")


def _resolve_file(path_str: str, default_folder: str = "") -> Path:
    p = Path(path_str)
    if p.exists():
        return p
    if default_folder:
        alt = Path(default_folder) / path_str
        if alt.exists():
            return alt
    return p


def main():
    use_llm_arbitration = '--llm' in sys.argv
    use_llm_weak = '--llm-weak' in sys.argv
    use_llm_only = '--llm-only' in sys.argv
    use_llm = use_llm_arbitration or use_llm_weak or use_llm_only

    argv = [a for a in sys.argv if a not in ('--llm', '--llm-weak', '--llm-only')]
    if len(argv) < 3 or len(argv) > 4:
        print(__doc__)
        sys.exit(2)

    vor_path = _resolve_file(argv[1], "data")
    lsr_path = _resolve_file(argv[2], "data")
    default_out = 'results/comparison_results.csv' if Path('results').exists() else 'comparison_results.csv'
    out_arg = argv[3] if len(argv) == 4 else default_out
    out_path = Path(out_arg)
    if not out_path.parent.exists():
        out_path.parent.mkdir(parents=True, exist_ok=True)

    if not vor_path.exists():
        sys.exit(f'Не найден файл ВОР: {vor_path}')
    if not lsr_path.exists():
        sys.exit(f'Не найден файл ЛСР: {lsr_path}')

    print(f"Чтение файлов:\n  ВОР: {vor_path}\n  ЛСР: {lsr_path}")
    try:
        vor = parse_vor(str(vor_path))
        lsr = parse_lsr(str(lsr_path))
    except ValueError as e:
        sys.exit(f'Ошибка структуры данных: {e}')
    except Exception as e:
        sys.exit(f'Не удалось открыть файл ({type(e).__name__}: {e}). Требуется формат .xlsx.')

    print(f"  Прочитано позиций ВОР: {len(vor)}")
    print(f"  Прочитано позиций ЛСР: {len(lsr)}")

    _warn_duplicates(vor, 'ВОР')
    _warn_duplicates(lsr, 'ЛСР')

    # Запуск сопоставления
    is_compat, overlap_ratio, compat_msg = match.check_document_compatibility(vor, lsr)
    if not is_compat:
        print(f"\n[ПРЕДОХРАНИТЕЛЬ СОВМЕСТИМОСТИ ДОКУМЕНТОВ]:")
        print(f"  {compat_msg}")
        if use_llm:
            print("  ВЫЗОВ ИИ ЗАБЛОКИРОВАН: предотвращен нецелевой расход бюджета токенов на несогласованные документы.")
            use_llm = False

    if use_llm_only:
        from llm_resolver import model_only_results
        results = model_only_results(vor, lsr)
    else:
        results = match.match(vor, lsr, thr=0.50, min_text_threshold=0.20)

    # Статистика неоднозначностей перед вызовом ИИ
    ambig_items = [r for r in results if r.get("is_ambiguous")]
    print(f"\nДетектор неоднозначностей SmartMatcher:")
    print(f"  Выявлено неоднозначных позиций: {len(ambig_items)}")
    breakdown = {}
    for r in ambig_items:
        t = r.get("ambiguity_type", "other")
        breakdown[t] = breakdown.get(t, 0) + 1
    for k, cnt in breakdown.items():
        print(f"    - {k}: {cnt}")

    if use_llm:
        from llm_resolver import YandexClient, resolve
        try:
            client = YandexClient()
        except RuntimeError as e:
            sys.exit(str(e))
        cache = 'results/llm_cache.json' if Path('results').exists() else 'llm_cache.json'
        llm_mode = "weak_only" if use_llm_weak else ("model_only" if use_llm_only else "arbitration")
        print(f"\nЗапуск ИИ-арбитра Алисы (режим: {llm_mode})...")
        results, st = resolve(results, vor, lsr, client, mode=llm_mode, cache_path=cache, verbose=True)
        print(f"  Обращений к модели: {st['calls']} (из кэша: {st['cache_hits']}), "
              f"проверено коллизий: {st['ambiguities_checked']}, "
              f"подтверждено пар: {st['confirmed']}, переназначено: {st['reassigned']}, "
              f"отклонено («нет в смете»): {st['rejected']}, время: {st['seconds']} с")
        if st.get("total_tokens"):
            in_t = st["input_tokens"]
            out_t = st["output_tokens"]
            tot_t = st["total_tokens"]
            cost_rub = (in_t / 1000.0) * 0.10 + (out_t / 1000.0) * 0.20
            print(f"  Фактический расход токенов: входящих={in_t:,}, исходящих={out_t:,}, суммарно={tot_t:,}")
            print(f"  Расчетная стоимость вызовов по тарифу Yandex AI: {cost_rub:.2f} руб.")

    rows: List[Dict[str, Any]] = []

    # Карты позиций для фоллбэка, если vor_item/lsr_item не переданы
    vor_by_num = {str(x.num): x for x in vor}
    lsr_by_num = {str(x.num): x for x in lsr}

    for r in results:
        # Прямое извлечение сопоставленных объектов исключает коллизии дубликатов номеров
        v = r.get('vor_item')
        l = r.get('lsr_item')

        if v is None and r.get('vor') is not None:
            v = vor_by_num.get(str(r.get('vor')))
        if l is None and r.get('lsr') is not None:
            l = lsr_by_num.get(str(r.get('lsr')))

        status = str(r.get('cls') or '')
        score = float(r.get('score', 0.0))
        text_sim = float(r.get('text_sim', 0.0))
        explanation = str(r.get('explanation') or '')

        rows.append({
            'ВОР №': v.num if v else '',
            'ВОР строка': v.row if v else (r.get('vor_row') or ''),
            'ВОР: наименование': v.name if v else '',
            'ВОР: единица': v.unit if v else '',
            'ВОР: количество': v.qty if v else '',
            'ЛСР №': l.num if l else '',
            'ЛСР строка': l.row if l else (r.get('lsr_row') or ''),
            'ЛСР шифр': l.code if l else '',
            'ЛСР: наименование': l.name if l else '',
            'ЛСР: единица': l.unit if l else '',
            'ЛСР: количество': l.qty if l else '',
            'Текстовое сходство': round(text_sim, 4),
            'Уверенность': round(score, 4),
            'Результат алгоритма': status,
            'Верхний статус': r.get('upper_status', match.upper_status(
                status, r.get('formulation_warning', False)
            )),
            'Предупреждение о формулировке': bool(r.get('formulation_warning', False)),
            'Причина предупреждения': r.get('formulation_warning_reason', ''),
            'Условие предупреждения': '; '.join(r.get('formulation_warning_conditions', [])),
            'Причина решения и расхождения': explanation,
            'Коллизия (неоднозначность)': r.get('conflict_reason', ''),
            'Решение ИИ-арбитра': r.get('ai_decision', 'Не привлекался'),
            'Исходный класс': status,
        })

    try:
        with out_path.open('w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS, delimiter=';')
            writer.writeheader()
            writer.writerows(rows)
    except PermissionError:
        sys.exit(f'Не удалось записать файл {out_path}: он открыт в другой программе (Excel). Закройте его и повторите запуск.')

    print(f"\nСопоставление успешно завершено:")
    print(f"  Всего сформировано записей: {len(rows)}")
    print(f"  Результат сохранен в CSV: {out_path.resolve()}")
    print("  Отчет содержит детальные технические объяснения каждого решения.")


if __name__ == '__main__':
    main()
