"""Замер языковых моделей на реальных запросах арбитража прототипа СверкаСмет.

Подготовка (из корня проекта sverka):
    python llmbench/export_tasks.py data/ВОР.xlsx data/ЛСР.xlsx llmbench/tasks_set1.json
    python llmbench/export_tasks.py data/ВОР.xlsx data/ЛСР.xlsx llmbench/tasks_set1_work.json work

Запуск:
    python llmbench/bench.py --tasks llmbench/tasks_set1.json --providers yandex_flash,gigachat_pro
    python llmbench/bench.py --tasks llmbench/tasks_set1_work.json --providers all --repeat 3
    python llmbench/bench.py --tasks llmbench/tasks_set1.json --providers selftest   # без ключей

Ключи берутся из .env (YANDEX_API_KEY, YANDEX_FOLDER_ID, GIGACHAT_AUTH_KEY, CLOUDRU_API_KEY ...).
Цены (₽ за 1 млн токенов, с НДС) задаются в providers.json: сверяйте с актуальными тарифами.
"""
import argparse, json, os, re, sys, time, uuid, statistics, csv
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

sys.path.insert(0, os.getcwd())
try:
    from dotenv import load_dotenv; load_dotenv()
except Exception:
    pass

HERE = Path(__file__).resolve().parent


# ---------- разбор ответа (та же логика, что в llm_resolver.parse_answer) ----------
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


