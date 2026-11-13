"""Проверки защит вокруг модели. Сеть и ключ не нужны: вместо модели подставляется заглушка.
Эти тесты проверяют КОД (что он не доверяет модели вслепую), а не качество самой модели."""
import json
import sys
import types
import unittest
import uuid
from pathlib import Path

try:
    import openai  # noqa: F401
except ImportError:                       # тесты не требуют настоящей библиотеки
    sys.modules['openai'] = types.ModuleType('openai')

from parsers import Item
import match
from llm_resolver import resolve, parse_answer, model_only_results, YandexClient


class Fake:
    model = "fake"
    def __init__(self, fn): self.fn, self.n = fn, 0
    def ask(self, system, user):
        self.n += 1
        return self.fn(user)


class _FallbackClient:
    def __init__(self, response_error=None, chat_error=None):
        self.response_error = response_error
        self.chat_error = chat_error
        self.chat_calls = 0
        self.responses = types.SimpleNamespace(create=self._responses_create)
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._chat_create))

    def _responses_create(self, **kwargs):
        if self.response_error:
            raise self.response_error
        return types.SimpleNamespace(output_text="ответ")

    def _chat_create(self, **kwargs):
        self.chat_calls += 1
        if self.chat_error:
            raise self.chat_error
        msg = types.SimpleNamespace(content="резервный ответ")
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])


def pick_by_word(word):
    def f(user):
        for line in user.splitlines():
            if line[:1].isdigit() and ". «" in line and word in line:
                return json.dumps({"candidate": int(line.split(".")[0]), "confidence": 0.9, "reason": "тест"})
        return '{"candidate": null, "confidence": 0.2, "reason": "нет"}'
    return f


def mk():
    vor = [Item('VOR', 1, '1', '', 'Монтаж щита распределительного', 'шт', 2.0),
           Item('VOR', 2, '2', '', 'Прибор приёмно-контрольный охранный', 'шт', 3.0)]
    lsr = [Item('LSR', 1, '1', 'Ф1', 'Монтаж щита распределительного', 'шт', 2.0),
           Item('LSR', 2, '2', 'Ф2', 'Прибор или аппарат', 'шт', 3.0),
           Item('LSR', 3, '3', 'Ф3', 'Кабель силовой', 'м', 10.0)]
    return vor, lsr


def base(vor, lsr):
    return match.match(vor, lsr, thr=0.50, min_text_threshold=0.20)


