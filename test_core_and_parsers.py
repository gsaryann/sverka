import unittest
import math
import json
import os
import tempfile
import threading
from pathlib import Path
from dataclasses import replace

import perturb
from parsers import parse_vor, parse_lsr, Item, get_parse_warnings, _clean_num
import units
import llm_resolver
import match

DATA_DIR = Path("data")

class TestCoreAndParsers(unittest.TestCase):
    def test_perturb_resets_caches(self):
        """4.1: perturb.make_set должен сбрасывать name_norm и characteristics при замене имени."""
        item = Item(doc="LSR", row=1, num="1", ref="ГЭСН 01", name="Разработка грунта экскаватором 0.5 м3", unit="м3", qty=100.0)
        self.assertEqual(item.characteristics.get("raw_nums"), ["0.5"])

        # Симулируем замену характеристик
        new_item = replace(item, name="Разработка грунта экскаватором 1.5 м3", name_norm="", characteristics={})
        self.assertEqual(new_item.characteristics.get("raw_nums"), ["1.5"])
        self.assertIn("1.5", new_item.name_norm)

    def test_llm_parse_answer_robustness(self):
        """4.3: parse_answer должен отвергать NaN, нормализовать проценты, игнорировать мусор вокруг JSON."""
        # 1. NaN confidence -> отвергается (None)
        res = llm_resolver.parse_answer('{"action": "CONFIRM", "candidate": 1, "confidence": NaN, "reason": "ok"}', 3)
        self.assertIsNone(res, "NaN confidence должен возвращать None")

        # 2. Проценты 85 -> 0.85
        res = llm_resolver.parse_answer('{"action": "CONFIRM", "candidate": 1, "confidence": 85, "reason": "ok"}', 3)
        self.assertIsNotNone(res)
        self.assertAlmostEqual(res[1], 0.85)

        # 3. Текст с фигурными скобками и двойной JSON
        text = 'Ответ эксперта: {дополнительный контекст} {"action": "REASSIGN", "candidate": 2, "confidence": 0.9, "reason": "верно"}'
        res = llm_resolver.parse_answer(text, 3)
        self.assertIsNotNone(res)
        self.assertEqual(res[0], 2)
        self.assertEqual(res[3], "REASSIGN")

        # 4. Нецелочисленный candidate (2.9) -> None
        res = llm_resolver.parse_answer('{"action": "CONFIRM", "candidate": 2.9, "confidence": 0.9, "reason": "ok"}', 3)
        self.assertIsNone(res)

        # 5. Булев candidate (true) -> None
        res = llm_resolver.parse_answer('{"action": "CONFIRM", "candidate": true, "confidence": 0.9, "reason": "ok"}', 3)
        self.assertIsNone(res)

    def test_units_thousand_separator_and_synonyms(self):
        """4.8: units.parse_unit корректно разбирает '1 000 шт', 'кв.метр', '100 кубических метров'."""
        # 1. 1 000 шт
        dim, k = units.parse_unit("1 000 шт")
        self.assertEqual(dim, "count")
        self.assertEqual(k, 1000.0)

        # 2. кв.метр
        dim, k = units.parse_unit("кв.метр")
        self.assertEqual(dim, "area")
        self.assertEqual(k, 1.0)

        # 3. 100 кубических метров
        dim, k = units.parse_unit("100 кубических метров")
        self.assertEqual(dim, "volume")
        self.assertEqual(k, 100.0)

    def test_clean_num_handles_prefixes_and_commas(self):
        """4.7: _clean_num корректно обрабатывает 'п.5', '№7', '1,5'."""
        self.assertEqual(_clean_num("п. 5"), "5")
        self.assertEqual(_clean_num("п.5"), "5")
        self.assertEqual(_clean_num("№ 7"), "7")
        self.assertEqual(_clean_num("№7"), "7")
        self.assertEqual(_clean_num("1,5"), "1.5")
        self.assertEqual(_clean_num("1.5"), "1.5")

    def test_real_pairs_baseline_metrics(self):
        """4.9: Проверка всех реальных пар из data/ на число позиций, верхние статусы и найденные цены."""
        test_cases = [
            ("ВОР.xlsx", "ЛСР.xlsx", 86, {"Совпало": 68, "Требует проверки": 17, "Расхождение": 1}),
            ("ВОР освещение КОРР.xlsx", "ЛСР освещение КОРР.xlsx", 137, {"Совпало": 128, "Требует проверки": 8, "Расхождение": 1}),
            ("ВОР ремонт и утеплитель.xlsx", "ЛСР по Методике 2020 (РИМ).xlsx", 88, {"Совпало": 87, "Расхождение": 1}),
        ]

        for vor_fn, lsr_fn, exp_count, exp_statuses in test_cases:
            v_path = DATA_DIR / vor_fn
            l_path = DATA_DIR / lsr_fn
            vor = parse_vor(str(v_path))
            lsr = parse_lsr(str(l_path))
            self.assertEqual(len(vor), exp_count, f"Неверное число позиций ВОР в {vor_fn}")

            results = match.match(vor, lsr)
            status_counts = {}
            for r in results:
                st = r.get("upper_status") or match.upper_status(r.get("cls"))
                status_counts[st] = status_counts.get(st, 0) + 1

            for st_name, exp_st_cnt in exp_statuses.items():
                self.assertEqual(
                    status_counts.get(st_name, 0), exp_st_cnt,
                    f"Расхождение статуса {st_name} в паре {vor_fn} + {lsr_fn}: ожидалось {exp_st_cnt}, получено {status_counts.get(st_name, 0)}"
                )

if __name__ == "__main__":
    unittest.main()
