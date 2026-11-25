#!/usr/bin/env python3
"""
Скрипт сбора воспроизводимых метрик сопоставления (Precision, Recall, F1, точность классов,
устойчивость к перемешиванию, анализ коллизий и единиц измерения)
для сравнительного анализа SmartMatcher v2 и Baseline Legacy.

Запуск:
    python tools/collect_metrics.py
"""

import sys
import subprocess
import collections
from pathlib import Path
from datetime import datetime

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from parsers import parse_vor, parse_lsr
from perturb import make_set
import match
import baseline_legacy
from evaluate import evaluate, norm_cls, equiv_groups

DATA_DIR = ROOT_DIR / "data"
DOCS_METRICS_DIR = ROOT_DIR / "docs" / "metrics"
DOCS_METRICS_DIR.mkdir(parents=True, exist_ok=True)

SETS = [
    ("Дворец", "ВОР.xlsx", "ЛСР.xlsx"),
    ("Освещение", "ВОР освещение КОРР.xlsx", "ЛСР освещение КОРР.xlsx"),
    ("Ремонт", "ВОР ремонт и утеплитель.xlsx", "ЛСР по Методике 2020 (РИМ).xlsx"),
    ("Чайная", "02_01_01_чайная_Анастасьевка__Текущий_ремонт___Дефектная_ведомость_по_смете_2.xlsx",
     "02_01_01_чайная_Анастасьевка__Текущий_ремонт___ЛСР_по_Методике_2020__РИМ__2.xlsx"),
]

SEEDS = (1, 2, 3)
MODES = [
    ("Порядок сохранён", False),
    ("Перемешивание строк (--shuffle)", True)
]


def get_git_hash() -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            check=True
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"


def analyze_diagnostics(pv, truth, lsr, preds_smart, preds_base):
    """Детальный расчет доли неразрешенных, точности авто-решений и распознавания единиц."""
    eq = equiv_groups(lsr)
    tv = {str(t['vor']): t for t in truth if t.get('vor') is not None}
    total_positions = len(tv)

    # 1. SmartMatcher
    smart_review = []
    smart_auto = []
    smart_unit_correct = 0
    smart_unit_total = 0

    for p in preds_smart:
        v_num = str(p.get('vor'))
        if v_num not in tv:
            continue
        t = tv[v_num]
        is_rev = (p.get('upper_status') == 'Требует проверки' or norm_cls(p.get('cls')) == 'Требуется проверка')
        t_lsr = str(t['lsr']) if t.get('lsr') is not None else None
        p_lsr = str(p['lsr']) if p.get('lsr') is not None else None

        corr = (p_lsr in eq.get(t_lsr, {t_lsr})) if t_lsr else (p_lsr is None)
        true_cls = norm_cls(t.get('cls'))
        pred_cls = norm_cls(p.get('cls'))
        is_truly_disputable = (true_cls != 'Совпало' or t_lsr is None)

        if is_rev:
            smart_review.append(is_truly_disputable)
        else:
            smart_auto.append(corr)

        if true_cls in ('Расхождение единиц', 'Совпало (после перевода единиц)'):
            smart_unit_total += 1
            if pred_cls == true_cls:
                smart_unit_correct += 1

    # 2. Baseline Legacy
    base_auto = []
    base_unit_correct = 0
    base_unit_total = 0

    for p in preds_base:
        v_num = str(p.get('vor'))
        if v_num not in tv:
            continue
        t = tv[v_num]
        t_lsr = str(t['lsr']) if t.get('lsr') is not None else None
        p_lsr = str(p['lsr']) if p.get('lsr') is not None else None
        corr = (p_lsr in eq.get(t_lsr, {t_lsr})) if t_lsr else (p_lsr is None)
        true_cls = norm_cls(t.get('cls'))
        pred_cls = norm_cls(p.get('cls'))

        base_auto.append(corr)
        if true_cls in ('Расхождение единиц', 'Совпало (после перевода единиц)'):
            base_unit_total += 1
            if pred_cls == true_cls:
                base_unit_correct += 1

    return {
        'total_pos': total_positions,
        'smart_unres': len(smart_review),
        'smart_unres_rate': len(smart_review) / total_positions if total_positions else 0.0,
        'smart_auto_prec': sum(smart_auto) / len(smart_auto) if smart_auto else 0.0,
        'smart_review_disputable_rate': sum(smart_review) / len(smart_review) if smart_review else 0.0,
        'smart_unit_correct': smart_unit_correct,
        'smart_unit_total': smart_unit_total,

        'base_unres': 0,
        'base_unres_rate': 0.0,
        'base_auto_prec': sum(base_auto) / len(base_auto) if base_auto else 0.0,
        'base_unit_correct': base_unit_correct,
        'base_unit_total': base_unit_total,
    }


