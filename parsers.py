"""Универсальное и надежное чтение позиций ВОР и ЛСР из Excel.

Извлекает позиции с сохранением исходных номеров, строк, ссылок,
наименований, единиц измерения, объемов и нормализованных метаданных.
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
import re
import openpyxl


@dataclass
class Item:
    doc: str                        # 'VOR' или 'LSR'
    row: int                        # Номер строки в файле Excel (1-based)
    num: str                        # Номер позиции по порядку (например '1', '1.1')
    ref: str                        # Ссылка (для ВОР: '№ в ЛСР'; для ЛСР: шифр норматива/расценки)
    name: str                       # Исходное наименование
    unit: str                       # Исходная единица измерения
    qty: Optional[float]            # Количество
    sheet: str = ""                 # Название листа
    section: str = ""               # Название раздела сметы / этажа / помещения
    name_norm: str = ""             # Нормализованное наименование для поиска
    code: str = ""                  # Нормативный шифр или артикул (ГЭСН, ФЕР, ФСБЦ, ТЦ)
    characteristics: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.name_norm:
            self.name_norm = normalize_text(self.name)
        if not self.code and self.ref:
            self.code = self.ref.strip()
        if not self.characteristics and self.name:
            self.characteristics = extract_technical_characteristics(self.name)


def normalize_text(text: str) -> str:
    """Приводит текст к каноническому виду для сопоставления."""
    if not text:
        return ""
    s = text.lower().replace("ё", "е")
    # Заменяем латинские схожие буквы на кириллические в смешанном тексте
    # (например 'x' на 'х' в размерах 3х1.5)
    s = s.replace("x", "х").replace("×", "х").replace("*", "х")
    # Оставляем буквы, цифры, дефисы, точки и пробелы
    s = re.sub(r"[^\w\s\.\-,/]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _s(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _key(value) -> str:
    s = _s(value).lower().replace("ё", "е")
    s = s.replace("№", " номер ")
    return re.sub(r"[^a-zа-я0-9]+", " ", s).strip()


def _f(value) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).replace("\u00a0", "").replace(" ", "").replace(",", ".")
    # Проверка на валидное число
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", s):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _clean_num(value) -> str:
    """Извлекает строковый номер позиции: '1', '1.1', '2 О' -> '1', '1.1', '2'."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    s = _s(value)
    # Если номер вида "2\nО" или "2 О" (оборудование)
    m = re.match(r"^(\d+(?:[\.\-]\d+)*)", s)
    if m:
        return m.group(1)
    return s


def _is_num_header(v: str) -> bool:
    return v in {"п п", "номер п п", "номер позиции", "номер по порядку", "n п п", "no п п"} or \
        ("п п" in v and "номер" not in v) or v.startswith("номер п п")


def _is_name_header(v: str) -> bool:
    return v in {"наименование", "наименование работ", "наименование работ и затрат",
                 "наименование затрат", "описание работ"} or (
        v.startswith("наименование") and any(w in v for w in ("работ", "затрат", "материал", "оборудован")))


def _is_unit_header(v: str) -> bool:
    return v.startswith(("ед изм", "единица измерения", "единицы измерения", "ед измерения", "измеритель")) or \
        v in {"ед", "ед изм", "изм"}


def _is_qty_header(v: str) -> bool:
    return v in {"кол во", "количество", "кол", "объем", "объем работ"} or \
        v.startswith(("количество", "кол во", "объем работ"))


def _is_ref_header(v: str, doc: str) -> bool:
    """Определяет, является ли колонка ссылочной."""
    if doc == "VOR":
        # В ВОР ссылка — это ссылка на номер в ЛСР / смете
        return any(k in v for k in ("лср", "номер в лср", "в лср", "по смете", "ссылка на смет", "пункт лср"))
    else:
        # В ЛСР ссылка — это шифр расценки, обоснование норматива, код ресурса
        return any(k in v for k in ("обоснование", "шифр", "код расценки", "шифр норматива", "код ресурса"))


def _refine_qty_col(ws, header_row: int, qty_col: int, width: int = 4) -> Tuple[int, int]:
    """В сметах ЛСР под 'Количество' часто идут подзаголовки:
    'на единицу', 'коэффициенты', 'всего с учетом коэффициентов'.
    Ищет колонку итогового объема работ."""
    for r in range(header_row + 1, min(header_row + 4, ws.max_row + 1)):
        row = next(ws.iter_rows(min_row=r, max_row=r, values_only=True), ())
        for c in range(qty_col, min(qty_col + width, len(row))):
            k = _key(row[c])
            if k.startswith("всего") or "с учетом коэф" in k or "всего с" in k:
                return c, r
    return qty_col, header_row


