import unittest

from parsers import _f, parse_vor


class QuantityFormulaParsingTests(unittest.TestCase):
    def test_leading_calculated_quantities(self):
        self.assertEqual(_f("0,01\n1 / 100"), 0.01)
        self.assertEqual(_f("1,26 (2,5+2,5+2) / 10"), 1.26)

    def test_unicode_negative_quantity(self):
        self.assertEqual(_f("−1,509398"), -1.509398)

    def test_real_workbook_all_positions_are_read(self):
        items = parse_vor("data/Приложение №2.3.1 Ведомость объемов работ №2.xlsx")
        self.assertEqual(len(items), 23)
        self.assertEqual(items[0].qty, 0.01)
        self.assertEqual(items[2].qty, 1.26)
        self.assertEqual(items[10].qty, -1.509398)


if __name__ == "__main__":
    unittest.main()
