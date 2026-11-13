"""Комплексный набор модульных тестов для системы сопоставления строительной документации."""
import unittest
from parsers import Item, normalize_text, extract_technical_characteristics
from units import parse_unit, to_base
import match
from match import apply_formulation_warnings
from perturb import make_set
from evaluate import evaluate


class TestUnits(unittest.TestCase):
    """Тесты нормализатора строительных единиц измерения."""

    def test_standard_units(self):
        self.assertEqual(to_base(10, 'м'), ('length', 10.0))
        self.assertEqual(to_base(5, 'м2'), ('area', 5.0))
        self.assertEqual(to_base(2, 'м3'), ('volume', 2.0))
        self.assertEqual(to_base(50, 'кг'), ('mass', 50.0))
        self.assertEqual(to_base(12, 'шт'), ('count', 12.0))

    def test_scaled_estimate_units(self):
        # 100 м2 -> 100 кв.м
        self.assertEqual(to_base(0.085, '100 м2'), ('area', 8.5))
        # 10 м -> 10 метров
        self.assertEqual(to_base(0.8, '10 м'), ('length', 8.0))
        # 100 шт -> 100 штук
        self.assertEqual(to_base(0.12, '100 шт'), ('count', 12.0))
        # 1000 м -> 1000 метров
        self.assertEqual(to_base(0.05, '1000 м'), ('length', 50.0))
        # 100 м3 -> 100 куб.м
        self.assertEqual(to_base(0.02, '100 м3'), ('volume', 2.0))

    def test_compound_spelling(self):
        # Погонные метры в различных написаниях
        dim, q = to_base(15.0, '100 пог. м')
        self.assertEqual(dim, 'length')
        self.assertAlmostEqual(q, 1500.0)

        dim, q = to_base(10.0, 'пог.м.')
        self.assertEqual(dim, 'length')
        self.assertAlmostEqual(q, 10.0)

        dim, q = to_base(5.0, 'м.п.')
        self.assertEqual(dim, 'length')
        self.assertAlmostEqual(q, 5.0)

        # Кубические метры
        dim, q = to_base(3.5, 'куб. м')
        self.assertEqual(dim, 'volume')
        self.assertAlmostEqual(q, 3.5)

        # Тонны
        dim, q = to_base(2.0, 'тн')
        self.assertEqual(dim, 'mass')
        self.assertAlmostEqual(q, 2000.0)

        # Литры
        dim, q = to_base(250.0, 'л')
        self.assertEqual(dim, 'volume')
        self.assertAlmostEqual(q, 0.25)


class TestParsers(unittest.TestCase):
    """Тесты извлечения характеристик и нормализации текста."""

    def test_characteristics_extraction(self):
        text = "Кабель ВВГнг-LS 3х1,5 мм2 в гофротрубе Ду 25"
        chars = extract_technical_characteristics(text)
        self.assertIn("3х1.5", chars.get("cables", []))
        self.assertIn("25", chars.get("diameters", []))

    def test_fraction_range_extraction_and_code_exclusions(self):
        expected = ["5-40"]
        for dash in ("-", "–", "—"):
            chars = extract_technical_characteristics(f"Щебень фракции 5{dash}40 мм")
            self.assertEqual(chars.get("ranges"), expected)

        for code in ("ГОСТ 8736-2014", "ПФ-115", "М-200"):
            chars = extract_technical_characteristics(code)
            self.assertNotIn("ranges", chars)

    def test_normalize_text(self):
        raw = "Монтаж   светильников  LED (светодиодных) 220В!"
        norm = normalize_text(raw)
        self.assertEqual(norm, "монтаж светильников led светодиодных 220в")


