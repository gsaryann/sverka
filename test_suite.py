"""Комплексный набор модульных тестов для системы сопоставления строительной документации."""
import unittest
from parsers import Item, normalize_text, extract_technical_characteristics
from units import parse_unit, to_base
import match
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

    def test_incompatible_units(self):
        name = "Устройство теплоизоляции минераловатными плитами"
        v = Item('VOR', 1, '1', '', name, 'м2', 50.0)
        l = Item('LSR', 1, '1', 'ГЭСН-04', name, 'м3', 50.0)

        res = match.match([v], [l], thr=0.50)
        v_res = next(r for r in res if r['vor'] == '1')
        self.assertEqual(v_res['lsr'], '1')
        self.assertEqual(v_res['cls'], 'Расхождение единиц')


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


if __name__ == '__main__':
    unittest.main()
