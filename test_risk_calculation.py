import unittest
from pathlib import Path
import parsers
import match
import units
from risk import calculate_item_risk

DATA_DIR = Path(__file__).resolve().parent / "data"

class TestRiskCalculationAndUnits(unittest.TestCase):
    def test_unit_multiplier_100m_risk_zero(self):
        """ВОР 1100 м против ЛСР 11 '100 м', цена 78 558.23 за '100 м'. Риск должен быть 0."""
        dv, risk, status = calculate_item_risk(
            vor_qty=1100.0,
            vor_unit="м",
            lsr_qty=11.0,
            lsr_unit="100 м",
            unit_price=78558.23
        )
        self.assertEqual(dv, 0.0)
        self.assertEqual(risk, 0.0)

    def test_unit_multiplier_volume_discrepancy(self):
        """ВОР 1200 м против ЛСР 11 '100 м', цена 78 558.23. Разница 1 '100 м', риск 78 558.23."""
        dv, risk, status = calculate_item_risk(
            vor_qty=1200.0,
            vor_unit="м",
            lsr_qty=11.0,
            lsr_unit="100 м",
            unit_price=78558.23
        )
        self.assertAlmostEqual(dv, -1.0, places=4)
        self.assertAlmostEqual(risk, 78558.23, places=2)

    def test_incompatible_dimensions_cannot_evaluate(self):
        """Несовместимые единицы (метры и тонны) -> риск None ('нельзя оценить')."""
        dv, risk, status = calculate_item_risk(
            vor_qty=10.0,
            vor_unit="м",
            lsr_qty=5.0,
            lsr_unit="т",
            unit_price=1000.0
        )
        self.assertIsNone(dv)
        self.assertIsNone(risk)
        self.assertEqual(status, "нельзя оценить")

    def test_negative_quantity_price_parsed(self):
        """Позиция 7 в смете освещения с отрицательным объемом (-14.4) не должна терять цену."""
        lsr_path = DATA_DIR / "ЛСР освещение КОРР.xlsx"
        items = parsers.parse_lsr(str(lsr_path))
        it7 = [x for x in items if str(x.num) == "7"]
        self.assertTrue(len(it7) > 0)
        self.assertIsNotNone(it7[0].unit_price, "Позиция 7 с отрицательным количеством потеряла цену")
        self.assertGreater(it7[0].unit_price, 0)

    def test_real_pairs_risk_totals(self):
        """Проверка контрольных сумм финансового риска на эталонных комплектах из data/."""
        cases = [
            ("ВОР.xlsx", "ЛСР.xlsx", 1003.28),
            ("ВОР освещение КОРР.xlsx", "ЛСР освещение КОРР.xlsx", 2395.29),
            ("02_01_01_чайная_Анастасьевка__Текущий_ремонт___Дефектная_ведомость_по_смете_2.xlsx",
             "02_01_01_чайная_Анастасьевка__Текущий_ремонт___ЛСР_по_Методике_2020__РИМ__2.xlsx", 0.0),
            ("ВЕДОМОСТЬ ОБЪЕМОВ РАБОТ.xlsx", "ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЕТ.xlsx", 0.0),
            ("ВОР (1 этаж кабинеты).xlsx", "ЛСР (1 этаж кабинеты).xlsx", 0.0),
            ("Приложение №2.3.1 Ведомость объемов работ №2.xlsx",
             "Приложение №2.3 Локальный сметный расчет №2.xlsx", 0.0),
        ]
        for v_name, l_name, expected_risk in cases:
            v_path = DATA_DIR / v_name
            l_path = DATA_DIR / l_name
            if not v_path.exists() or not l_path.exists():
                continue
            v_items = parsers.parse_vor(str(v_path))
            l_items = parsers.parse_lsr(str(l_path))
            results = match.match(v_items, l_items)
            v_by_num = {str(x.num): x for x in v_items}
            l_by_num = {str(x.num): x for x in l_items}

            total_risk = 0.0
            for r in results:
                v = r.get("vor_item") or (v_by_num.get(str(r.get("vor"))) if r.get("vor") is not None else None)
                l = r.get("lsr_item") or (l_by_num.get(str(r.get("lsr"))) if r.get("lsr") is not None else None)
                if not v or not l:
                    continue
                dv, item_risk, _ = calculate_item_risk(
                    v.qty, v.unit, l.qty, l.unit, getattr(l, "unit_price", None)
                )
                if item_risk is not None:
                    total_risk += item_risk

            self.assertAlmostEqual(
                round(total_risk, 2),
                expected_risk,
                places=2,
                msg=f"Не совпал финансовый риск для пары {v_name} + {l_name}: получено {total_risk}, ожидалось {expected_risk}"
            )

if __name__ == "__main__":
    unittest.main()
