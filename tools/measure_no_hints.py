"""Воспроизводимый замер комплекта «Дворец молодёжи» без подсказок (с очищенным ref).

Запуск:
    python tools/measure_no_hints.py --mode algo
    python tools/measure_no_hints.py --mode hybrid_local --model qwen2.5:7b-instruct --out-json results/no_hints_<hash>.json
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parsers import parse_lsr, parse_vor
import match


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


def is_disputed(row: Dict[str, Any]) -> bool:
    return bool(
        row.get("vor")
        and (
            row.get("is_ambiguous")
            or row.get("cls") == "Нет в рассматриваемой смете"
            or (float(row.get("text_sim", 1.0)) < 0.40 and row.get("cls") != "Дубль")
        )
    )


def evaluate_vor_results(results: List[Dict[str, Any]], truth: Dict[str, str]) -> Dict[str, Any]:
    correct = 0
    wrong = 0
    no_pair = 0
    disputed_count = 0
    cls_counts = Counter()

    for r in results:
        vn = r.get("vor")
        if not vn:
            continue
        cls_counts[r.get("cls") or "(none)"] += 1
        if is_disputed(r):
            disputed_count += 1
        ln = r.get("lsr")
        if not ln:
            no_pair += 1
        elif ln == truth.get(vn):
            correct += 1
        else:
            wrong += 1

    return {
        "total_vor": len(truth),
        "correct": correct,
        "wrong": wrong,
        "no_pair": no_pair,
        "disputed": disputed_count,
        "cls_counts": dict(cls_counts),
    }


def load_dvorets_no_hints() -> Tuple[List[Any], List[Any], Dict[str, str]]:
    vor = parse_vor(str(ROOT / "data" / "ВОР.xlsx"))
    lsr = parse_lsr(str(ROOT / "data" / "ЛСР.xlsx"))
    truth = {v.num: (v.ref or "").strip() for v in vor if (v.ref or "").strip()}
    for v in vor:
        v.ref = ""
        v.code = ""
    assert all(not (v.ref or "").strip() for v in vor), "ref должен быть очищен перед сопоставлением"
    return vor, lsr, truth


def run_algo() -> Dict[str, Any]:
    vor, lsr, truth = load_dvorets_no_hints()
    res = match.match(vor, lsr, thr=0.50, min_text_threshold=0.20)
    summary = evaluate_vor_results(res, truth)
    summary["results"] = res
    summary["vor"] = vor
    summary["lsr"] = lsr
    summary["truth"] = truth
    return summary


class _RecordingClient:
    def __init__(self, inner: Any):
        self.inner = inner
        self.provider = inner.provider
        self.model = inner.model
        self.raw_calls: List[Dict[str, Any]] = []

    @property
    def total_input_tokens(self) -> int:
        return self.inner.total_input_tokens

    @property
    def total_output_tokens(self) -> int:
        return self.inner.total_output_tokens

    def ask(self, system: str, user: str) -> str:
        t0 = time.time()
        ans = self.inner.ask(system, user)
        self.raw_calls.append({
            "user_head": user[:200],
            "response": ans,
            "seconds": round(time.time() - t0, 2),
        })
        return ans


def run_hybrid_local(model: str, out_json: Optional[Path]) -> Dict[str, Any]:
    import llm_resolver

    algo_data = run_algo()
    vor = algo_data["vor"]
    lsr = algo_data["lsr"]
    truth = algo_data["truth"]
    algo_res = algo_data["results"]

    unpaired_15 = {r["vor"] for r in algo_res if r.get("vor") and not r.get("lsr")}
    other_disputed = {r["vor"] for r in algo_res if is_disputed(r) and r["vor"] not in unpaired_15}

    cli = _RecordingClient(llm_resolver.make_client("local", model=model, timeout=120.0))
    fd, tmp_cache = tempfile.mkstemp(prefix="no_hints_cache_", suffix=".json")
    os.close(fd)
    try:
        os.unlink(tmp_cache)
    except OSError:
        pass

    try:
        res_llm, llm_stats = llm_resolver.resolve(
            algo_res,
            vor,
            lsr,
            cli,
            mode="arbitration",
            cache_path=tmp_cache,
            verbose=False,
        )
    finally:
        if os.path.exists(tmp_cache):
            try:
                os.unlink(tmp_cache)
            except OSError:
                pass

    overall = evaluate_vor_results(res_llm, truth)

    def _subset_stats(vor_nums: set) -> Dict[str, Any]:
        c = w = np_ = 0
        decs = Counter()
        rows = []
        for r in res_llm:
            vn = r.get("vor")
            if vn not in vor_nums:
                continue
            dec = r.get("ai_decision") or "(none)"
            decs[dec] += 1
            ln = r.get("lsr")
            t = truth.get(vn)
            if not ln:
                np_ += 1
                status = "no_pair"
            elif ln == t:
                c += 1
                status = "correct"
            else:
                w += 1
                status = "wrong"
            rows.append({
                "vor": vn,
                "vor_name": r.get("vor_name"),
                "pred_lsr": ln,
                "true_lsr": t,
                "status": status,
                "ai_decision": dec,
                "ai_reason": r.get("ai_reason"),
                "ai_confidence": r.get("ai_confidence"),
                "cls": r.get("cls"),
            })
        return {
            "total": len(vor_nums),
            "correct": c,
            "wrong": w,
            "no_pair": np_,
            "decisions": dict(decs),
            "rows": rows,
        }

    unpaired_stats = _subset_stats(unpaired_15)
    other_stats = _subset_stats(other_disputed)

    payload = {
        "commit": get_git_short_hash(),
        "kit": "Дворец молодёжи (data/ВОР.xlsx / data/ЛСР.xlsx)",
        "mode": "hybrid_local",
        "provider": "local",
        "model": model,
        "repeats": 1,
        "algo_baseline": {
            "total_vor": algo_data["total_vor"],
            "correct": algo_data["correct"],
            "wrong": algo_data["wrong"],
            "no_pair": algo_data["no_pair"],
            "disputed": algo_data["disputed"],
            "cls_counts": algo_data["cls_counts"],
        },
        "overall": overall,
        "unpaired_15": {k: v for k, v in unpaired_stats.items() if k != "rows"},
        "other_disputed": {k: v for k, v in other_stats.items() if k != "rows"},
        "unpaired_15_rows": unpaired_stats["rows"],
        "other_disputed_rows": other_stats["rows"],
        "llm_stats": llm_stats,
        "raw_calls": cli.raw_calls,
    }

    if out_json is not None:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Замер «Дворец молодёжи» без подсказок (с очищенным ref)")
    parser.add_argument("--mode", choices=["algo", "hybrid_local"], default="algo")
    parser.add_argument("--model", default=os.environ.get("LOCAL_LLM_MODEL", "qwen2.5:7b-instruct"))
    parser.add_argument("--out-json", default=None)
    args = parser.parse_args()

    if args.mode == "algo":
        s = run_algo()
        print(f"Режим: algo | commit: {get_git_short_hash()}")
        print(f"Всего ВОР: {s['total_vor']}, верно: {s['correct']}, неверно: {s['wrong']}, без пары: {s['no_pair']}, на проверку: {s['disputed']}")
        print(f"Классы: {s['cls_counts']}")
    else:
        out_p = Path(args.out_json) if args.out_json else (ROOT / "results" / f"no_hints_{get_git_short_hash()}.json")
        if not out_p.is_absolute():
            out_p = ROOT / out_p
        p = run_hybrid_local(args.model, out_p)
        o = p["overall"]
        print(f"Режим: hybrid_local ({args.model}, 1 повтор) | commit: {p['commit']}")
        print(f"Итого: верно={o['correct']}, неверно={o['wrong']}, без пары={o['no_pair']}, на проверку={o['disputed']}")
        print(f"15 непарных algo: {p['unpaired_15']}")
        print(f"Прочие спорные: {p['other_disputed']}")
        print(f"Сырые ответы сохранены: {out_p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