def _find_header(ws, doc: str, scan_rows: int = 100):
    """Находит строку заголовков и карту колонок: num, ref, name, unit, qty."""
    for row_idx, row in enumerate(
            ws.iter_rows(min_row=1, max_row=min(scan_rows, ws.max_row), values_only=True), 1):
        vals = [_key(v) for v in row]
        num_col = next((i for i, v in enumerate(vals) if _is_num_header(v)), None)
        name_col = next((i for i, v in enumerate(vals) if _is_name_header(v)), None)
        unit_col = next((i for i, v in enumerate(vals) if _is_unit_header(v)), None)
        qty_col = next((i for i, v in enumerate(vals) if _is_qty_header(v)), None)

        if None in (num_col, name_col, unit_col, qty_col):
            continue

        # Ищем колонку со ссылкой (№ в ЛСР для ВОР, обоснование/шифр для ЛСР)
        ref_col = next((i for i, v in enumerate(vals) if _is_ref_header(v, doc)), None)
        # Если в ВОР колонка № в ЛСР стоит второй (сразу после № п/п), а заголовок короткий
        if ref_col is None and doc == "VOR":
            for i, v in enumerate(vals):
                if i != num_col and i != name_col and ("лср" in v or "смет" in v):
                    ref_col = i
                    break

        if doc != "VOR":
            qty_col, row_idx = _refine_qty_col(ws, row_idx, qty_col)

        return row_idx, {
            "num": num_col,
            "ref": ref_col,
            "name": name_col,
            "unit": unit_col,
            "qty": qty_col,
        }
    return None


def extract_technical_characteristics(text: str) -> Dict[str, Any]:
    """Извлекает ключевые технические характеристики из наименования."""
    chars: Dict[str, Any] = {}
    if not text:
        return chars

    # Фракционные диапазоны и размеры: дефис и различные тире приводим к одной форме.
    # Сначала извлекаем кандидаты, затем требуем доменный контекст или единицу измерения,
    # чтобы не трактовать нормативные шифры вроде ГОСТ 8736-2014 как диапазон.
    range_pattern = re.compile(
        r"(?<![\w.])(?P<lo>\d+(?:[.,]\d+)?)\s*[-‐‑‒–—−]\s*"
        r"(?P<hi>\d+(?:[.,]\d+)?)(?![\w.])"
    )
    ranges = set()
    for match_range in range_pattern.finditer(text):
        before = text[max(0, match_range.start() - 40):match_range.start()]
        after = text[match_range.end():match_range.end() + 12]
        has_label = bool(re.search(r"(?:фракц\w*|размер\w*)\D{0,30}$", before, re.IGNORECASE))
        has_unit = bool(re.match(r"\s*(?:мм|см|м)\b", after, re.IGNORECASE))
        if has_label or has_unit:
            lo = f"{float(match_range.group('lo').replace(',', '.')):g}"
            hi = f"{float(match_range.group('hi').replace(',', '.')):g}"
            ranges.add(f"{lo}-{hi}")
    if ranges:
        chars["ranges"] = sorted(ranges)

    # 1. Сечения кабелей и проводов (например 3х1.5, 3х2,5, 5х16)
    cables = re.findall(r"\b(\d+)\s*[хx×*]\s*(\d+(?:[.,]\d+)?)\b", text, re.IGNORECASE)
    if cables:
        chars["cables"] = [f"{c[0]}х{c[1].replace(',', '.')}" for c in cables]

    # 2. Диаметры (например Ду50, Ду 100, d=50, диам. 150)
    diameters = re.findall(r"\b(?:ду|диам|d|диаметр)[\.\s]*(\d+(?:[.,]\d+)?)\b", text, re.IGNORECASE)
    if diameters:
        chars["diameters"] = [d.replace(',', '.') for d in diameters]

    # 3. Марки оборудования и материалов (буквенно-цифровые обозначения с дефисом, например ВД-АК-149, БУ32-И, ПФ-115)
    models = re.findall(r"\b([А-Яа-яA-Za-z]+[-][А-Яа-яA-Za-z0-9\-]+)\b", text)
    if models:
        chars["models"] = [m.lower() for m in models if len(m) >= 3]

    # 4. Все числа в тексте
    raw_nums = re.findall(r"\b\d+(?:[.,]\d+)?\b", text)
    chars["raw_nums"] = [n.replace(',', '.') for n in raw_nums]

    return chars


