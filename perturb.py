"""Генератор проверочного набора для Режима A (синтетические эксперименты).

Создает контролируемые возмущения и эталонную разметку (ground truth)
на основе гарантированно известных соответствий.
"""
import random
import re
from dataclasses import replace
from typing import List, Tuple, Dict, Any, Optional

from parsers import Item

SYNONYMS = [
    ('Разборка', 'Демонтаж'),
    ('Демонтаж', 'Разборка'),
    ('Смена', 'Замена'),
    ('Замена', 'Смена'),
    ('Монтаж', 'Установка'),
    ('Установка', 'Монтаж'),
    ('Устройство', 'Монтаж'),
    ('из листовой стали', 'из стального листа'),
    ('водосточных труб', 'водосточных трубопроводов'),
    ('хвойных пород', 'из хвойных пород'),
    ('окрашивание', 'покраска'),
    ('прокладка', 'монтаж'),
    ('устройство потолков', 'монтаж подвесного потолка'),
]

UNIT_SCALES = {
    '100 м2': ('м2', 100.0),
    'м2': ('100 м2', 0.01),
    '100 м': ('м', 100.0),
    'м': ('100 м', 0.01),
    '10 м': ('м', 10.0),
    'т': ('кг', 1000.0),
    'кг': ('т', 0.001),
    '100 шт': ('шт', 100.0),
    'шт': ('100 шт', 0.01),
}

INCOMPATIBLE_UNITS = {
    'м2': 'м3',
    '100 м2': 'м3',
    'м3': 'м2',
    'т': 'м3',
    '100 м': 'м2',
    'м': 'шт',
    'шт': 'м',
}