# ---------- клиенты ----------
class OpenAICompat:
    def __init__(self, cfg):
        import openai
        key = os.environ.get(cfg["api_key_env"], "").strip()
        if not key:
            raise RuntimeError(f"нет ключа {cfg['api_key_env']}")
        kw = dict(api_key=key, base_url=cfg["base_url"])
        model = cfg["model"]
        if cfg.get("folder_env"):
            folder = os.environ.get(cfg["folder_env"], "").strip()
            if not folder:
                raise RuntimeError(f"нет {cfg['folder_env']}")
            kw["project"] = folder
            model = model.replace("{folder}", folder)
        self.model = model
        self.client = openai.OpenAI(**kw)

    def ask(self, system, user):
        r = self.client.chat.completions.create(
            model=self.model, temperature=0, max_tokens=1000,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        u = getattr(r, "usage", None)
        return (r.choices[0].message.content or "",
                getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0)


class GigaChat:
    """Прямая работа по REST: OAuth-токен на 30 минут + /chat/completions.
    Сертификат НУЦ Минцифры: путь к корневому сертификату в GIGACHAT_CA_BUNDLE."""
    def __init__(self, cfg):
        import requests
        self.requests = requests
        self.key = os.environ.get(cfg["api_key_env"], "").strip()
        if not self.key:
            raise RuntimeError(f"нет ключа {cfg['api_key_env']}")
        self.scope = os.environ.get("GIGACHAT_SCOPE") or os.environ.get("SCOPE") or "GIGACHAT_API_PERS"
        self.model = cfg["model"]
        self.verify = os.environ.get("GIGACHAT_CA_BUNDLE") or False
        if self.verify is False:
            print("  [GigaChat] ВНИМАНИЕ: GIGACHAT_CA_BUNDLE не задан, проверка сертификата отключена (только для теста)")
            try:
                import urllib3; urllib3.disable_warnings()
            except Exception:
                pass
        self.token, self.exp = None, 0

    def _auth(self):
        if self.token and time.time() < self.exp - 60:
            return
        r = self.requests.post(
            "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            headers={"Authorization": f"Basic {self.key}", "RqUID": str(uuid.uuid4()),
                     "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            data={"scope": self.scope}, verify=self.verify, timeout=30)
        r.raise_for_status()
        j = r.json()
        self.token = j["access_token"]
        self.exp = j.get("expires_at", 0) / 1000 or time.time() + 1700

    def ask(self, system, user):
        self._auth()
        r = self.requests.post(
            "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            json={"model": self.model, "temperature": 0.01, "max_tokens": 1000,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
            verify=self.verify, timeout=90)
        r.raise_for_status()
        j = r.json()
        u = j.get("usage", {})
        return j["choices"][0]["message"]["content"], u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


class Mock:
    """Для самопроверки без ключей: oracle (знает ответ), confirm_all, reject_all."""
    def __init__(self, cfg):
        self.mode = cfg["mode"]; self.model = "mock-" + self.mode; self.task = None

    def ask(self, system, user):
        t = self.task
        if self.mode == "oracle":
            if t["ok_idx"]:
                a = {"action": "REASSIGN", "candidate": t["ok_idx"][0], "confidence": 0.9, "reason": "oracle"}
            else:
                a = {"action": "REJECT", "candidate": None, "confidence": 0.9, "reason": "oracle"}
        elif self.mode == "confirm_all":
            a = {"action": "CONFIRM", "candidate": 1, "confidence": 0.9, "reason": "mock"}
        else:
            a = {"action": "REJECT", "candidate": None, "confidence": 0.9, "reason": "mock"}
        return json.dumps(a), 0, 0


def make_client(cfg):
    return {"openai": OpenAICompat, "gigachat": GigaChat, "mock": Mock}[cfg["type"]](cfg)


# ---------- оценка ----------
def judge(task, ans):
    answerable = bool(task["ok_idx"])
    if ans is None:
        return "invalid"
    if ans["action"] != "REJECT" and ans["conf"] < 0.5:
        return "abstain"                               # низкая уверенность: решает сметчик
    if ans["cand"] is None:                            # отказ
        return "missed" if answerable else "safe_reject"
    if answerable:
        return "correct" if ans["cand"] in task["ok_idx"] else "wrong"
    return "false_pick"


def run_provider(name, cfg, tasks, repeat, outdir):
    client = make_client(cfg)
    rows, lat, tin, tout, errs = [], [], 0, 0, 0
    for rep in range(repeat):
        for t in tasks:
            if isinstance(client, Mock):
                client.task = t
            t0 = time.time()
            try:
                text, a, b = client.ask(t["system"], t["prompt"])
            except Exception as e:
                errs += 1
                rows.append(dict(task=t["id"], rep=rep, verdict="error", detail=str(e)[:150]))
                continue
            dt = time.time() - t0
            ans = parse_answer(text, len(t["cand_nums"]))
            v = judge(t, ans)
            lat.append(dt); tin += a; tout += b
            rows.append(dict(task=t["id"], rep=rep, verdict=v, answerable=bool(t["ok_idx"]),
                             action=ans and ans["action"], cand=ans and ans["cand"], conf=ans and ans["conf"],
                             ok_idx=t["ok_idx"], sec=round(dt, 2), reason=(ans or {}).get("reason", text[:120] if text else "")))
    outdir.mkdir(exist_ok=True)
    json.dump(rows, open(outdir / f"bench_{name}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    n = len([r for r in rows if r["verdict"] != "error"])
    cnt = lambda v, ans=None: sum(1 for r in rows if r["verdict"] == v)
    ans_total = sum(1 for r in rows if r.get("answerable"))
    unans_total = sum(1 for r in rows if r.get("answerable") is False)
    calls = max(n, 1)
    cost = (tin * cfg.get("price_in", 0) + tout * cfg.get("price_out", 0)) / 1e6
    # устойчивость: доля задач, где все повторы дали одинаковый вердикт
    stab = ""
    if repeat > 1:
        by = {}
        for r in rows:
            by.setdefault(r["task"], set()).add(r["verdict"])
        stab = f"{sum(1 for s in by.values() if len(s) == 1)}/{len(by)}"
    return dict(provider=name, model=getattr(client, "model", cfg.get("model", "")), n=n, errors=errs,
                correct=cnt("correct"), wrong=cnt("wrong"), missed=cnt("missed"), abstain=cnt("abstain"),
                invalid=cnt("invalid"), safe_reject=cnt("safe_reject"), false_pick=cnt("false_pick"),
                answerable=ans_total, unanswerable=unans_total,
                sec_avg=round(statistics.mean(lat), 2) if lat else None,
                sec_p95=round(sorted(lat)[int(len(lat) * 0.95) - 1], 2) if len(lat) >= 5 else None,
                tok_in_avg=round(tin / calls), tok_out_avg=round(tout / calls),
                cost_run=round(cost / repeat, 3), cost_per_call=round(cost / calls, 4), stable=stab)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--providers", default="selftest")
    ap.add_argument("--config", default=str(HERE / "providers.json"))
    ap.add_argument("--repeat", type=int, default=1)
    a = ap.parse_args()

    tasks = json.load(open(a.tasks, encoding="utf-8"))
    cfgs = json.load(open(a.config, encoding="utf-8"))
    if a.providers == "selftest":
        names = [k for k in cfgs if k.startswith("mock_")]
    elif a.providers == "all":
        names = [k for k in cfgs if not k.startswith("mock_")]
    else:
        names = a.providers.split(",")
    print(f"Задач: {len(tasks)} (с верным ответом среди кандидатов: {sum(1 for t in tasks if t['ok_idx'])}); повторов: {a.repeat}")
    res = []
    for n in names:
        print(f"-> {n} ...", flush=True)
        try:
            res.append(run_provider(n, cfgs[n], tasks, a.repeat, Path(a.tasks).resolve().parent / "results_bench"))
        except Exception as e:
            print(f"   пропущено: {e}")
    cols = ["provider", "correct", "wrong", "missed", "abstain", "invalid", "safe_reject", "false_pick", "errors",
            "sec_avg", "tok_in_avg", "tok_out_avg", "cost_run", "stable"]
    print("\n" + "  ".join(f"{c:>11}" for c in cols))
    for r in res:
        print("  ".join(f"{str(r[c]):>11}" for c in cols))
    if res:
        r0 = res[0]
        print(f"\nВсего: с верным ответом среди кандидатов {r0['answerable']}, без него {r0['unanswerable']} (за один повтор делите на {a.repeat}).")
        print("correct — выбрана верная строка; wrong — выбрана другая; missed — отказ при верной строке в списке;")
        print("abstain — низкая уверенность (решает сметчик); safe_reject — верной строки нет в списке и модель отказалась;")
        print("false_pick — верной строки нет в списке, но модель выбрала другую; cost_run — стоимость одного прогона, руб.")
        out = Path(a.tasks).resolve().parent / "results_bench" / "summary.csv"
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(res[0].keys()), delimiter=";"); w.writeheader(); w.writerows(res)
        print("Сводка:", out)


if __name__ == "__main__":
    main()
