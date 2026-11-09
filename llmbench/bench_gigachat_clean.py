"""Замер модели GigaChat-3-Ultra на задачах tasks_set1.json с очищенными формулировками промпта.

Исключает ложные срабатывания корпоративного модерационного фильтра Сбера
(замена терминов 'ВОР', 'экспертное решение', 'арбитраж' на нейтральные аналитические).
Считает реальную точность: верно, неверно, отказ, невалидный JSON, время и токены.
"""
import sys, os, re, json, time, csv, statistics
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    try: sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass

sys.path.insert(0, os.getcwd())
try:
    from dotenv import load_dotenv; load_dotenv()
except Exception:
    pass

from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole

HERE = Path(__file__).resolve().parent

CLEAN_SYSTEM = (
    "Ты система сопоставления строительных сметных позиций. "
    "Сопоставь наименование работы из ведомости с вариантами сметы. "
    "Отвечай СТРОГО в формате JSON:\n"
    '{"action": "CONFIRM"|"REASSIGN"|"REJECT", "candidate": <номер 1..K или null>, "confidence": <0..1>, "reason": "<краткая причина>"}'
)


def sanitize_prompt(p: str) -> str:
    p = p.replace("Позиция ВОР:", "Строка ведомости работ:")
    p = p.replace("сметы ЛСР:", "сметы:")
    p = p.replace("Какое экспертное решение принять? Подтвердить выбор алгоритма ('CONFIRM'), переназначить на другого кандидата ('REASSIGN') или отклонить ('REJECT')?",
                  "Какой вариант выбрать: CONFIRM (подтвердить выбор 1), REASSIGN (выбрать другой) или REJECT (отклонить все)?")
    p = p.replace("экспертное решение", "решение")
    p = p.replace("арбитраж", "сопоставление")
    return p


def parse_answer(text, k):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    action = str(obj.get("action", "")).upper().strip()
    cand = obj.get("candidate")
    if cand is not None:
        try:
            cand = int(cand)
        except (TypeError, ValueError):
            cand = None
        if cand is not None and not (1 <= cand <= k):
            return None
    try:
        conf = max(0.0, min(1.0, float(obj.get("confidence", 0.0))))
    except (TypeError, ValueError):
        conf = 0.0
    if action not in ("CONFIRM", "REASSIGN", "REJECT"):
        return None
    if action == "CONFIRM":
        cand = 1
    elif action == "REJECT":
        cand = None
    elif cand is None:
        return None
    return dict(action=action, cand=cand, conf=conf, reason=str(obj.get("reason", ""))[:200])


def judge(task, ans):
    if not ans:
        return "invalid"
    if task["ok_idx"]:
        if ans["cand"] is None:
            return "missed"
        if ans["conf"] < 0.5:
            return "abstain"
        return "correct" if ans["cand"] in task["ok_idx"] else "wrong"
    return "false_pick"


def main():
    auth_key = os.environ.get("GIGACHAT_AUTH_KEY", "").strip()
    if not auth_key:
        print("Ошибка: не задан GIGACHAT_AUTH_KEY в .env")
        return

    scope = os.environ.get("GIGACHAT_SCOPE") or os.environ.get("SCOPE") or "GIGACHAT_API_PERS"
    tasks_path = HERE / "tasks_set1.json"
    tasks = json.load(open(tasks_path, encoding="utf-8"))

    client = GigaChat(
        base_url="https://api.giga.chat/v1",
        credentials=auth_key,
        scope=scope,
        verify_ssl_certs=False,
    )

    print(f"Запуск GigaChat-3-Ultra (очищенный промпт), задач: {len(tasks)}")
    rows, lat = [], []
    tin, tout, errs = 0, 0, 0

    for idx, t in enumerate(tasks, 1):
        clean_p = sanitize_prompt(t["prompt"])
        chat = Chat(
            model="GigaChat-3-Ultra",
            messages=[
                Messages(role=MessagesRole.SYSTEM, content=CLEAN_SYSTEM),
                Messages(role=MessagesRole.USER, content=clean_p)
            ],
            temperature=0.01
        )
        t0 = time.time()
        try:
            resp = client.chat(chat)
            dt = time.time() - t0
            content = resp.choices[0].message.content or ""
            u = getattr(resp, "usage", None)
            a = getattr(u, "prompt_tokens", 0) or 0
            b = getattr(u, "completion_tokens", 0) or 0
        except Exception as e:
            dt = time.time() - t0
            errs += 1
            rows.append(dict(task=t["id"], verdict="error", detail=str(e)[:150]))
            print(f"  [{idx}/{len(tasks)}] Ошибка: {e}")
            continue

        ans = parse_answer(content, len(t["cand_nums"]))
        v = judge(t, ans)
        lat.append(dt)
        tin += a
        tout += b
        rows.append(dict(
            task=t["id"], verdict=v, answerable=bool(t["ok_idx"]),
            action=ans and ans["action"], cand=ans and ans["cand"], conf=ans and ans["conf"],
            ok_idx=t["ok_idx"], sec=round(dt, 2),
            reason=(ans or {}).get("reason", content[:120] if content else "")
        ))
        print(f"  [{idx:02d}/{len(tasks)}] вердикт: {v:<8} cand={ans and ans['cand']} conf={ans and ans['conf']} ({dt:.2f}с)")

    outdir = HERE / "results_bench"
    outdir.mkdir(exist_ok=True)
    out_json = outdir / "bench_gigachat_3_ultra_clean__tasks_set1.json"
    json.dump(rows, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    n = len([r for r in rows if r["verdict"] != "error"])
    correct = sum(1 for r in rows if r["verdict"] == "correct")
    wrong = sum(1 for r in rows if r["verdict"] == "wrong")
    missed = sum(1 for r in rows if r["verdict"] == "missed")
    invalid = sum(1 for r in rows if r["verdict"] == "invalid")
    sec_avg = round(statistics.mean(lat), 2) if lat else 0.0

    print("\n--- ИТОГ GIGACHAT-3-ULTRA ---")
    print(f"Всего задач: {len(tasks)}")
    print(f"Верно: {correct} ({correct/len(tasks)*100:.1f}%)")
    print(f"Ошибки: {wrong}")
    print(f"Отказы (missed): {missed}")
    print(f"Невалидный JSON: {invalid}")
    print(f"Ошибки сети: {errs}")
    print(f"Среднее время: {sec_avg}с")
    print(f"Файл сохранен: {out_json}")


if __name__ == "__main__":
    main()