def collect_raw_metrics():
    """Собирает детальные метрики по всем датасетам, режимам и seed."""
    results = []

    for set_name, v_fn, l_fn in SETS:
        vp = DATA_DIR / v_fn
        lp = DATA_DIR / l_fn
        if not vp.exists() or not lp.exists():
            continue

        vor = parse_vor(str(vp))
        lsr = parse_lsr(str(lp))

        for mode_title, shuffle_flag in MODES:
            for seed in SEEDS:
                pv, truth = make_set(vor, lsr, seed=seed, shuffle_order=shuffle_flag)

                # 1. Baseline Legacy
                preds_base = baseline_legacy.match(pv, lsr, thr=0.55, w_q=0.3, w_o=0.4)
                r_base = evaluate(preds_base, truth, lsr)

                # 2. SmartMatcher v2
                preds_smart = match.match(pv, lsr, thr=0.50, min_text_threshold=0.20)
                r_smart = evaluate(preds_smart, truth, lsr)

                # 3. Диагностика коллизий и единиц
                diag = analyze_diagnostics(pv, truth, lsr, preds_smart, preds_base)

                results.append({
                    "set": set_name,
                    "mode": mode_title,
                    "seed": seed,
                    "pv_count": len(pv),
                    # SmartMatcher
                    "smart_p": r_smart["prec"],
                    "smart_r": r_smart["rec"],
                    "smart_f1": r_smart["f1"],
                    "smart_cls": r_smart["cls_acc"],
                    "smart_unres": diag["smart_unres"],
                    "smart_unres_rate": diag["smart_unres_rate"],
                    "smart_auto_prec": diag["smart_auto_prec"],
                    "smart_review_disp": diag["smart_review_disputable_rate"],
                    "smart_unit_cor": diag["smart_unit_correct"],
                    "smart_unit_tot": diag["smart_unit_total"],
                    # Baseline
                    "base_p": r_base["prec"],
                    "base_r": r_base["rec"],
                    "base_f1": r_base["f1"],
                    "base_cls": r_base["cls_acc"],
                    "base_unres": diag["base_unres"],
                    "base_unres_rate": diag["base_unres_rate"],
                    "base_auto_prec": diag["base_auto_prec"],
                    "base_unit_cor": diag["base_unit_correct"],
                    "base_unit_tot": diag["base_unit_total"],
                })
    return results


def compute_averages(raw_results):
    """Вычисляет средние по комплекту и режиму."""
    groups = collections.defaultdict(list)
    for r in raw_results:
        groups[(r["set"], r["mode"])].append(r)

    averages = []
    for (set_name, mode_title), items in groups.items():
        n = len(items)
        s_p = sum(x["smart_p"] for x in items) / n
        s_r = sum(x["smart_r"] for x in items) / n
        s_f1 = sum(x["smart_f1"] for x in items) / n
        s_cls = sum(x["smart_cls"] for x in items) / n
        s_unres = sum(x["smart_unres"] for x in items) / n

        b_p = sum(x["base_p"] for x in items) / n
        b_r = sum(x["base_r"] for x in items) / n
        b_f1 = sum(x["base_f1"] for x in items) / n
        b_cls = sum(x["base_cls"] for x in items) / n
        b_unres = sum(x["base_unres"] for x in items) / n

        delta_f1 = (s_f1 - b_f1) * 100.0  # в п.п.
        if delta_f1 > 0.05:
            winner = "SmartMatcher"
        elif delta_f1 < -0.05:
            winner = "Baseline"
        else:
            winner = "Ничья"

        averages.append({
            "set": set_name,
            "mode": mode_title,
            "smart_p": s_p,
            "smart_r": s_r,
            "smart_f1": s_f1,
            "smart_cls": s_cls,
            "smart_unres": s_unres,
            "base_p": b_p,
            "base_r": b_r,
            "base_f1": b_f1,
            "base_cls": b_cls,
            "base_unres": b_unres,
            "delta_f1": delta_f1,
            "winner": winner
        })
    return averages


