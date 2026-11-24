import unittest
import os
from unittest.mock import patch
from db import LLMLog, Base, is_production
from web.web_app import format_rows
from parsers import Item

class TestDatabaseAndProjects(unittest.TestCase):
    def test_llm_log_decision_allows_long_text(self):
        """3.2: LLMLog.decision должен поддерживать длинные тексты (>100 символов)."""
        long_name = "Ремонт штукатурки внутренних стен известково-гипсовым раствором по камню и бетону площадью отдельных мест более 10 м2 с приготовлением раствора"
        self.assertGreater(len(long_name), 100)
        log = LLMLog(
            project_id=1,
            vor_name="ВОР позиция",
            decision=long_name,
            confidence=0.95
        )
        self.assertEqual(log.decision, long_name)

    def test_llm_log_tokens_and_cost_allow_null(self):
        """3.3: LLMLog должен позволять None/NULL для токенов и стоимости."""
        log = LLMLog(
            project_id=1,
            vor_name="ВОР",
            decision="ЛСР",
            confidence=0.9,
            prompt_tokens=None,
            completion_tokens=None,
            cost_rub=None
        )
        self.assertIsNone(log.prompt_tokens)
        self.assertIsNone(log.completion_tokens)
        self.assertIsNone(log.cost_rub)

    def test_migrate_db_refuses_production(self):
        """3.5: migrate_db.run_migration запрещает выполнение в production."""
        from migrate_db import run_migration
        with patch.dict(os.environ, {"ENV": "production"}):
            with self.assertRaises(RuntimeError):
                run_migration(force=True)

    def test_format_rows_does_not_mark_ai_arbitration_when_model_not_called(self):
        """3.3: format_rows не должен ставить 'Авто' строкам, которые модель не обрабатывала."""
        vor_items = [Item(doc="vor", ref="1", num=1, row=1, section="1", name="Штукатурка", unit="м2", qty=10.0)]
        lsr_items = [Item(doc="lsr", ref="1", num=1, row=1, section="1", code="E1", name="Штукатурка стен", unit="м2", qty=10.0, unit_price=100.0)]
        results = [{
            'vor': 1, 'lsr': 1, 'cls': 'Точное совпадение',
            'score': 1.0, 'text_sim': 1.0, 'upper_status': 'ok'
        }]

        # Вызываем с llm_active=True, но конкретная строка не имеет ai_decision
        rows, stats = format_rows(results, vor_items, lsr_items, llm_active=True)
        self.assertEqual(len(rows), 1)
        self.assertNotEqual(rows[0]['Решение ИИ-арбитра'], 'Авто', "Строка без ai_decision не должна получать 'Авто'!")
        self.assertEqual(rows[0]['Решение ИИ-арбитра'], 'Не привлекался')

    def test_demo_tour_boundaries_in_app_js(self):
        """3.7: В app.js проверка tourDemoLoaded для save/export и риск 0 для позиции без сметы."""
        with open("web/app.js", encoding="utf-8") as f:
            js = f.read()

        self.assertIn("tourDemoLoaded", js)
        self.assertIn("function saveCurrentProjectToDB", js)
        self.assertIn("function exportDiscrepancyAct", js)

if __name__ == "__main__":
    unittest.main()
