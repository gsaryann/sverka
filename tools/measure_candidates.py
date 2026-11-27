"""Воспроизводимый расчёт охвата отбора кандидатов (top_k = 1, 3, 5, 10) по комплектам смет.

Запуск:
    python tools/measure_candidates.py
"""
import csv
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parsers import parse_lsr, parse_vor
import llm_resolver
import match
import perturb


def get_git_short_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ROOT),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def clear_vor_hints(vor: List[Any]) -> List[Any]:
    for v in vor:
        v.ref = ""
        v.code = ""
    assert all(not (v.ref or "").strip() for v in vor), "ref должен быть очищен перед сопоставлением"
    return vor


def eval_coverage(title: str, vor_nh: List[Any], lsr: List[Any], truth: Dict[str, str]) -> Dict[str, Any]:
    assert all(not (v.ref or "").strip() for v in vor_nh)
    results = match.match(vor_nh, lsr, thr=0.50, min_text_threshold=0.20)
    vor_idx_by_num = {v.num: i for i, v in enumerate(vor_nh)}
    lsr_idx_by_num = {l.num: j for j, l in enumerate(lsr)}
    sim = match.similarity(vor_nh, lsr)

    used_lsr = {lsr_idx_by_num[r["lsr"]] for r in results if r.get("lsr") and r.get("lsr") in lsr_idx_by_num}
    free = [j for j in range(len(lsr)) if j not in used_lsr]

    disputed = []
    for r in results:
        vn = r.get("vor")
        if not vn or vn not in truth:
            continue
        needs = bool(
            r.get("is_ambiguous")
            or r.get("cls") == "Нет в рассматриваемой смете"
            or (float(r.get("text_sim", 1.0)) < 0.40 and r.get("cls") != "Дубль")
        )
        if needs:
            disputed.append(r)

    cov = {1: 0, 3: 0, 5: 0, 10: 0}
    with_true_in_lsr = 0
    for r in disputed:
        vn = r["vor"]
        true_j = lsr_idx_by_num.get(truth[vn])
        if true_j is None:
            continue
        with_true_in_lsr += 1
        i = vor_idx_by_num[vn]
        cur_j = lsr_idx_by_num.get(r["lsr"]) if r.get("lsr") else None
        is_work_v = llm_resolver.is_work_item(vor_nh[i].name)

        for top_k in (1, 3, 5, 10):
            if top_k == 1:
                cand_idx = [cur_j] if cur_j is not None else llm_resolver.rank_candidates_for_item(
                    vor_nh[i], i, free, lsr, sim, top_k=1
                )
            else:
                slots_needed = top_k - (1 if cur_j is not None else 0)
                if is_work_v:
                    work_cands = [j for j in free if llm_resolver.is_work_item_lsr(lsr[j]) and j != cur_j]
                    if len(work_cands) < slots_needed:
                        all_works = [j for j in range(len(lsr)) if llm_resolver.is_work_item_lsr(lsr[j]) and j != cur_j]
                        work_cands = list(dict.fromkeys(work_cands + all_works))
                    pool = llm_resolver.rank_candidates_for_item(vor_nh[i], i, work_cands, lsr, sim, top_k=slots_needed)
                    if len(pool) < slots_needed:
                        remaining = [j for j in free if j != cur_j and j not in pool]
                        pool.extend(llm_resolver.rank_candidates_for_item(vor_nh[i], i, remaining, lsr, sim, top_k=slots_needed - len(pool)))
                else:
                    candidates_to_rank = [j for j in free if j != cur_j]
                    pool = llm_resolver.rank_candidates_for_item(vor_nh[i], i, candidates_to_rank, lsr, sim, top_k=slots_needed)
                cand_idx = ([cur_j] if cur_j is not None else []) + pool

            if true_j in cand_idx:
                cov[top_k] += 1

    print(f"{title}: VOR={len(vor_nh)}, LSR={len(lsr)}, спорных={len(disputed)} (с эталоном в ЛСР={with_true_in_lsr})")
    for k in (1, 3, 5, 10):
        pct = (cov[k] / with_true_in_lsr * 100) if with_true_in_lsr else 0.0
        print(f"  k={k:>2}: {cov[k]} / {with_true_in_lsr} ({pct:.1f}%)")
    return {"title": title, "disputed": len(disputed), "with_true": with_true_in_lsr, "cov": cov}


def main() -> int:
    print(f"commit: {get_git_short_hash()}")
    print("=== 1. Реальные эталоны (№ в ЛСР / pair_2_3_truth.csv) ===")
    for title, vf, lf in [
        ("Дворец (86)", "ВОР.xlsx", "ЛСР.xlsx"),
        ("Освещение (137)", "ВОР освещение КОРР.xlsx", "ЛСР освещение КОРР.xlsx"),
    ]:
        vor = parse_vor(str(ROOT / "data" / vf))
        lsr = parse_lsr(str(ROOT / "data" / lf))
        truth = {v.num: (v.ref or "").strip() for v in vor if (v.ref or "").strip()}
        eval_coverage(title, clear_vor_hints(vor), lsr, truth)

    vor23 = parse_vor(str(ROOT / "data" / "Приложение №2.3.1 Ведомость объемов работ №2.xlsx"))
    lsr23 = parse_lsr(str(ROOT / "data" / "Приложение №2.3 Локальный сметный расчет №2.xlsx"))
    with open(ROOT / "data" / "real_truth" / "pair_2_3_truth.csv", encoding="utf-8-sig") as f:
        t23 = {r["vor_num"]: r["lsr_num"] for r in csv.DictReader(f)}
    eval_coverage("Приложение №2.3 (23)", clear_vor_hints(vor23), lsr23, t23)

    print("\n=== 2. Эталон perturb.make_set (seed=1, shuffle=False) для комплектов без № в ЛСР ===")
    for title, vf, lf in [
        ("83 позиции (КОРР)", "ВЕДОМОСТЬ ОБЪЕМОВ РАБОТ.xlsx", "ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЕТ.xlsx"),
        ("137 позиций (Освещение, perturb)", "ВОР освещение КОРР.xlsx", "ЛСР освещение КОРР.xlsx"),
        ("534 позиции (1 этаж кабинеты)", "ВОР (1 этаж кабинеты).xlsx", "ЛСР (1 этаж кабинеты).xlsx"),
        ("Чайная (371)",
         "02_01_01_чайная_Анастасьевка__Текущий_ремонт___Дефектная_ведомость_по_смете_2.xlsx",
         "02_01_01_чайная_Анастасьевка__Текущий_ремонт___ЛСР_по_Методике_2020__РИМ__2.xlsx"),
    ]:
        vor = parse_vor(str(ROOT / "data" / vf))
        lsr = parse_lsr(str(ROOT / "data" / lf))
        pv, pt = perturb.make_set(vor, lsr, seed=1, shuffle_order=False)
        truth = {str(t["vor"]): str(t["lsr"]) for t in pt if t.get("vor") is not None and t.get("lsr") is not None}
        eval_coverage(title, clear_vor_hints(pv), lsr, truth)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