class T(unittest.TestCase):
    def setUp(self):
        self.cache_files = []
        self.cache = self._cache_file("llm_test_cache")
        self.vor, self.lsr = mk()
        self.base = base(self.vor, self.lsr)

    def _cache_file(self, prefix):
        path = Path(__file__).resolve().parent / f".{prefix}_{uuid.uuid4().hex}.json"
        self.cache_files.append(path)
        return str(path)

    def tearDown(self):
        for path in self.cache_files:
            path.unlink(missing_ok=True)

    def run_resolve(self, cli, **kw):
        return resolve(self.base, self.vor, self.lsr, cli, cache_path=self.cache, verbose=False, **kw)

    def test_model_links_generic_name(self):
        cli = Fake(pick_by_word("аппарат"))
        res, st = self.run_resolve(cli)
        self.assertEqual(next(r for r in res if r["vor"] == "2")["lsr"], "2")
        left = {r["lsr"] for r in res if r["cls"] == "Нет в ВОР"}
        self.assertNotIn("2", left); self.assertIn("3", left)

    def test_number_outside_list_is_ignored(self):
        _, st = self.run_resolve(Fake(lambda u: '{"candidate": 9, "confidence": 1, "reason": "x"}'))
        self.assertEqual(st["accepted"], 0); self.assertGreaterEqual(st["invalid"], 1)

    def test_low_confidence_rejected(self):
        _, st = self.run_resolve(Fake(lambda u: '{"candidate": 1, "confidence": 0.2, "reason": "x"}'))
        self.assertEqual(st["accepted"], 0)

    def test_text_confidence_does_not_crash(self):
        # раньше «confidence»: «высокая» валило программу
        _, st = self.run_resolve(Fake(lambda u: '{"candidate": 1, "confidence": "высокая", "reason": "x"}'))
        self.assertEqual(st["accepted"], 0)

    def test_garbage_and_network_errors(self):
        b = self.base
        _, st = self.run_resolve(Fake(lambda u: "не знаю"))
        self.assertGreaterEqual(st["invalid"], 1)
        self.cache = self._cache_file("llm_test_cache")   # чистый кэш
        def boom(u): raise RuntimeError("сеть")
        with self.assertLogs('llm_resolver', level='ERROR') as captured:
            res, st = self.run_resolve(Fake(boom))
        self.assertGreaterEqual(st["errors"], 1); self.assertEqual(len(res), len(b))
        failed = next(r for r in res if r.get('vor') == '2')
        self.assertEqual(failed['ai_decision'], 'Модель не ответила')
        self.assertIn('сеть', failed['ai_reason'])
        self.assertTrue(any('позиции ВОР' in line for line in captured.output))

    def test_yandex_fallback_succeeds_after_first_interface_fails(self):
        client = YandexClient.__new__(YandexClient)
        fake = _FallbackClient(response_error=RuntimeError('responses недоступен'))
        client.client = fake
        client.model = 'fake-model'
        client.total_input_tokens = 0
        client.total_output_tokens = 0
        client._tokens_lock = __import__('threading').Lock()

        self.assertEqual(client.ask('system', 'user'), 'резервный ответ')
        self.assertEqual(fake.chat_calls, 1)

    def test_yandex_raises_when_both_interfaces_fail(self):
        client = YandexClient.__new__(YandexClient)
        fake = _FallbackClient(
            response_error=RuntimeError('responses упал'),
            chat_error=RuntimeError('chat упал')
        )
        client.client = fake
        client.model = 'fake-model'
        client.total_input_tokens = 0
        client.total_output_tokens = 0
        client._tokens_lock = __import__('threading').Lock()

        with self.assertLogs('llm_resolver', level='ERROR'):
            with self.assertRaisesRegex(RuntimeError, 'chat упал'):
                client.ask('system', 'user')
        self.assertEqual(fake.chat_calls, 1)

    def test_cache_avoids_second_call(self):
        c1 = Fake(pick_by_word("аппарат")); self.run_resolve(c1)
        c2 = Fake(pick_by_word("аппарат")); _, st = self.run_resolve(c2)
        self.assertEqual(c2.n, 0); self.assertGreaterEqual(st["cache_hits"], 1)

    def test_cache_depends_on_model(self):
        c1 = Fake(pick_by_word("аппарат")); self.run_resolve(c1)
        c2 = Fake(pick_by_word("аппарат")); c2.model = "другая модель"
        self.run_resolve(c2)
        self.assertGreater(c2.n, 0)       # другая модель не должна брать чужие ответы

    def test_parse_answer(self):
        self.assertEqual(parse_answer('текст {"candidate": 2, "confidence": 0.7, "reason": "ok"} ещё', 3)[0], 2)
        self.assertIsNone(parse_answer('{"candidate": 4}', 3))
        self.assertIsNone(parse_answer('[1, 2]', 3))
        # Проверка строгой валидации допустимых действий:
        # 1) неизвестное действие без кандидата
        self.assertIsNone(parse_answer('{"action": "INVALID_CMD", "reason": "test"}', 3))
        # 2) неизвестное действие даже если указан кандидат (должно строго отклоняться)
        self.assertIsNone(parse_answer('{"action": "MAYBE", "candidate": 1, "confidence": 0.9}', 3))
        # 3) допустимые действия валидируются корректно
        self.assertEqual(parse_answer('{"action": "CONFIRM", "confidence": 0.9}', 3)[3], "CONFIRM")
        self.assertEqual(parse_answer('{"action": "REJECT", "confidence": 0.9}', 3)[3], "REJECT")
        self.assertEqual(parse_answer('{"action": "REASSIGN", "candidate": 2, "confidence": 0.9}', 3)[3], "REASSIGN")
        # REASSIGN без кандидата не допускается
        self.assertIsNone(parse_answer('{"action": "REASSIGN", "candidate": null, "confidence": 0.9}', 3))

    def test_low_confidence_preserves_pair_as_unverified(self):
        # При низкой уверенности пара должна сохраняться с переводом в "Кандидат — требуется проверка"
        b = [dict(self.base[0])]
        b[0]["is_ambiguous"] = True
        b[0]["conflict_reason"] = "Слабая уверенность"
        fake_cli = Fake(lambda u: '{"action": "REASSIGN", "candidate": 2, "confidence": 0.30, "reason": "сомневаюсь"}')
        res, st = resolve(b, self.vor[:1], self.lsr, fake_cli, mode="arbitration",
                          min_conf=0.50, cache_path=self.cache, verbose=False)
        self.assertEqual(st.get("unverified", 0), 1)
        self.assertEqual(st.get("rejected", 0), 0)
        self.assertEqual(st.get("said_null", 0), 0)  # исходная пара не сброшена, значит не said_null!
        self.assertEqual(res[0]["cls"], "Кандидат — требуется проверка")
        self.assertIn("низкая уверенность", res[0]["ai_decision"].lower())
        self.assertIsNotNone(res[0]["lsr"])  # исходная пара не удалена!

    def test_low_confidence_unmatched_stays_unmatched(self):
        # Если позиция изначально не имела пары, при низкой уверенности она остаётся без пары
        vor_unmatched = [Item('VOR', 1, '99', '', 'Совершенно уникальная работа', 'шт', 1.0)]
        b = [{
            "vor": "99", "lsr": None, "cls": "Нет в рассматриваемой смете", "score": 0.0,
            "text_sim": 0.0, "explanation": "", "vor_item": vor_unmatched[0], "lsr_item": None,
            "vor_row": 1, "lsr_row": None, "is_ambiguous": True, "ambiguity_type": "unmatched"
        }]
        fake_cli = Fake(lambda u: '{"action": "REASSIGN", "candidate": 1, "confidence": 0.25, "reason": "не уверен"}')
        res, st = resolve(b, vor_unmatched, self.lsr, fake_cli, mode="arbitration",
                          min_conf=0.50, prune_threshold=0.0, cache_path=self.cache, verbose=False)
        self.assertEqual(st.get("unverified", 0), 1)
        self.assertEqual(st.get("said_null", 0), 1)
        self.assertIsNone(res[0]["lsr"])
        self.assertEqual(res[0]["cls"], "Нет в рассматриваемой смете")

    def test_smart_pruning_filters_hopeless_positions(self):
        # Позиция с максимальным сходством < 0.20 отсекается до вызова модели
        vor_hopeless = [Item('VOR', 1, '100', '', 'Абсолютно чуждый текст zzz999', 'шт', 1.0)]
        b = [{
            "vor": "100", "lsr": None, "cls": "Нет в рассматриваемой смете", "score": 0.0,
            "text_sim": 0.0, "explanation": "", "vor_item": vor_hopeless[0], "lsr_item": None,
            "vor_row": 1, "lsr_row": None, "is_ambiguous": True, "ambiguity_type": "unmatched"
        }]
        cli = Fake(lambda u: '{"action": "REJECT", "candidate": null, "confidence": 1.0}')
        res, st = resolve(b, vor_hopeless, self.lsr, cli, mode="arbitration",
                          prune_threshold=0.20, cache_path=self.cache, verbose=False)
        self.assertEqual(cli.n, 0)  # Модель не вызывалась!
        self.assertEqual(st.get("pruned", 0), 1)
        self.assertIn("< 0.20", res[0]["explanation"])

    def test_model_only_mode(self):
        vor, lsr = self.vor, self.lsr
        res, st = resolve(model_only_results(vor, lsr), vor, lsr, Fake(pick_by_word("щита")),
                          cache_path=self.cache, verbose=False)
        self.assertEqual(next(r for r in res if r["vor"] == "1")["lsr"], "1")

    def test_arbitration_confirm_action(self):
        # Проверяем подтверждение решения алгоритма экспертом-Алисой
        b = [dict(self.base[0])]
        b[0]["is_ambiguous"] = True
        b[0]["conflict_reason"] = "Расхождение объема при сходном тексте"
        fake_cli = Fake(lambda u: '{"action": "CONFIRM", "candidate": 1, "confidence": 0.95, "reason": "Обосновано"}')
        res, st = resolve(b, self.vor[:1], self.lsr, fake_cli, mode="arbitration",
                          cache_path=self.cache, verbose=False)
        self.assertEqual(st["confirmed"], 1)
        self.assertEqual(res[0]["ai_decision"], "Подтверждено ИИ")

    def test_arbitration_reassign_action(self):
        # Проверяем переназначение пары на другого кандидата
        fake_cli = Fake(lambda u: '{"action": "REASSIGN", "candidate": 2, "confidence": 0.90, "reason": "Точнее по разделу"}')
        res, st = self.run_resolve(fake_cli, mode="arbitration")
        self.assertGreaterEqual(st["reassigned"] + st["accepted"], 1)

    def test_arbitration_reject_action(self):
        # Проверяем отклонение всех вариантов (нет в смете)
        fake_cli = Fake(lambda u: '{"action": "REJECT", "candidate": null, "confidence": 0.95, "reason": "Чужая работа"}')
        res, st = self.run_resolve(fake_cli, mode="arbitration")
        self.assertGreaterEqual(st["rejected"], 1)

    def test_order_independence_in_resolve(self):
        # Проверяем инвариантность к порядку следования спорных строк
        vor = [
            Item('VOR', 1, '1', '', 'Установка светильника LED 36W', 'шт', 10.0),
            Item('VOR', 2, '2', '', 'Монтаж светильника LED 36W', 'шт', 10.0),
        ]
        lsr = [
            Item('LSR', 1, '10', 'Ф1', 'Установка светильника люминесцентного', 'шт', 10.0),
            Item('LSR', 2, '20', 'Ф2', 'Светильник светодиодный 36W', 'шт', 10.0),
        ]

        def smart_fake(u):
            if "Установка светильника LED 36W" in u:
                return '{"action": "REASSIGN", "candidate": 2, "confidence": 0.95, "reason": "Точное совпадение"}'
            else:
                return '{"action": "REASSIGN", "candidate": 2, "confidence": 0.70, "reason": "Менее уверенно"}'

        b = match.match(vor, lsr, thr=0.50)
        for r in b:
            if r.get("vor"):
                r["is_ambiguous"] = True
                r["conflict_reason"] = "Конкуренция за сметную расценку"

        cache1 = self._cache_file("llm_order_cache")
        res_forward, _ = resolve(b, vor, lsr, Fake(smart_fake), mode="arbitration", cache_path=cache1, verbose=False)
        map_forward = {r["vor"]: r["lsr"] for r in res_forward if r.get("vor")}

        b_reversed = [b[1], b[0]] + [r for r in b if r.get("vor") is None]
        cache2 = self._cache_file("llm_order_cache")
        res_reversed, _ = resolve(b_reversed, vor, lsr, Fake(smart_fake), mode="arbitration", cache_path=cache2, verbose=False)
        map_reversed = {r["vor"]: r["lsr"] for r in res_reversed if r.get("vor")}

        # Более приоритетная позиция №1 гарантированно забирает строку 20 независимо от порядка
        self.assertEqual(map_forward["1"], "20")
        self.assertEqual(map_reversed["1"], "20")
        self.assertEqual(map_forward, map_reversed)


if __name__ == "__main__":
    unittest.main()