def compute_robustness(averages):
    """Вычисляет устойчивость к порядку строк (F1 order - F1 shuffle)."""
    by_set = collections.defaultdict(dict)
    for a in averages:
        key = "order" if "Порядок" in a["mode"] else "shuffle"
        by_set[a["set"]][key] = a

    robustness = []
    for set_name in ["Дворец", "Освещение", "Ремонт", "Чайная"]:
        ord_data = by_set[set_name].get("order")
        shuf_data = by_set[set_name].get("shuffle")
        if not ord_data or not shuf_data:
            continue

        s_ord_f1 = ord_data["smart_f1"]
        s_shf_f1 = shuf_data["smart_f1"]
        s_drop = (s_ord_f1 - s_shf_f1) * 100.0

        b_ord_f1 = ord_data["base_f1"]
        b_shf_f1 = shuf_data["base_f1"]
        b_drop = (b_ord_f1 - b_shf_f1) * 100.0

        # Разница устойчивости: насколько больше потерял Baseline по сравнению со SmartMatcher
        diff_robustness = b_drop - s_drop

        robustness.append({
            "set": set_name,
            "smart_order_f1": s_ord_f1,
            "smart_shuf_f1": s_shf_f1,
            "smart_drop": s_drop,
            "base_order_f1": b_ord_f1,
            "base_shuf_f1": b_shf_f1,
            "base_drop": b_drop,
            "diff_robustness": diff_robustness
        })
    return robustness


def compute_diagnostics_by_set(raw_results):
    """Агрегирует диагностические показатели по каждому комплекту."""
    by_set = collections.defaultdict(list)
    for r in raw_results:
        by_set[r["set"]].append(r)

    diagnostics = []
    for set_name in ["Дворец", "Освещение", "Ремонт", "Чайная"]:
        items = by_set[set_name]
        n = len(items)

        s_unres_pct = (sum(x["smart_unres_rate"] for x in items) / n) * 100.0
        b_unres_pct = 0.0

        s_auto_prec = (sum(x["smart_auto_prec"] for x in items) / n) * 100.0
        b_auto_prec = (sum(x["base_auto_prec"] for x in items) / n) * 100.0

        s_disp_pct = (sum(x["smart_review_disp"] for x in items) / n) * 100.0

        s_unit_cor = sum(x["smart_unit_cor"] for x in items)
        s_unit_tot = sum(x["smart_unit_tot"] for x in items)
        b_unit_cor = sum(x["base_unit_cor"] for x in items)
        b_unit_tot = sum(x["base_unit_tot"] for x in items)

        diagnostics.append({
            "set": set_name,
            "smart_unres_pct": s_unres_pct,
            "base_unres_pct": b_unres_pct,
            "smart_auto_prec": s_auto_prec,
            "base_auto_prec": b_auto_prec,
            "smart_review_disp": s_disp_pct,
            "smart_unit_cor": s_unit_cor,
            "smart_unit_tot": s_unit_tot,
            "base_unit_cor": b_unit_cor,
            "base_unit_tot": b_unit_tot,
        })
    return diagnostics


