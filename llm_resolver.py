"""Модуль сопоставления и арбитража спорных позиций с помощью Алисы (Yandex AI Studio).

Реализует двухуровневую гибридную архитектуру:
1. Уровень 1: SmartMatcher выполняет детерминированное сопоставление и выявляет неоднозначности.
2. Уровень 2: Алиса привлекается в качестве эксперта-арбитра для разрешения коллизий:
   - конкуренция близких кандидатов-двойников;
   - скрытые расхождения характеристик (сечения, диаметры, марки);
   - скачки объёмов при схожем тексте;
   - сопоставление позиций со слабым текстовым сходством.
"""
import os
import re
import json
import time
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Callable

_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except Exception:
        for _line in _env_path.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))

try:
    import openai
except ImportError:
    raise SystemExit('Не установлена библиотека openai. Выполните: pip install openai python-dotenv')

from parsers import Item
from match import similarity, evaluate_pair

DEFAULT_FOLDER = ""
DEFAULT_MODEL = "aliceai-llm-flash/latest"
BASE_URL = "https://ai.api.cloud.yandex.net/v1"

SYSTEM_PROMPT_ARBITRATION = (
    "Ты ведущий инженер-эксперт по сметному аудиту и ценообразованию в строительстве. "
    "Твоя задача — арбитраж спорных и неоднозначных позиций между Ведомостью объёмов работ (ВОР) "
    "и Локальным сметным расчётом (ЛСР).\n\n"
    "Тебе передают позицию ВОР, предварительный выбор алгоритма сопоставления, выявленное противоречие "
    "(конкуренция двойников, расхождение объёма, различие характеристик или разделов) и список кандидатов сметы.\n\n"
    "Ты должен принять одно из трёх экспертных решений (action):\n"
    "1. 'CONFIRM' — подтвердить текущего кандидата алгоритма (если расхождение допустимо, является проектной неточностью или обусловлено сметными нормативами);\n"
    "2. 'REASSIGN' — переназначить на другого кандидата из списка (укажи 'candidate': <номер 1..K>), если он точнее соответствует технологии, разделу или характеристикам;\n"
    "3. 'REJECT' — отклонить все варианты ('candidate': null), если ни один кандидат технологически не соответствует работе.\n\n"
    "Отвечай СТРОГО в формате JSON:\n"
    '{"action": "CONFIRM"|"REASSIGN"|"REJECT", "candidate": <номер 1..K или null>, "confidence": <0.0..1.0>, "reason": "<краткое экспертное обоснование>"}'
)

SYSTEM_PROMPT_LEGACY = (
    "Ты помощник инженера-сметчика. Тебе дают позицию из ведомости объёмов работ (ВОР) и "
    "пронумерованные строки из локального сметного расчёта (ЛСР). Выбери строку ЛСР, которая "
    "технологически описывает ту же работу или материал. В смете часто используются обобщённые "
    "нормативные названия (например «Прибор или аппарат»), а в ВОР - конкретные названия. "
    "Единицы могут отличаться масштабом (м2 и 100 м2) - это не мешает совпадению. "
    "Если ни одна строка уверенно не подходит, укажи candidate: null. Ничего не выдумывай. "
    "Отвечай ТОЛЬКО в формате JSON: "
    '{"candidate": <номер или null>, "confidence": <0..1>, "reason": "<краткое объяснение>"}'
)


