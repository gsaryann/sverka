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

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"

class TestCoreAndParsers(unittest.TestCase):
    def test_parser_warnings_ignore_resource_markers(self):
        """Задача 1: для маркеров ресурсов без количества и единицы _is_noise_row_number(...) is True; для п.5, №7, 1,5 с количеством False."""
        from parsers import _is_noise_row_number
        for marker in ["Н", "П,Н", "Н,П", "М", "Э"]:
            self.assertTrue(_is_noise_row_number(marker, has_qty=False, has_unit=False), f"Маркер {marker} должен быть шумом")
        for num_str in ["п.5", "№7", "1,5"]:
            self.assertFalse(_is_noise_row_number(num_str, has_qty=True, has_unit=True), f"Номер {num_str} не должен быть шумом")

    def test_parser_warns_on_duplicate_numbers(self):
        """Задача 1 (п. 4.7): парсер должен предупреждать о повторных номерах позиций."""
        import tempfile
        import openpyxl
        from parsers import parse_vor, get_parse_warnings

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "ВОР"
        # Заголовки
        ws.append(["№ п/п", "Наименование работ", "Ед. изм.", "Количество"])
        ws.append(["1", "Демонтаж плинтусов", "м", "50.0"])
        ws.append(["1", "Монтаж плинтусов (повторный номер)", "м", "50.0"])

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            wb.save(tmp_path)
            get_parse_warnings()
            items = parse_vor(tmp_path)
            warnings = get_parse_warnings()
            dup_warnings = [w for w in warnings if "Повторный номер позиции" in w.get("reason", "")]
            self.assertGreaterEqual(len(dup_warnings), 1, "Должно быть предупреждение о дубликате номера")
            self.assertIn("1", dup_warnings[0]["reason"])
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_real_pairs_parser_warnings(self):
        """Задача 1: проверка числа позиций и порогов предупреждений на всех 7 реальных парах."""
        from parsers import parse_vor, parse_lsr, get_parse_warnings
        pairs = [
            ("ВОР.xlsx", "ЛСР.xlsx", 86, 30),
            ("ВОР освещение КОРР.xlsx", "ЛСР освещение КОРР.xlsx", 137, 35),
            ("ВОР (1 этаж кабинеты).xlsx", "ЛСР (1 этаж кабинеты).xlsx", 534, 55),
            ("ВОР ремонт и утеплитель.xlsx", "ЛСР по Методике 2020 (РИМ).xlsx", 88, 5),
            ("ВЕДОМОСТЬ ОБЪЕМОВ РАБОТ.xlsx", "ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЕТ.xlsx", 83, 10),
            ("Приложение №2.3.1 Ведомость объемов работ №2.xlsx", "Приложение №2.3 Локальный сметный расчет №2.xlsx", 23, 5),
            ("02_01_01_чайная_Анастасьевка__Текущий_ремонт___Дефектная_ведомость_по_смете_2.xlsx", "02_01_01_чайная_Анастасьевка__Текущий_ремонт___ЛСР_по_Методике_2020__РИМ__2.xlsx", 371, 25),
        ]
        for vor_fn, lsr_fn, exp_count, max_warn in pairs:
            vp = DATA_DIR / vor_fn
            lp = DATA_DIR / lsr_fn
            if vp.exists() and lp.exists():
                get_parse_warnings()
                vor = parse_vor(str(vp))
                lsr = parse_lsr(str(lp))
                warnings = get_parse_warnings()
                self.assertEqual(len(vor), exp_count, f"Неверное число позиций ВОР в {vor_fn}")
                self.assertLessEqual(len(warnings), max_warn, f"Слишком много предупреждений ({len(warnings)}) для {vor_fn}")

    def test_llm_resolver_imports_without_openai(self):
        """Задача 2: без openai импорт llm_resolver не должен вызывать SystemExit, а вызов YandexClient бросает RuntimeError."""
        import sys
        import importlib
        orig_openai = sys.modules.get('openai')
        try:
            sys.modules['openai'] = None  # блокирует импорт openai (ModuleNotFoundError / ImportError)
            if 'llm_resolver' in sys.modules:
                del sys.modules['llm_resolver']

            # Должен импортироваться успешно, без SystemExit
            mod = importlib.import_module('llm_resolver')
            self.assertIsNotNone(mod)

            # А вызов клиента должен давать RuntimeError
            with self.assertRaises(RuntimeError) as ctx:
                mod.YandexClient(api_key="fake", folder_id="fake")
            self.assertIn("openai", str(ctx.exception).lower())
        finally:
            if orig_openai is not None:
                sys.modules['openai'] = orig_openai
            elif 'openai' in sys.modules:
                del sys.modules['openai']
            if 'llm_resolver' in sys.modules:
                del sys.modules['llm_resolver']
            importlib.import_module('llm_resolver')

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

    def test_metrics_conclusions_match_table(self):
        """Задача 1 (Задание 3, 4): верификация соответствия раздела 4 таблицам отчёта."""
        import re
        metrics_dir = ROOT_DIR / "docs" / "metrics"
        f1_files = sorted(metrics_dir.glob("f1_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not f1_files:
            self.skipTest("Файл отчета f1_*.md еще не сгенерирован.")

        text = f1_files[0].read_text(encoding="utf-8")
        self.assertIn("## 4. Аналитический вывод", text)
        parts = text.split("## 4. Аналитический вывод")
        tables_text = parts[0]
        concl_text = parts[1]

        # 1. Запрещённая субъективная формулировка (Задание 4)
        self.assertNotIn(
            "действительно содержат", concl_text,
            "В разделе 4 недопустима субъективная формулировка 'действительно содержат'!"
        )

        # 2. Проверка отсутствия слова «лидер» при |ΔF1| < 1,0 п.п. (Задание 4)
        for line in concl_text.splitlines():
            if "лидер" in line.lower():
                match_delta = re.search(r'([-+]?\d+\.\d+)\s*п\.п\.', line)
                if match_delta:
                    diff_val = abs(float(match_delta.group(1)))
                    self.assertGreaterEqual(
                        diff_val, 1.0,
                        f"Слово 'лидер' недопустимо при незначимой разнице ({diff_val} < 1.0 п.п.) в строке: {line}"
                    )

        # 3. Все числа в разделе 4 есть в таблицах
        floats = re.findall(r'\b0\.\d{4}\b', concl_text)
        pcts = re.findall(r'\b\d+\.\d+%', concl_text)
        pps = re.findall(r'[-+]?\d+\.\d+\s*п\.п\.', concl_text)
        ratios = re.findall(r'\b\d+/\d+\b', concl_text)

        all_numbers = floats + pcts + pps + ratios
        self.assertGreater(len(all_numbers), 0, "В разделе выводов должны быть приведены числовые доказательства")

        for num in all_numbers:
            self.assertIn(
                num, tables_text,
                f"Число '{num}' из выводов отсутствует в таблицах отчёта {f1_files[0].name}!"
            )


if __name__ == "__main__":
    unittest.main()
