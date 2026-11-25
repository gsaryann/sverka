"""Модуль классификации типов загружаемых книг и валидации пар ВОР/ЛСР.

Не зависит от СУБД (SQLAlchemy) и веб-фреймворка (Flask), что позволяет
использовать функции в любых окружениях без внешних зависимостей.
"""

import re
import hashlib
from pathlib import Path
from typing import Optional, Tuple

DATA_DIR = Path(__file__).resolve().parent / "data"


def _document_kind(path: Path) -> Optional[str]:
    """Определяет тип сметного документа (ВОР или ЛСР) по заголовкам и содержимому ячеек."""
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        text = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 45), values_only=True):
                text.extend(str(v).lower().replace('ё', 'е') for v in row if v is not None)
    finally:
        wb.close()
    blob = ' '.join(text)
    cleaned_blob = re.sub(r'№\s*(?:в\s*)?лср', '', blob)

    vor_score = 0
    if re.search(r'ведомост\w* объем\w* работ', blob): vor_score += 2
    if re.search(r'дефектн\w* ведомост\w*', blob): vor_score += 2
    if re.search(r'формула расчета объемов работ', blob): vor_score += 2
    if re.search(r'\bвор\b', blob): vor_score += 1

    lsr_score = 0
    if re.search(r'локальн\w* смет\w* расчет', blob): lsr_score += 2
    if re.search(r'локальная смета', blob): lsr_score += 2
    if re.search(r'сметная стоимость', blob): lsr_score += 2
    if re.search(r'составлен\w* в ценах', blob): lsr_score += 1
    if re.search(r'\bлср\b', cleaned_blob): lsr_score += 1

    if vor_score == lsr_score:
        return None
    return 'vor' if vor_score > lsr_score else 'lsr'


def _resolve_preset_paths(preset: Optional[str]) -> Optional[Tuple[Path, Path]]:
    """Определяет пути к файлам ВОР и ЛСР для эталонных демонстрационных комплектов."""
    if not preset:
        return None
    p = str(preset).strip().lower()
    if p in ('set1', 'palace', 'дворец'):
        return DATA_DIR / "ВОР.xlsx", DATA_DIR / "ЛСР.xlsx"
    elif p in ('crystal', 'lighting', 'кристалл', 'освещение'):
        return DATA_DIR / "ВОР освещение КОРР.xlsx", DATA_DIR / "ЛСР освещение КОРР.xlsx"
    elif p in ('kaluga', 'cabinets', 'калуга', 'кабинеты'):
        return DATA_DIR / "ВОР (1 этаж кабинеты).xlsx", DATA_DIR / "ЛСР (1 этаж кабинеты).xlsx"
    elif p in ('set2', 'room163', 'пом163'):
        return DATA_DIR / "ВЕДОМОСТЬ ОБЪЕМОВ РАБОТ.xlsx", DATA_DIR / "ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЕТ.xlsx"
    elif p in ('tea', 'anastasyevka', 'анастасьевка', 'чайная'):
        return (
            DATA_DIR / "02_01_01_чайная_Анастасьевка__Текущий_ремонт___Дефектная_ведомость_по_смете_2.xlsx",
            DATA_DIR / "02_01_01_чайная_Анастасьевка__Текущий_ремонт___ЛСР_по_Методике_2020__РИМ__2.xlsx"
        )
    return None


def _validate_document_pair(vor_path: Path, lsr_path: Path) -> Optional[str]:
    """Проверяет корректность пары загружаемых документов (разные файлы, не перепутаны местами)."""
    if hashlib.sha256(vor_path.read_bytes()).digest() == hashlib.sha256(lsr_path.read_bytes()).digest():
        return 'Загружен один и тот же файл в оба поля. Выберите отдельные ВОР и ЛСР.'
    kind_v, kind_l = _document_kind(vor_path), _document_kind(lsr_path)
    if kind_v == kind_l and kind_v in ('vor', 'lsr'):
        label = 'ВОР' if kind_v == 'vor' else 'ЛСР'
        return f'В оба поля загружены документы типа {label}. Для сверки нужны одна ВОР и одна ЛСР.'
    if kind_v == 'lsr' and kind_l == 'vor':
        return 'Файлы, похоже, перепутаны: в поле ВОР загружена ЛСР, а в поле ЛСР — ВОР. Поменяйте их местами и запустите сверку снова.'
    return None