class YandexClient:
    """Простой клиент для работы с Алисой через официальную библиотеку openai."""

    def __init__(self, api_key: Optional[str] = None, folder_id: Optional[str] = None, model: Optional[str] = None):
        self.api_key = (api_key or os.environ.get("YANDEX_API_KEY") or
                        os.environ.get("YANDEX_CLOUD_API_KEY") or "").strip()
        self.folder_id = (folder_id or os.environ.get("YANDEX_FOLDER_ID") or
                          os.environ.get("YANDEX_CLOUD_FOLDER") or DEFAULT_FOLDER).strip()
        model_name = (model or os.environ.get("YANDEX_MODEL") or
                      os.environ.get("YANDEX_CLOUD_MODEL") or DEFAULT_MODEL).strip()

        if not self.api_key or not self.folder_id:
            raise RuntimeError(
                "Не заданы ключ или каталог Yandex Cloud. Откройте файл .env в папке sverka и впишите:\n"
                "  YANDEX_API_KEY=ваш_ключ\n  YANDEX_FOLDER_ID=идентификатор_каталога"
            )

        self.model = f"gpt://{self.folder_id}/{model_name}" if not model_name.startswith("gpt://") else model_name

        self.client = openai.OpenAI(
            api_key=self.api_key,
            base_url=BASE_URL,
            project=self.folder_id,
        )

    def ask(self, system: str, user: str) -> str:
        """Отправляет запрос к модели Алисы."""
        try:
            resp = self.client.responses.create(
                model=self.model,
                temperature=0,
                instructions=system,
                input=user,
                max_output_tokens=1000,
            )
            if hasattr(resp, "output_text") and resp.output_text:
                return resp.output_text
            if hasattr(resp, "output") and resp.output:
                return resp.output[0].text
        except Exception:
            pass

        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            max_tokens=1000,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ]
        )
        return resp.choices[0].message.content


def _fmt(item: Item) -> str:
    qty_str = f"{item.qty:g}" if item.qty is not None else "не указано"
    code_str = f"; шифр: {item.code}" if getattr(item, "code", "") else ""
    sec_str = f"; раздел: {item.section}" if getattr(item, "section", "") else ""
    return f"«{item.name}»; единица: {item.unit}; количество: {qty_str}{sec_str}{code_str}"


def build_prompt(v: Item, cands: List[Item], cur_cand: Optional[Item] = None,
                 conflict_reason: str = "", ambiguity_type: str = "") -> str:
    """Формирует объяснимый промпт для арбитража с контекстом разделов и коллизий."""
    lines = [f"Позиция ВОР: {_fmt(v)}", ""]
    if cur_cand is not None:
        lines.extend([
            f"Предварительный выбор алгоритма (Кандидат №1): {_fmt(cur_cand)}",
            f"Выявленная коллизия: {conflict_reason or 'Неоднозначность сопоставления'}",
            ""
        ])

    lines.append("Варианты расценок из сметы ЛСР:")
    for n, c in enumerate(cands, 1):
        lines.append(f"{n}. {_fmt(c)}")
    lines.append("")
    lines.append(
        "Какое экспертное решение принять? Подтвердить выбор алгоритма ('CONFIRM'), "
        "переназначить на другого кандидата ('REASSIGN') или отклонить ('REJECT')? "
        "Ответь строго JSON-объектом: {\"action\": \"CONFIRM\"|\"REASSIGN\"|\"REJECT\", \"candidate\": <1..K или null>, \"confidence\": <0..1>, \"reason\": \"<причина>\"}"
    )
    return "\n".join(lines)


