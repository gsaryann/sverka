"""Экспериментальная оценка алгоритмов сопоставления ВОР и ЛСР.

Запуск:
    python run_baseline.py "ВОР.xlsx" "ЛСР.xlsx"
    python run_baseline.py --shuffle "ВОР.xlsx" "ЛСР.xlsx"
    python run_baseline.py --compare "ВОР.xlsx" "ЛСР.xlsx"
    python run_baseline.py --llm "ВОР.xlsx" "ЛСР.xlsx"         # код + YandexGPT
    python run_baseline.py --model-only "ВОР.xlsx" "ЛСР.xlsx"  # только модель
    python run_baseline.py --compare --llm "ВОР.xlsx" "ЛСР.xlsx"  # все варианты подряд
"""
import sys
import argparse
from pathlib import Path
from typing import List, Tuple

from parsers import parse_vor, parse_lsr
from perturb import make_set
import match
import baseline_legacy
from evaluate import evaluate

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def run_benchmark(sets: List[Tuple[str, str]], seeds=(1, 2, 3),
                  shuffle_order: bool = False,
                  use_legacy: bool = False,
                  verbose_conf: bool = True,
                  llm: str = ""):
    """llm: '' - без модели; 'hybrid' - код + модель; 'only' - только модель."""
    algo_name = "Baseline (TF-IDF + w_o=0.4 + w_q=0.3)" if use_legacy else "SmartMatcher (Модульный алгоритм v2)"
    client = None
    if llm:
        from llm_resolver import YandexClient, resolve, model_only_results
        try:
            client = YandexClient()
        except RuntimeError as e:
            sys.exit(str(e))
        algo_name = ("Только модель (YandexGPT)" if llm == 'only'
                     else algo_name + " + YandexGPT для спорных пар")
    print(f"\n{'='*75}\nТЕСТИРОВАНИЕ: {algo_name}")
    print(f"Параметр перемешивания строк (shuffle_order): {shuffle_order}\n{'='*75}")

    for seed in seeds:
        for idx, (v_path, l_path) in enumerate(sets, 1):
            V = parse_vor(v_path)
            L = parse_lsr(l_path)
            lnums = {str(x.num) for x in L}
            has_ref = sum(1 for x in V if str(x.ref).strip() in lnums)

            if seed == 1:
                print(f"Комплект {idx} ({Path(v_path).name} / {Path(l_path).name}):")
                print(f"  Позиций ВОР: {len(V)}, позиций ЛСР: {len(L)}")
                if has_ref > 0:
                    print(f"  Найдено подтвержденных ссылок ВОР -> ЛСР: {has_ref} из {len(V)}")
                else:
                    print("  Внимание: в ВОР отсутствуют ссылки '№ в ЛСР'.")
                    print("  Режим A: сформирован синтетический бенчмарк со 100% гарантированным эталоном на основе позиций ЛСР.")

            pv, truth = make_set(V, L, seed=seed, shuffle_order=shuffle_order)

            if use_legacy:
                preds = baseline_legacy.match(pv, L, thr=0.55, w_q=0.3, w_o=0.4)
            else:
                preds = match.match(pv, L, thr=0.50, min_text_threshold=0.20)

            extra = ""
            if client:
                start = model_only_results(pv, L) if llm == 'only' else preds
                preds, st = resolve(start, pv, L, client, cache_path='results/llm_cache.json')
                extra = (f" | обращений={st['calls']}+{st['cache_hits']} из кэша, "
                         f"время={st['seconds']} с, ошибок={st['errors']}")

            r = evaluate(preds, truth, L)

            print(f"seed={seed} Комплект {idx}: проверочных ВОР={len(pv):2d} | "
                  f"P={r['prec']:.3f} R={r['rec']:.3f} F1={r['f1']:.3f} | "
                  f"Классы={r['cls_acc']:.3f} Неразрешенных={r['unresolved_rate']:.3f} | "
                  f"Нет в ВОР: P={r['nv_prec']:.2f} R={r['nv_rec']:.2f}" + extra)

            if seed == 1 and verbose_conf:
                print("  Матрица классификации (Эталон -> Предсказание):")
                for (t, p), count in sorted(r['conf'].items(), key=lambda x: -x[1])[:8]:
                    print(f"    {t:32s} -> {p:32s} : {count}")


def main():
    parser = argparse.ArgumentParser(description="Бенчмарк алгоритмов сопоставления ВОР и ЛСР")
    parser.add_argument("files", nargs="*", help="Пары файлов: ВОР1 ЛСР1 [ВОР2 ЛСР2 ...]")
    parser.add_argument("--shuffle", action="store_true", help="Перемешивать порядок строк позиций ВОР")
    parser.add_argument("--compare", action="store_true", help="Сравнить Baseline и SmartMatcher бок о бок")
    parser.add_argument("--legacy", action="store_true", help="Запустить только legacy baseline")
    parser.add_argument("--llm", action="store_true", help="Код + YandexGPT для спорных пар")
    parser.add_argument("--model-only", action="store_true", help="Только модель (без кода)")

    args = parser.parse_args()

    files = args.files
    if not files:
        # По умолчанию берем файлы проекта
        files = ["ВОР.xlsx", "ЛСР.xlsx"]

    if len(files) % 2 != 0:
        print("Ошибка: файлы должны передаваться парами (ВОР, затем ЛСР).")
        sys.exit(2)

    sets = []
    for i in range(0, len(files), 2):
        v = Path(files[i])
        l = Path(files[i + 1])
        if not v.exists() and (Path("data") / v).exists():
            v = Path("data") / v
        if not l.exists() and (Path("data") / l).exists():
            l = Path("data") / l
        if not v.exists() or not l.exists():
            print(f"Ошибка: не найден один из файлов: {v} или {l}")
            sys.exit(1)
        sets.append((str(v), str(l)))

    if args.compare:
        print("ЗАПУСК СРАВНИТЕЛЬНОГО АНАЛИЗА ВЕРСИЙ (Baseline vs SmartMatcher)")
        run_benchmark(sets, shuffle_order=args.shuffle, use_legacy=True, verbose_conf=False)
        run_benchmark(sets, shuffle_order=args.shuffle, use_legacy=False, verbose_conf=True)
        if args.llm:
            run_benchmark(sets, shuffle_order=args.shuffle, use_legacy=True, verbose_conf=False, llm='hybrid')
        if args.model_only:
            run_benchmark(sets, shuffle_order=args.shuffle, verbose_conf=False, llm='only')
    else:
        mode = 'only' if args.model_only else ('hybrid' if args.llm else '')
        run_benchmark(sets, shuffle_order=args.shuffle, use_legacy=args.legacy, verbose_conf=True, llm=mode)


if __name__ == '__main__':
    main()