class TestMatching(unittest.TestCase):
    """Тесты алгоритма сопоставления и классификации."""

    def test_no_false_match_on_zero_text(self):
        # Две абсолютно разные позиции с одинаковым объемом и порядковым номером НЕ должны связываться
        v = Item('VOR', 1, '1', '', 'Демонтаж деревянных полов', 'м2', 50.0)
        l = Item('LSR', 1, '1', '', 'Монтаж охранной сигнализации', 'м2', 50.0)

        res = match.match([v], [l], thr=0.50, min_text_threshold=0.20)
        v_res = next(r for r in res if r['vor'] == '1')
        # Должен быть статус 'Нет в рассматриваемой смете', а не ложное совпадение
        self.assertEqual(v_res['cls'], 'Нет в рассматриваемой смете')
        self.assertIsNone(v_res['lsr'])

    def test_duplicate_rows_require_identical_quantity(self):
        name = "Монтаж извещателя пожарного дымового"
        lsr = [Item('LSR', 10, '10', 'ГЭСН-01', name, 'шт', 2.0)]
        vor = [
            Item('VOR', 1, '1', '', name, 'шт', 2.0),
            Item('VOR', 2, '2', '', name, 'шт', 2.0),
            Item('VOR', 3, '3', '', name, 'шт', 3.0),
        ]

        results = match.match(vor, lsr, thr=0.50, min_text_threshold=0.20)
        duplicate = next(r for r in results if r['vor'] == '2')
        different_quantity = next(r for r in results if r['vor'] == '3')

        self.assertEqual(duplicate['cls'], 'Дубль')
        self.assertEqual(duplicate['lsr'], '10')
        self.assertNotEqual(different_quantity['cls'], 'Дубль')

    def test_unit_conversion_match(self):
        # 8.5 м2 в ВОР и 0.085 100 м2 в ЛСР должны дать 'Совпало (с пересчетом единиц)'
        name = "Окрашивание водоэмульсионными составами поверхностей потолков"
        v = Item('VOR', 1, '1', '', name, 'м2', 8.5)
        l = Item('LSR', 1, '1', 'ГЭСН-01', name, '100 м2', 0.085)

        res = match.match([v], [l], thr=0.50)
        v_res = next(r for r in res if r['vor'] == '1')
        self.assertEqual(v_res['lsr'], '1')
        self.assertEqual(v_res['cls'], 'Совпало (с пересчетом единиц)')

    def test_volume_discrepancy(self):
        name = "Установка выключателей автоматических"
        v = Item('VOR', 1, '1', '', name, 'шт', 10.0)
        l = Item('LSR', 1, '1', 'ГЭСН-02', name, 'шт', 15.0)

        res = match.match([v], [l], thr=0.50)
        v_res = next(r for r in res if r['vor'] == '1')
        self.assertEqual(v_res['lsr'], '1')
        self.assertEqual(v_res['cls'], 'Расхождение объёма')

    def test_characteristics_discrepancy(self):
        v = Item('VOR', 1, '1', '', "Кабель силовой ВВГнг-LS 3х1.5", 'м', 100.0)
        l = Item('LSR', 1, '1', 'ГЭСН-03', "Прокладка кабеля ВВГнг-LS 3х2.5", 'м', 100.0)

        res = match.match([v], [l], thr=0.50)
        v_res = next(r for r in res if r['vor'] == '1')
        self.assertEqual(v_res['lsr'], '1')
        self.assertEqual(v_res['cls'], 'Расхождение характеристик')

    def test_fraction_range_discrepancy_and_match(self):
        def compare(vor_name, lsr_name):
            v = Item('VOR', 1, '1', '', vor_name, 'т', 1.0)
            l = Item('LSR', 1, '1', 'ГЭСН-05', lsr_name, 'т', 1.0)
            return next(r for r in match.match([v], [l]) if r['vor'] == '1')

        mismatch = compare("Щебень фракции 5–40 мм", "Щебень фракции 20–40 мм")
        self.assertEqual(mismatch['cls'], 'Расхождение характеристик')
        self.assertIn('5–40', mismatch['explanation'])
        self.assertIn('20–40', mismatch['explanation'])

        same = compare("Щебень фракции 5-40 мм", "Щебень фракции 5—40 мм")
        self.assertEqual(same['cls'], 'Совпало')

    def test_incompatible_units(self):
        name = "Устройство теплоизоляции минераловатными плитами"
        v = Item('VOR', 1, '1', '', name, 'м2', 50.0)
        l = Item('LSR', 1, '1', 'ГЭСН-04', name, 'м3', 50.0)

        res = match.match([v], [l], thr=0.50)
        v_res = next(r for r in res if r['vor'] == '1')
        self.assertEqual(v_res['lsr'], '1')
        self.assertEqual(v_res['cls'], 'Расхождение единиц')

    def test_document_compatibility_guard(self):
        # 1. Согласованные документы (одинаковый проект / раздел)
        vor_compat = [
            Item('VOR', 1, '1', '', 'Монтаж извещателей пожарных дымовых', 'шт', 20.0),
            Item('VOR', 2, '2', '', 'Прокладка кабеля КПСЭнг-FRLS 1х2х0.75', 'м', 150.0),
            Item('VOR', 3, '3', '', 'Монтаж прибора приемно-контрольного', 'шт', 1.0),
        ]
        lsr_compat = [
            Item('LSR', 1, '1', 'ГЭСН-1', 'Извещатель пожарный дымовой оптико-электронный', 'шт', 20.0),
            Item('LSR', 2, '2', 'ГЭСН-2', 'Проводка кабелей в каналах: КПСЭнг 1х2х0.75', '100 м', 1.5),
            Item('LSR', 3, '3', 'ГЭСН-3', 'Прибор приемно-контрольный охранно-пожарный', 'шт', 1.0),
        ]
        is_ok, ratio, msg = match.check_document_compatibility(vor_compat, lsr_compat)
        self.assertTrue(is_ok)
        self.assertGreater(ratio, 0.5)

        # 2. Несовместимые документы (пожарная сигнализация vs земляные/дорожные работы)
        lsr_mismatch = [
            Item('LSR', 1, '1', 'ГЭСН-10', 'Разработка грунта экскаватором в отвал', '1000 м3', 1.2),
            Item('LSR', 2, '2', 'ГЭСН-11', 'Устройство подстилающих слоев из щебня', 'м3', 85.0),
            Item('LSR', 3, '3', 'ГЭСН-12', 'Асфальтирование покрытий мелкозернистой смесью', '100 м2', 4.5),
        ]
        is_ok, ratio, msg = match.check_document_compatibility(vor_compat, lsr_mismatch)
        self.assertFalse(is_ok)
        self.assertLess(ratio, 0.25)
        self.assertIn("критически низкое", msg)

        # 3. Пустые входные данные
        is_ok, ratio, msg = match.check_document_compatibility([], lsr_compat)
        self.assertFalse(is_ok)
        self.assertEqual(ratio, 0.0)