def _read_sheet(ws, doc: str):
    """Читает один лист Excel-книги. Возвращает (items, header_row) или None."""
    found = _find_header(ws, doc)
    if not found:
        return None
    header_row, cols = found
    items = []
    current_section = ""

    for row_idx, row in enumerate(
            ws.iter_rows(min_row=header_row + 1, values_only=True),
            header_row + 1):
        row = list(row)

        def cell(col):
            return row[col] if col is not None and col < len(row) else None

        # Проверяем, не является ли строка заголовком раздела / объекта / помещения
        row_cells = [_s(c) for c in row if c is not None and _s(c)]
        row_text = " ".join(row_cells)
        row_key = _key(row_text)
        if any(pfx in row_key for pfx in ("раздел", "подраздел", "помещение", "этаж", "участок")):
            for c_text in row_cells:
                ck = _key(c_text)
                if any(pfx in ck for pfx in ("раздел", "подраздел", "помещение", "этаж", "участок")):
                    if len(c_text) > 3 and not re.fullmatch(r"\d+", c_text):
                        current_section = c_text[:120].strip()
                        break

        raw_num = cell(cols["num"])
        num = _clean_num(raw_num)
        # В ЛСР номер позиции — целое число. Строки ресурсов («Н», «П,Н», «1.1») — это не
        # самостоятельные позиции, их пропускаем. В ВОР допускаем номера вида «1.1».
        if not num or not re.fullmatch(r"\d+" if doc != "VOR" else r"\d+(?:\.\d+)*", num):
            continue

        raw_ref = cell(cols["ref"]) if cols["ref"] is not None else ""
        ref = _clean_num(raw_ref) if (doc == "VOR" and raw_ref is not None) else _s(raw_ref)

        name = _s(cell(cols["name"]))
        unit = _s(cell(cols["unit"]))
        qty = _f(cell(cols["qty"]))

        # Исключаем служебные строки и строки разделов
        if not name or not unit or qty is None:
            continue

        # Строка с номерами колонок ("1", "2", "3", ...)
        if re.fullmatch(r"\d+(?:[.,]\d+)?", name) or re.fullmatch(r"\d+(?:[.,]\d+)?", unit):
            continue

        name_lower = _key(name)
        if name_lower.startswith(("раздел", "итого", "всего", "накладные расходы",
                                  "сметная прибыль", "непредвиденные затраты", "сметная стоимость")):
            continue

        if unit == "%" or name_lower in {"наименование работ и затрат", "наименование", "наименование работ"}:
            continue

        item = Item(
            doc=doc,
            row=row_idx,
            num=num,
            ref=ref,
            name=name,
            unit=unit,
            qty=qty,
            sheet=ws.title,
            section=current_section or ws.title,
            code=ref if doc != "VOR" else "",
            characteristics=extract_technical_characteristics(name)
        )
        items.append(item)

    return items, header_row


def _read(path: str, doc: str) -> List[Item]:
    wb = openpyxl.load_workbook(path, data_only=True)
    try:
        best = None
        with_header = []
        for ws in wb.worksheets:
            res = _read_sheet(ws, doc)
            if res is None:
                continue
            with_header.append(ws.title)
            items, header_row = res
            if items and (best is None or len(items) > len(best[0])):
                best = (items, header_row)
        if not with_header:
            sheet_names = ", ".join(wb.sheetnames[:8])
            raise ValueError(
                f"Не удалось определить заголовки {doc} ни на одном листе. "
                f"Листы книги: {sheet_names}. Проверьте названия колонок."
            )
        if best is None:
            raise ValueError(
                f"Заголовки {doc} найдены (листы: {', '.join(with_header)}), "
                "но позиции не распознаны. Возможно, формат таблицы отличается "
                "или ячейки с количеством пусты."
            )
        return best[0]
    finally:
        wb.close()


def parse_vor(path: str) -> List[Item]:
    """Читает позиции ВОР из Excel с автоматическим определением структуры."""
    return _read(path, "VOR")


def parse_lsr(path: str) -> List[Item]:
    """Читает позиции ЛСР из Excel с автоматическим определением структуры."""
    return _read(path, "LSR")