def collect_all_metrics():
    git_hash = get_git_hash()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"=== Сбор честных и воспроизводимых метрик F1 [commit {git_hash}] ===")
    print(f"Дата расчёта: {timestamp}\n")

    # 1. Расчёт сырых данных
    print("Расчёт матрицы тестов (4 датасета x 3 seeds x 2 режима)...")
    raw_results = collect_raw_metrics()

    # 2. Агрегация средних и аналитических таблиц
    averages = compute_averages(raw_results)
    robustness = compute_robustness(averages)
    diagnostics = compute_diagnostics_by_set(raw_results)

    # 3. Удаление старых отчетов f1_*.md перед записью актуального
    for old_f in DOCS_METRICS_DIR.glob("f1_*.md"):
        try:
            old_f.unlink()
        except Exception:
            pass

    out_md = DOCS_METRICS_DIR / f"f1_{git_hash}.md"
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(f"# Воспроизводимые метрики качества сопоставления F1 (Бенчмарк ВКР)\n\n")
        f.write(f"- **Git commit:** `{git_hash}`\n")
        f.write(f"- **Дата формирования:** {timestamp}\n")
        f.write(f"- **Методы:** SmartMatcher v2 (`match.py`) vs Baseline Legacy (`baseline_legacy.py`)\n")
        f.write(f"- **Условия тестирования:** Автономный режим без LLM (детерминированная алгоритмическая оценка ядер)\n\n")

        # ТАБЛИЦА 1
        f.write("## 1. Сводная таблица средних показателей по комплектам и режимам\n\n")
        f.write("| Комплект | Режим | Smart P | Smart R | **Smart F1** | Smart Точн. кл. | Smart Неразр. | Base P | Base R | **Base F1** | Base Точн. кл. | Base Неразр. | $\\Delta F1$ (п.п.) | Лидер по F1 |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")

        for a in averages:
            f.write(
                f"| {a['set']} | {a['mode']} | "
                f"{a['smart_p']:.4f} | {a['smart_r']:.4f} | **{a['smart_f1']:.4f}** | {a['smart_cls']:.4f} | {a['smart_unres']:.1f} | "
                f"{a['base_p']:.4f} | {a['base_r']:.4f} | **{a['base_f1']:.4f}** | {a['base_cls']:.4f} | {a['base_unres']:.1f} | "
                f"{a['delta_f1']:+.2f} п.п. | {a['winner']} |\n"
            )

        # ТАБЛИЦА 2
        f.write("\n## 2. Устойчивость к порядку строк (деградация $F_1$ при перемешивании)\n\n")
        f.write("| Комплект | Smart F1 (порядок) | Smart F1 (shuffle) | Падение Smart (п.п.) | Base F1 (порядок) | Base F1 (shuffle) | Падение Base (п.п.) | Разница устойчивости (п.п.) |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")

        for r in robustness:
            f.write(
                f"| {r['set']} | {r['smart_order_f1']:.4f} | {r['smart_shuf_f1']:.4f} | {r['smart_drop']:.2f} п.п. | "
                f"{r['base_order_f1']:.4f} | {r['base_shuf_f1']:.4f} | {r['base_drop']:.2f} п.п. | {r['diff_robustness']:+.2f} п.п. |\n"
            )

        # ТАБЛИЦА 3
        f.write("\n## 3. Диагностика коллизий и единиц измерения\n\n")
        f.write("| Комплект | Доля на проверку (Smart / Base) | Точность авто-решений (Smart / Base) | Спорность позиций проверки (Smart) | Верно найденные расхождения единиц (Smart / Base) |\n")
        f.write("|---|---|---|---|---|\n")

        for d in diagnostics:
            f.write(
                f"| {d['set']} | {d['smart_unres_pct']:.2f}% / {d['base_unres_pct']:.2f}% | "
                f"{d['smart_auto_prec']:.2f}% / {d['base_auto_prec']:.2f}% | "
                f"{d['smart_review_disp']:.2f}% | "
                f"{d['smart_unit_cor']}/{d['smart_unit_tot']} vs {d['base_unit_cor']}/{d['base_unit_tot']} |\n"
            )

        # РАЗДЕЛ 4: ВЫВОДЫ (генерируются строго из средних чисел)
        f.write("\n## 4. Аналитический вывод по фактическим данным бенчмарка\n\n")

        # Извлечение точных значений для текста выводов
        avg_dv_ord = next(x for x in averages if x["set"] == "Дворец" and "Порядок" in x["mode"])
        avg_lt_ord = next(x for x in averages if x["set"] == "Освещение" and "Порядок" in x["mode"])
        avg_ch_shf = next(x for x in averages if x["set"] == "Чайная" and "Перемешивание" in x["mode"])
        rob_lt = next(x for x in robustness if x["set"] == "Освещение")
        rob_rm = next(x for x in robustness if x["set"] == "Ремонт")
        diag_lt = next(x for x in diagnostics if x["set"] == "Освещение")
        diag_ch = next(x for x in diagnostics if x["set"] == "Чайная")
        diag_dv = next(x for x in diagnostics if x["set"] == "Дворец")

        f.write(
            f"1. **В чём Baseline Legacy показывает более высокий $F_1$:**\n"
            f"   - На исходно упорядоченных сметах алгоритм Baseline превосходит SmartMatcher за счёт эвристического веса позиционной близости ($w_o = 0.4$):\n"
            f"     - На комплекте «Дворец» (порядок сохранён) $F_1$ составляет {avg_dv_ord['base_f1']:.4f} у Baseline против {avg_dv_ord['smart_f1']:.4f} у SmartMatcher ({avg_dv_ord['delta_f1']:+.2f} п.п.).\n"
            f"     - На комплекте «Освещение» (порядок сохранён) $F_1$ составляет {avg_lt_ord['base_f1']:.4f} у Baseline против {avg_lt_ord['smart_f1']:.4f} у SmartMatcher ({avg_lt_ord['delta_f1']:+.2f} п.п.).\n"
            f"   - Это обусловлено тем, что в синхронно сформированных парах смета-ВОР порядковые номера строк близки, что дает Baseline безусловный бонус к оценке сходства.\n\n"
        )

        f.write(
            f"2. **Устойчивость к порядку строк (деградация $F_1$):**\n"
            f"   - При случайном перемешивании строк Baseline теряет позиционный ориентир:\n"
            f"     - На комплекте «Освещение» падение $F_1$ у Baseline составляет {rob_lt['base_drop']:.2f} п.п. (с {rob_lt['base_order_f1']:.4f} до {rob_lt['base_shuf_f1']:.4f}), тогда как у SmartMatcher падение составляет {rob_lt['smart_drop']:.2f} п.п. (разница устойчивости {rob_lt['diff_robustness']:+.2f} п.п.).\n"
            f"     - На комплекте «Ремонт» падение у Baseline составляет {rob_rm['base_drop']:.2f} п.п., а у SmartMatcher — {rob_rm['smart_drop']:.2f} п.п. (разница устойчивости {rob_rm['diff_robustness']:+.2f} п.п.).\n"
            f"     - На крупном комплекте «Чайная» при перемешивании средний $F_1$ SmartMatcher составляет {avg_ch_shf['smart_f1']:.4f}, а Baseline — {avg_ch_shf['base_f1']:.4f} ({avg_ch_shf['delta_f1']:+.2f} п.п., лидер: {avg_ch_shf['winner']}).\n\n"
        )

        f.write(
            f"3. **Фильтрация коллизий и защита от ложноположительных решений:**\n"
            f"   - Baseline Legacy принудительно принимает решение по 100% строк (доля на проверку {diag_lt['base_unres_pct']:.2f}%), что делает его неспособным сигнализировать о сомнениях.\n"
            f"   - SmartMatcher направляет на проверку инженеру или ИИ-арбитру в среднем {diag_lt['smart_unres_pct']:.2f}% позиций на «Освещении» и {diag_ch['smart_unres_pct']:.2f}% на «Чайной».\n"
            f"   - Из отправленных на проверку позиций {diag_lt['smart_review_disp']:.2f}% на «Освещении» и {diag_ch['smart_review_disp']:.2f}% на «Чайной» действительно содержат расхождения или отсутствуют в смете.\n\n"
        )

        f.write(
            f"4. **Точность распознавания единиц измерения:**\n"
            f"   - Модуль физической нормализации `units.py` позволяет SmartMatcher точно классифицировать несовпадения и масштабирование единиц: на комплекте «Дворец» верно найдено {diag_dv['smart_unit_cor']}/{diag_dv['smart_unit_tot']} расхождений единиц против {diag_dv['base_unit_cor']}/{diag_dv['base_unit_tot']} у Baseline.\n"
        )

    print(f"\nТаблица средних метрик успешно сохранена в: {out_md}")
    return out_md


if __name__ == "__main__":
    collect_all_metrics()