class TestEvaluationAndPerturb(unittest.TestCase):
    """Тесты проверочного контура и расчета метрик."""

    def test_synthetic_set_not_empty_without_refs(self):
        # Если в ВОР нет ref, make_set должен корректно сформировать синтетическую выборку
        lsr = [
            Item('LSR', 1, '1', 'ГЭСН-1', 'Монтаж щита распределительного', 'шт', 2.0),
            Item('LSR', 2, '2', 'ГЭСН-2', 'Прокладка кабеля в лотках', 'м', 120.0),
            Item('LSR', 3, '3', 'ГЭСН-3', 'Установка светильников', 'шт', 24.0),
        ]
        vor = [
            Item('VOR', 1, '1', '', 'Монтаж щита распределительного', 'шт', 2.0),
            Item('VOR', 2, '2', '', 'Прокладка кабеля в лотках', 'м', 120.0),
            Item('VOR', 3, '3', '', 'Установка светильников', 'шт', 24.0),
        ]

        pv, truth = make_set(vor, lsr, seed=1)
        self.assertGreater(len(pv), 2)
        self.assertGreater(len(truth), 2)

        # Проверяем оценку
        preds = match.match(pv, lsr)
        metrics = evaluate(preds, truth, lsr)
        self.assertIn('f1', metrics)
        self.assertIn('prec', metrics)
        self.assertIn('rec', metrics)
        self.assertGreaterEqual(metrics['f1'], 0.0)


