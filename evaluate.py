"""Модуль честной и всесторонней оценки качества алгоритма сопоставления.

Рассчитывает:
- Точность (Precision), Полноту (Recall) и F1-меру сопоставления пар;
- Точность классификации выявленных расхождений (объем, единицы, характеристики, совпало, дубль);
- Долю неразрешенных случаев (требующих ручной проверки специалистом);
- Точность и полноту обнаружения отсутствующих позиций (отдельно для ВОР и ЛСР);
- Матрицу ошибок (confusion matrix).
"""
import collections
from typing import List, Dict, Any, Optional

from parsers import Item


def equiv_groups(lsr: List[Item]) -> Dict[str, set]:
    """Группирует эквивалентные позиции ЛСР (с одинаковым наименованием, единицей и объемом)."""
    g = {}
    for x in lsr:
        qty_round = round(x.qty, 6) if x.qty is not None else None
        g.setdefault((x.name.strip().lower(), x.unit.strip().lower(), qty_round), []).append(str(x.num))
    return {str(n): set(v) for v in g.values() for n in v}


def norm_cls(c: Optional[str]) -> str:
    """Нормализует строковый класс для объективного сравнения."""
    if not c:
        return 'Нет ответа'
    s = str(c).strip()
    if s.startswith('Совпало'):
        return 'Совпало'
    if 'проверка' in s.lower() or 'кандидат' in s.lower():
        return 'Требуется проверка'
    if 'по сути' in s.lower() or 'характеристик' in s.lower():
        return 'Расхождение характеристик'
    return s


def evaluate(pred: List[Dict[str, Any]], truth: List[Dict[str, Any]], lsr: List[Item]) -> Dict[str, Any]:
    """Вычисляет полный набор метрик качества."""
    if not truth:
        raise ValueError("Тестовый эталон (truth) пуст. Невозможно рассчитать метрики.")

    eq = equiv_groups(lsr)
    tv = {str(t['vor']): t for t in truth if t.get('vor') is not None}
    pv = {str(p['vor']): p for p in pred if p.get('vor') is not None}

    if not tv:
        raise ValueError("В тестовом эталоне отсутствуют позиции ВОР. Проверьте разметку.")

    tp = fp = fn = tn = 0
    total_positives = sum(1 for t in tv.values() if t.get('lsr') is not None)

    for v, t in tv.items():
        p = pv.get(v)
        t_lsr = str(t['lsr']) if t.get('lsr') is not None else None
        p_lsr = str(p['lsr']) if p and p.get('lsr') is not None else None

        if t_lsr is None:
            # Истинный статус: позиции нет в смете ЛСР
            if p_lsr is not None:
                fp += 1  # Алгоритм ложно связал несуществующую пару
            else:
                tn += 1  # Алгоритм верно определил отсутствие в смете
            continue

        # Истинный статус: у позиции есть пара в смете
        if p_lsr is not None:
            allowed_equivalents = eq.get(t_lsr, {t_lsr})
            if p_lsr in allowed_equivalents:
                tp += 1
            else:
                fp += 1
                fn += 1
        else:
            fn += 1

    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

    # Классификация расхождений
    conf = collections.Counter()
    cls_ok = 0
    cls_total = 0
    unresolved_count = 0

    for v, t in tv.items():
        p = pv.get(v)
        true_c = norm_cls(t.get('cls'))
        pred_c = norm_cls(p.get('cls') if p else None)

        if pred_c == 'Требуется проверка':
            unresolved_count += 1

        conf[(true_c, pred_c)] += 1
        cls_total += 1
        if true_c == pred_c:
            cls_ok += 1

    cls_acc = cls_ok / cls_total if cls_total > 0 else 0.0
    unresolved_rate = unresolved_count / cls_total if cls_total > 0 else 0.0

    # Оценка качества выявления позиций ЛСР, отсутствующих в ВОР
    tm = {str(t['lsr']) for t in truth if t.get('vor') is None and t.get('lsr') is not None}
    pm = {str(p['lsr']) for p in pred if p.get('vor') is None and p.get('lsr') is not None}

    nv_tp = len(tm & pm)
    nv_prec = nv_tp / len(pm) if pm else 0.0
    nv_rec = nv_tp / len(tm) if tm else 0.0
    nv_f1 = 2 * nv_prec * nv_rec / (nv_prec + nv_rec) if (nv_prec + nv_rec) > 0 else 0.0

    return {
        'prec': prec,
        'rec': rec,
        'f1': f1,
        'tp': tp,
        'fp': fp,
        'fn': fn,
        'tn': tn,
        'total_positives': total_positives,
        'cls_acc': cls_acc,
        'unresolved_rate': unresolved_rate,
        'conf': conf,
        'nv_prec': nv_prec,
        'nv_rec': nv_rec,
        'nv_f1': nv_f1,
    }