def make_set_from_pairs(base_pairs: List[Tuple[Item, Item]], seed: int = 1,
                        shuffle_order: bool = False) -> Tuple[List[Item], List[Dict[str, Any]]]:
    """Генерирует проверочный набор на основе известного списка пар (ВОР, ЛСР)."""
    rnd = random.Random(seed)
    out: List[Item] = []
    truth: List[Dict[str, Any]] = []
    removed_lsr_nums = set()

    for v_orig, l_orig in base_pairs:
        r = rnd.random()
        it = replace(v_orig, ref='', num=str(len(out) + 1))
        cls = 'Совпало'

        if r < 0.06:
            # Случай: позиции нет в ВОР (удалена из ведомости)
            removed_lsr_nums.add(l_orig.num)
            continue
        elif r < 0.28:
            # Синонимическая замена в наименовании
            replaced = False
            for a, b in SYNONYMS:
                if a in it.name:
                    it = replace(it, name=it.name.replace(a, b, 1))
                    replaced = True
                    break
            if not replaced:
                it = replace(it, name=it.name.lower())
        elif r < 0.46 and it.unit in UNIT_SCALES:
            # Масштабирование единицы измерения (например м2 <-> 100 м2)
            u_new, k = UNIT_SCALES[it.unit]
            new_qty = round(it.qty * k, 6) if it.qty is not None else None
            it = replace(it, unit=u_new, qty=new_qty)
            cls = 'Совпало (после перевода единиц)'
        elif r < 0.58 and it.qty is not None:
            # Ошибка / расхождение объема
            factor = rnd.choice([0.7, 0.85, 1.15, 1.3, 1.5])
            it = replace(it, qty=round(it.qty * factor, 4))
            cls = 'Расхождение объёма'
        elif r < 0.68:
            # Расхождение технических характеристик (числовых параметров в наименовании)
            nums_in_name = re.findall(r'\d+(?:[.,]\d+)?', it.name)
            if nums_in_name:
                n = rnd.choice(nums_in_name)
                val = float(n.replace(',', '.'))
                new_val = str(int(val + 5)) if val.is_integer() else f"{val + 1.5:.1f}"
                it = replace(it, name=it.name.replace(n, new_val, 1))
                cls = 'Расхождение по сути'
        elif r < 0.74 and it.unit in INCOMPATIBLE_UNITS:
            # Несовместимая единица измерения
            it = replace(it, unit=INCOMPATIBLE_UNITS[it.unit])
            cls = 'Расхождение единиц'

        out.append(it)
        truth.append(dict(vor=it.num, lsr=l_orig.num, cls=cls))

        # Генерация дубликата
        if rnd.random() < 0.04:
            dup_item = replace(it, num=str(len(out) + 1))
            out.append(dup_item)
            truth.append(dict(vor=dup_item.num, lsr=l_orig.num, cls='Дубль'))

    # Добавляем лишние позиции в ВОР, которых нет в смете ЛСР
    extra_templates = [
        ('Устройство ограждения временного из сетки', 'м', 45.0),
        ('Покраска металлических элементов эмалью ПФ-115 за 2 раза', 'м2', 28.5),
        ('Уборка строительного мусора вручную с погрузкой в контейнер', 'т', 2.0),
        ('Монтаж молниеприёмной сетки на кровле', 'м', 60.0),
        ('Герметизация швов силиконовым герметиком', 'м', 35.0),
    ]
    num_extras = max(2, len(base_pairs) // 20)
    for _ in range(num_extras):
        name_t, unit_t, q_base = rnd.choice(extra_templates)
        qty_val = round(q_base * rnd.uniform(0.8, 1.5), 2)
        extra = Item('VOR', 0, str(len(out) + 1), '', name_t, unit_t, qty_val)
        out.append(extra)
        truth.append(dict(vor=extra.num, lsr=None, cls='Нет в рассматриваемой смете'))

    # Формируем список сметных позиций, удаленных из ВОР
    missing_lsr = [dict(vor=None, lsr=n, cls='Нет в ВОР') for n in sorted(removed_lsr_nums, key=lambda x: str(x))]

    if shuffle_order:
        # Перемешивание порядка строк для проверки независимости алгоритма от исходного порядка
        combined = list(zip(out, [t for t in truth if t['vor'] is not None]))
        rnd.shuffle(combined)
        out = [c[0] for c in combined]
        truth_shuffled = [c[1] for c in combined]
        return out, truth_shuffled + missing_lsr

    return out, truth + missing_lsr


def make_set(vor: List[Item], lsr: List[Item], seed: int = 1,
             shuffle_order: bool = False,
             ground_truth_map: Optional[Dict[str, str]] = None) -> Tuple[List[Item], List[Dict[str, Any]]]:
    """Универсальное создание проверочного набора.

    Источники известных соответствий:
    1. ground_truth_map: явное отображение {vor_num: lsr_num}.
    2. vor[i].ref: ссылки на номера ЛСР в исходной ВОР.
    3. Если ссылок нет — генерация синтетической ВОР на основе ЛСР (Режим A),
       гарантирующая известное соответствие и исключающая пустой проверочный набор.
    """
    lsr_by_num = {str(x.num): x for x in lsr}
    base_pairs: List[Tuple[Item, Item]] = []

    if ground_truth_map:
        for v in vor:
            target_lsr = ground_truth_map.get(str(v.num))
            if target_lsr and str(target_lsr) in lsr_by_num:
                base_pairs.append((v, lsr_by_num[str(target_lsr)]))
    else:
        # Проверяем наличие ссылок v.ref
        for v in vor:
            ref_val = str(v.ref).strip()
            if ref_val and ref_val in lsr_by_num:
                base_pairs.append((v, lsr_by_num[ref_val]))

    if not base_pairs:
        # Если в ВОР нет ссылок на ЛСР и нет внешней разметки:
        # Для Режима А строим синтетическую ВОР НАПРЯМУЮ из позиций ЛСР!
        # Каждая позиция ЛСР порождает базовую позицию ВОР со 100% известным соответствием.
        for idx, l in enumerate(lsr, 1):
            v_synth = Item(
                doc='VOR',
                row=idx,
                num=str(idx),
                ref=str(l.num),
                name=l.name,
                unit=l.unit,
                qty=l.qty,
                sheet='Синтетический ВОР'
            )
            base_pairs.append((v_synth, l))

    return make_set_from_pairs(base_pairs, seed=seed, shuffle_order=shuffle_order)