class TestFormulationWarnings(unittest.TestCase):
    def setUp(self):
        self.v = Item('VOR', 1, '1', '', 'Монтаж насоса X', 'шт', 2.0, section='ВОР')
        self.l = Item('LSR', 1, '1', 'ГЭСН-1', 'Установка насоса X', 'шт', 2.0, section='Секция 1')

    def row(self, cls='Совпало', text_sim=0.44, ai_decision=''):
        return {
            'vor': self.v.num, 'lsr': self.l.num, 'cls': cls,
            'text_sim': text_sim, 'vor_item': self.v, 'lsr_item': self.l,
            'ai_decision': ai_decision,
        }

    def test_weak_text_warning_uses_strict_point_45_boundary(self):
        weak = self.row(text_sim=0.44)
        weak_confirm = self.row(text_sim=0.44, ai_decision='Подтверждено ИИ')
        at_boundary = self.row(text_sim=0.45)
        apply_formulation_warnings([weak, weak_confirm, at_boundary], [self.v], [self.l])

        self.assertTrue(weak['formulation_warning'])
        self.assertEqual(weak['cls'], 'Совпало')
        self.assertEqual(weak['upper_status'], 'Требует проверки')
        self.assertTrue(weak_confirm['formulation_warning'])
        self.assertFalse(at_boundary['formulation_warning'])

        exact_v = Item('VOR', 2, '2', '', 'Прокладка трубы стальной', 'м', 10.0, section='ВОР')
        exact_l = Item('LSR', 2, '2', 'ГЭСН-2', exact_v.name, 'м', 10.0, section='Секция 1')
        exact = {
            'vor': exact_v.num, 'lsr': exact_l.num, 'cls': 'Совпало', 'text_sim': 1.0,
            'vor_item': exact_v, 'lsr_item': exact_l,
        }
        apply_formulation_warnings([exact], [exact_v], [exact_l])
        self.assertFalse(exact['formulation_warning'])

    def test_model_pick_and_reassignment_warn_but_confirm_does_not_add_warning(self):
        self.l.qty = 3.0  # исключает условие (б); конкурирующих разделов нет
        picked = self.row(cls='Расхождение объёма', text_sim=0.9, ai_decision='Подобрано ИИ')
        reassigned = self.row(cls='Расхождение объёма', text_sim=0.9, ai_decision='Переназначено ИИ')
        confirmed = self.row(cls='Расхождение объёма', text_sim=0.9, ai_decision='Подтверждено ИИ')
        apply_formulation_warnings([picked, reassigned, confirmed], [self.v], [self.l])

        self.assertTrue(picked['formulation_warning'])
        self.assertTrue(reassigned['formulation_warning'])
        self.assertFalse(confirmed['formulation_warning'])

    def test_competitor_from_another_section_warns(self):
        self.v.name = 'Монтаж насоса X 20 кВт'
        self.v.name_norm = normalize_text(self.v.name)
        self.l.name = 'Монтаж насоса X 25 кВт'
        self.l.name_norm = normalize_text(self.l.name)
        self.l.qty = 3.0  # исключает условие (б)
        other = Item('LSR', 2, '2', 'ГЭСН-2', 'Монтаж насоса X 21 кВт', 'шт', 4.0, section='Секция 2')
        row = self.row(cls='Расхождение объёма', text_sim=0.8114)
        apply_formulation_warnings([row], [self.v], [self.l, other])

        self.assertTrue(row['formulation_warning'])

    def test_identical_text_in_another_section_is_not_a_formulation_warning(self):
        self.v.name = self.l.name
        self.v.name_norm = normalize_text(self.v.name)
        self.l.name_norm = normalize_text(self.l.name)
        self.l.qty = 3.0
        other = Item('LSR', 2, '2', 'ГЭСН-2', self.l.name, 'шт', 4.0, section='Секция 2')
        row = self.row(cls='Расхождение объёма', text_sim=1.0)
        apply_formulation_warnings([row], [self.v], [self.l, other])

        self.assertFalse(row['formulation_warning'])

    def test_rejected_or_absent_pair_has_no_formulation_warning(self):
        row = {
            'vor': self.v.num, 'lsr': None, 'cls': 'Нет в рассматриваемой смете',
            'vor_item': self.v, 'lsr_item': None, 'ai_decision': 'Отклонено ИИ',
        }
        apply_formulation_warnings([row], [self.v], [self.l])

        self.assertFalse(row['formulation_warning'])
        self.assertEqual(row['formulation_warning_reason'], '')
        self.assertEqual(row['upper_status'], 'Отсутствует в документе')


if __name__ == '__main__':
    unittest.main()