def parse_answer(text: str, k: int):
    """Извлекает выбранный номер, уверенность, причину и действие."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None

    if not isinstance(obj, dict):
        return None

    VALID_ACTIONS = {"CONFIRM", "REASSIGN", "REJECT"}
    raw_action = str(obj.get("action", "")).upper().strip()
    cand = obj.get("candidate")
    if cand is not None:
        try:
            cand = int(cand)
        except (TypeError, ValueError):
            cand = None
        if cand is not None and not (1 <= cand <= k):
            return None

    try:
        conf = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    reason = str(obj.get("reason", ""))[:300]

    if raw_action in VALID_ACTIONS:
        action = raw_action
    elif not raw_action:
        # Для обратной совместимости со старыми записями кэша без поля action:
        if cand is None:
            action = "REJECT"
        else:
            action = "CONFIRM" if cand == 1 else "REASSIGN"
    else:
        # Неизвестное значение действия строго отклоняется как некорректное
        return None

    if action == "CONFIRM":
        cand = 1
    elif action == "REASSIGN":
        if cand is None:
            return None
    elif action == "REJECT":
        cand = None

    return cand, conf, reason, action


class Cache:
    """Кэширует ответы Алисы в файл, чтобы не тратить запросы повторно."""
    def __init__(self, path="results/llm_cache.json"):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.data: Dict[str, str] = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.data = {}

    def get(self, key):
        with self.lock:
            return self.data.get(key)

    def put(self, key, value):
        with self.lock:
            self.data[key] = value
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")


def model_only_results(vor: List[Item], lsr: List[Item]) -> List[Dict[str, Any]]:
    """Начальное состояние для режима 'только модель'."""
    res = [dict(vor=v.num, lsr=None, cls="Нет в рассматриваемой смете", score=0.0, text_sim=0.0,
                explanation="", vor_item=v, lsr_item=None, vor_row=v.row, lsr_row=None,
                is_ambiguous=True, ambiguity_type="unmatched", conflict_reason="Режим прямой оценки моделью",
                competing_candidates=[]) for v in vor]
    res += [dict(vor=None, lsr=l.num, cls="Нет в ВОР", score=0.0, text_sim=0.0, explanation="",
                 vor_item=None, lsr_item=l, vor_row=None, lsr_row=l.row,
                 is_ambiguous=False, ambiguity_type=None, conflict_reason="",
                 competing_candidates=[]) for l in lsr]
    return res


def resolve(results: List[Dict[str, Any]], vor: List[Item], lsr: List[Item], client,
            mode: str = "arbitration",
            weak_text: float = 0.45, top_k: int = 5, min_conf: float = 0.5,
            prune_threshold: float = 0.20,
            max_workers: int = 5,
            cache_path: str = "results/llm_cache.json", verbose: bool = True,
            progress_callback: Optional[Callable[[int, int, Dict[str, Any]], None]] = None):
    """Арбитраж и уточнение спорных позиций с помощью Алисы.

    Режимы (mode):
    - 'arbitration': Двухуровневый гибрид (проверка коллизий, конкуренции и слабых пар).
    - 'weak_only': Базовый режим (обращение только при text_sim < weak_text или отсутствии пары).
    - 'model_only': Прямое сопоставление позиций моделью.
    """
    cache = Cache(cache_path)
    t0 = time.time()
    stats = {
        "calls": 0, "cache_hits": 0, "accepted": 0, "confirmed": 0,
        "reassigned": 0, "rejected": 0, "said_null": 0, "invalid": 0,
        "errors": 0, "ambiguities_checked": 0, "unverified": 0, "pruned": 0
    }

    vi = {id(v): i for i, v in enumerate(vor)}
    li = {id(l): j for j, l in enumerate(lsr)}
    sim = similarity(vor, lsr)

    vor_by_num = {str(v.num): v for v in vor}
    lsr_by_num = {str(l.num): l for l in lsr}

    out = []
    for r in results:
        if r.get("vor_item") is None and r.get("vor") is None:
            continue
        r = dict(r)
        if r.get("vor_item") is None:
            r["vor_item"] = vor_by_num.get(str(r["vor"]))
        if r.get("lsr_item") is None and r.get("lsr") is not None:
            r["lsr_item"] = lsr_by_num.get(str(r["lsr"]))
        if r["vor_item"] is None:
            continue
        if "text_sim" not in r:
            r["text_sim"] = (float(sim[vi[id(r["vor_item"])], li[id(r["lsr_item"])]])
                             if r.get("lsr_item") is not None else 0.0)
        out.append(r)

    taken = {li[id(r["lsr_item"])]: r for r in out if r.get("lsr_item") is not None and r["cls"] != "Дубль"}
    free = [j for j in range(len(lsr)) if j not in taken]

    system_prompt = SYSTEM_PROMPT_ARBITRATION if mode == "arbitration" else SYSTEM_PROMPT_LEGACY

    tasks = []
    for r in out:
        v = r["vor_item"]
        i = vi[id(v)]
        cur_j = li[id(r["lsr_item"])] if r.get("lsr_item") is not None else None

        # Определение необходимости обращения к модели:
        unmatched = (r["cls"] == "Нет в рассматриваемой смете" and cur_j is None)
        weak = (cur_j is not None and r["cls"] != "Дубль" and float(r.get("text_sim", 1.0)) < weak_text)
        ambig = bool(mode == "arbitration" and r.get("is_ambiguous", False) and r["cls"] != "Дубль")

        if not (unmatched or weak or ambig):
            continue

        # Smart Pruning (Этап 1):
        # Если максимальное сходство со всей сметой < prune_threshold (0.20),
        # в смете гарантированно нет подходящей расценки. Не отправляем в модель заведомый отказ.
        max_sim_for_row = float(sim[i].max()) if len(lsr) > 0 else 0.0
        if max_sim_for_row < prune_threshold and mode != "model_only":
            stats["pruned"] += 1
            if cur_j is None:
                r["explanation"] = f"В смете ЛСР нет подходящей расценки (макс. сходство {max_sim_for_row:.2f} < {prune_threshold:.2f})"
                r["ai_decision"] = "Отсечено Smart Pruning (<0.20)"
            else:
                r["cls"] = "Кандидат — требуется проверка"
                r["explanation"] = f"{r.get('explanation', '')}; Крайне низкое сходство со сметой ({max_sim_for_row:.2f} < {prune_threshold:.2f}) — требуется проверка".strip("; ")
                r["ai_decision"] = "Отсечено Smart Pruning (<0.20, на проверку)"
            continue

        stats["ambiguities_checked"] += 1

        # Формирование пула кандидатов
        pool = sorted(free, key=lambda j: -sim[i, j])[:top_k - (1 if cur_j is not None else 0)]
        cand_idx = ([cur_j] if cur_j is not None else []) + pool
        if not cand_idx:
            continue

        prompt = build_prompt(
            v=v,
            cands=[lsr[j] for j in cand_idx],
            cur_cand=lsr[cur_j] if cur_j is not None else None,
            conflict_reason=r.get("conflict_reason", ""),
            ambiguity_type=r.get("ambiguity_type", "")
        )

        cache_key = hashlib.sha1(
            (getattr(client, "model", "") + "\n" + system_prompt + "\n" + prompt).encode("utf-8")
        ).hexdigest()

        tasks.append({
            "r": r,
            "v": v,
            "i": i,
            "cur_j": cur_j,
            "cand_idx": cand_idx,
            "prompt": prompt,
            "cache_key": cache_key,
            "weak": weak
        })

    # Сбор ответов: из кэша либо параллельными сетевыми запросами
    uncached = []
    responses = {}

    for t in tasks:
        cached_text = cache.get(t["cache_key"])
        if cached_text:
            stats["cache_hits"] += 1
            responses[t["cache_key"]] = cached_text
        else:
            uncached.append(t)

    total_tasks = len(tasks)
    cached_count = len(tasks) - len(uncached)
    if progress_callback and cached_count > 0:
        try:
            progress_callback(cached_count, total_tasks, {
                "message": f"Извлечено из кэша: {cached_count} из {total_tasks}"
            })
        except Exception:
            pass

    if uncached:
        def _fetch(t):
            try:
                res = client.ask(system_prompt, t["prompt"])
                return t["cache_key"], res, None, t
            except Exception as e:
                return t["cache_key"], None, e, t

        actual_workers = min(len(uncached), max_workers) if max_workers > 1 else 1
        with ThreadPoolExecutor(max_workers=actual_workers) as executor:
            fut_map = {executor.submit(_fetch, t): t for t in uncached}
            done_count = cached_count
            for fut in as_completed(fut_map):
                ck, ans, err, t = fut.result()
                done_count += 1
                if err:
                    stats["errors"] += 1
                    if verbose:
                        print(f"  Ошибка запроса к ИИ: {err}")
                elif ans:
                    stats["calls"] += 1
                    responses[ck] = ans
                    cache.put(ck, ans)
                if progress_callback:
                    try:
                        progress_callback(done_count, total_tasks, {
                            "vor_num": str(t["v"].num),
                            "name": t["v"].name,
                            "error": bool(err)
                        })
                    except Exception:
                        pass

    # Применение экспертных решений арбитра с детерминированным разрешением коллизий
    evaluated_tasks = []
    for t in tasks:
        ans_text = responses.get(t["cache_key"])
        if not ans_text:
            continue

        parsed = parse_answer(ans_text, len(t["cand_idx"]))
        if not parsed:
            stats["invalid"] += 1
            continue

        pick, conf, reason, action = parsed
        t["pick"] = pick
        t["conf"] = conf
        t["reason"] = reason
        t["action"] = action
        t["new_j"] = t["cand_idx"][pick - 1] if pick is not None else None
        t["resolved"] = False
        evaluated_tasks.append(t)

    # Фаза 1: Обработка явных отказов (REJECT) и низкой уверенности модели
    for t in evaluated_tasks:
        cur_j = t["cur_j"]
        conf = t["conf"]
        reason = t["reason"]
        action = t["action"]
        r = t["r"]

        # Вариант A: Явный отказ с достаточной уверенностью (action == "REJECT" и conf >= min_conf)
        if action == "REJECT" and conf >= min_conf:
            stats["rejected"] += 1
            stats["said_null"] += 1
            if cur_j is not None:
                if cur_j not in free:
                    free.append(cur_j)
                taken.pop(cur_j, None)
                r.update(
                    lsr=None, lsr_item=None, lsr_row=None,
                    cls="Нет в рассматриваемой смете",
                    explanation=f"ИИ-арбитр отклонил совпадение ({reason})",
                    ai_decision="Отклонено ИИ",
                    ai_reason=reason
                )
            else:
                r["ai_decision"] = "Отклонено ИИ"
                r["ai_reason"] = reason
            t["resolved"] = True

        # Вариант B: Низкая уверенность модели (conf < min_conf) или отказ с низкой уверенностью
        elif conf < min_conf or t["pick"] is None or action == "REJECT":
            stats["unverified"] += 1
            # Единое детерминированное поведение:
            # Если у SmartMatcher была исходная пара (cur_j is not None), мы её сохраняем
            # как непроверенную для ручного решения сметчика (BPMN human-in-the-loop).
            # В статистике rejected НЕ увеличивается, said_null НЕ увеличивается.
            if cur_j is not None:
                r["cls"] = "Кандидат — требуется проверка"
                expl_note = (f"Низкая уверенность ИИ ({conf:.2f}): {reason}"
                             if conf < min_conf else f"ИИ не подтвердил пару: {reason}")
                r["explanation"] = f"{r.get('explanation', '')}; {expl_note}".strip("; ")
                r["ai_decision"] = "Требует решения сметчика (низкая уверенность ИИ)"
                r["ai_reason"] = reason
            else:
                # Позиция изначально была без пары и модель не смогла уверенно подобрать кандидата
                stats["said_null"] += 1
                r["cls"] = "Нет в рассматриваемой смете"
                expl_note = f"ИИ не подобрал пару с достаточной уверенностью ({conf:.2f}): {reason}"
                r["explanation"] = f"{r.get('explanation', '')}; {expl_note}".strip("; ")
                r["ai_decision"] = "Не подобрано ИИ (низкая уверенность)"
                r["ai_reason"] = reason
            t["resolved"] = True

    # Фаза 2: Обработка подтверждений (CONFIRM)
    # Позиции подтверждают свои исходные расценки (уже уникальные из SmartMatcher)
    for t in evaluated_tasks:
        if t["resolved"]:
            continue
        cur_j = t["cur_j"]
        new_j = t["new_j"]
        action = t["action"]
        r = t["r"]

        if cur_j is not None and (action == "CONFIRM" or new_j == cur_j):
            stats["confirmed"] += 1
            r["explanation"] = f"{r.get('explanation', '')}; ИИ-арбитр подтвердил выбор ({t['reason']})".strip("; ")
            r["ai_decision"] = "Подтверждено ИИ"
            r["ai_reason"] = t["reason"]
            t["resolved"] = True

    # Фаза 3: Разрешение переназначений и новых назначений по приоритету уверенности
    # Исключает зависимость результата от порядка обхода строк
    reassign_tasks = [t for t in evaluated_tasks if not t["resolved"]]

    # Временно освобождаем cur_j у тех, кто хочет переназначиться на другую расценку
    for t in reassign_tasks:
        cur_j = t["cur_j"]
        if cur_j is not None:
            if cur_j not in free:
                free.append(cur_j)
            taken.pop(cur_j, None)

    # Сортируем претендентов по убыванию уверенности модели и текстового сходства
    def _priority_key(t):
        v_num_val = 0.0
        try:
            v_num_val = float(re.sub(r"[^\d.]", "", str(t["v"].num)))
        except Exception:
            pass
        return (
            t["conf"],
            float(sim[t["i"], t["new_j"]]) if t["new_j"] is not None else 0.0,
            -v_num_val
        )

    reassign_tasks.sort(key=_priority_key, reverse=True)

    for t in reassign_tasks:
        r = t["r"]
        v = t["v"]
        i = t["i"]
        cur_j = t["cur_j"]
        new_j = t["new_j"]
        conf = t["conf"]
        reason = t["reason"]

        if new_j is not None and new_j in free:
            free.remove(new_j)
            l = lsr[new_j]
            cand = evaluate_pair(v, l, float(sim[i, new_j]))
            act_name = "Пару подобрала Алиса" if cur_j is None else "Пару переназначил ИИ-арбитр"
            r.update(
                lsr=l.num,
                lsr_item=l,
                lsr_row=l.row,
                cls=cand.classification,
                score=round(conf, 4),
                text_sim=round(float(sim[i, new_j]), 4),
                explanation=f"{act_name} ({reason}); {cand.explanation}",
                ai_decision="Подобрано ИИ" if cur_j is None else "Переназначено ИИ",
                ai_reason=reason
            )
            taken[new_j] = r
            if cur_j is None:
                stats["accepted"] += 1
            else:
                stats["reassigned"] += 1
                stats["accepted"] += 1
        else:
            # Коллизия: желаемая расценка уже занята более приоритетным сопоставлением
            if cur_j is not None and cur_j in free:
                # Возвращаем исходную расценку
                free.remove(cur_j)
                taken[cur_j] = r
                r["explanation"] = (
                    f"{r.get('explanation', '')}; ИИ предложил смету №{lsr[new_j].num if new_j is not None else '—'}, "
                    f"но она занята с более высокой уверенностью. Сохранен исходный выбор"
                ).strip("; ")
                r["ai_decision"] = "Коллизия назначения (сохранен выбор)"
            else:
                r["cls"] = "Кандидат — требуется проверка"
                r["explanation"] = (
                    f"{r.get('explanation', '')}; ИИ рекомендовал смету №{lsr[new_j].num if new_j is not None else '—'}, "
                    f"но позиция занята более приоритетным соответствием"
                ).strip("; ")
                r["ai_decision"] = "Коллизия назначения"

    for j in sorted(set(range(len(lsr))) - set(taken)):
        l = lsr[j]
        out.append(dict(
            vor=None, lsr=l.num, cls="Нет в ВОР", score=0.0, text_sim=0.0,
            explanation="Сметная расценка отсутствует в ведомости объемов работ",
            vor_item=None, lsr_item=l, vor_row=None, lsr_row=l.row,
            is_ambiguous=False, ambiguity_type=None, conflict_reason="",
            competing_candidates=[]
        ))

    stats["seconds"] = round(time.time() - t0, 1)
    return out, stats
