"""Модульный алгоритм сопоставления позиций ВОР и сметы ЛСР.

Архитектура:
1. Candidate Generation: лексический поиск Top-K кандидатов (n-граммы + токенный скоринг).
2. Feature Scoring: независимый расчет признаков (текст, характеристики, единицы, объем).
3. Optimal / Greedy Matching: сопоставление на основе уверенности с жестким отсечением ложных пар.
4. Explainable Classification: подробная классификация и человекочитаемые объяснения.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import re
import numpy as np
from scipy.optimize import linear_sum_assignment
from sklearn.feature_extraction.text import TfidfVectorizer

from parsers import Item, normalize_text
from units import to_base, parse_unit


@dataclass
class MatchCandidate:
    vor_item: Item
    lsr_item: Item
    sim_text: float
    token_overlap: float
    char_match: bool
    char_diff_desc: str
    unit_compatible: bool
    qty_matched: bool
    qty_ratio: Optional[float]
    confidence: float
    classification: str
    explanation: str
    details: Dict[str, Any] = field(default_factory=dict)


def _tokenize(text: str) -> set:
    words = re.findall(r'[a-zа-я0-9]+', normalize_text(text))
    # Исключаем короткие стоп-слова
    stop = {'и', 'в', 'во', 'на', 'по', 'с', 'со', 'для', 'из', 'от', 'до', 'к', 'при', 'без'}
    return {w for w in words if w not in stop and len(w) > 1}


def _token_jaccard(tokens1: set, tokens2: set) -> float:
    if not tokens1 or not tokens2:
        return 0.0
    return len(tokens1 & tokens2) / len(tokens1 | tokens2)


def extract_nums(s: str) -> List[str]:
    return sorted(re.findall(r'\d+(?:[.,]\d+)?', s.replace(',', '.')))


def compare_technical_characteristics(v_chars: Dict[str, Any], l_chars: Dict[str, Any]) -> Tuple[bool, str]:
    """Сравнивает извлеченные характеристики (кабели, диаметры, марки).
    Возвращает (совпали_ли, текстовое_описание_различий)."""
    diffs = []

    # 1. Сравнение сечений кабелей
    v_cables = set(v_chars.get("cables", []))
    l_cables = set(l_chars.get("cables", []))
    if v_cables and l_cables:
        if not (v_cables & l_cables):
            diffs.append(f"различие сечений: ВОР={list(v_cables)} vs ЛСР={list(l_cables)}")

    # 2. Сравнение диаметров
    v_diams = set(v_chars.get("diameters", []))
    l_diams = set(l_chars.get("diameters", []))
    if v_diams and l_diams:
        if not (v_diams & l_diams):
            diffs.append(f"различие диаметров: ВОР={list(v_diams)} vs ЛСР={list(l_diams)}")

    # 3. Сравнение марок/моделей
    v_models = set(v_chars.get("models", []))
    l_models = set(l_chars.get("models", []))
    if v_models and l_models:
        if not (v_models & l_models):
            # Проверим частичное включение (например, 'пф-115' и 'пф-115-1')
            overlap = any(m1 in m2 or m2 in m1 for m1 in v_models for m2 in l_models)
            if not overlap:
                diffs.append(f"различие марок: ВОР={list(v_models)} vs ЛСР={list(l_models)}")

    if diffs:
        return False, "; ".join(diffs)
    return True, ""


def similarity(vor: List[Item], lsr: List[Item]) -> np.ndarray:
    """Вычисляет матрицу текстового сходства на основе символьных n-грамм (3..5)."""
    if not vor or not lsr:
        return np.zeros((len(vor), len(lsr)))
    vec = TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5), sublinear_tf=True)
    all_texts = [x.name_norm for x in vor] + [x.name_norm for x in lsr]
    X = vec.fit_transform(all_texts)
    A = X[:len(vor)]
    B = X[len(vor):]
    return (A @ B.T).toarray()


def check_document_compatibility(vor: List[Item], lsr: List[Item],
                                 min_candidate_sim: float = 0.25,
                                 min_valid_ratio: float = 0.25) -> Tuple[bool, float, str]:
    """Проверяет глобальную смысловую совместимость двух документов (Project Mismatch Guard).

    Предотвращает нецелевой расход токенов языковой модели, если пользователь случайно
    загрузил файлы от двух совершенно разных проектов или несвязанных разделов работ.
    """
    if not vor or not lsr:
        return False, 0.0, "Один из документов не содержит позиций для сопоставления."

    sim = similarity(vor, lsr)
    if sim.size == 0:
        return False, 0.0, "Матрица сходства пуста."

    max_sims = sim.max(axis=1)
    valid_ratio = float(np.mean(max_sims >= min_candidate_sim))
    avg_sim = float(np.mean(max_sims))

    is_compatible = bool(valid_ratio >= min_valid_ratio)
    if not is_compatible:
        msg = (
            f"Семантическое перекрытие документов критически низкое: лишь {valid_ratio * 100:.1f}% "
            f"позиций имеют хотя бы отдаленного кандидата (среднее сходство {avg_sim * 100:.1f}%). "
            f"Вероятно, загружены файлы от разных объектов или несвязанных разделов работ."
        )
    else:
        msg = (
            f"Документы согласованы: {valid_ratio * 100:.1f}% позиций имеют кандидатов "
            f"(среднее сходство {avg_sim * 100:.1f}%)."
        )
    return is_compatible, valid_ratio, msg


def evaluate_pair(v: Item, l: Item, text_sim: float, tol: float = 1e-3) -> MatchCandidate:
    """Оценивает пару позиций по комплексу независимых признаков."""
    tokens_v = _tokenize(v.name)
    tokens_l = _tokenize(l.name)
    tok_sim = _token_jaccard(tokens_v, tokens_l)

    # Комбинированное текстовое сходство (n-граммы + токенный Jaccard)
    combined_text_sim = 0.7 * text_sim + 0.3 * tok_sim

    # Сравнение единиц и объемов
    dim_v, q_v = to_base(v.qty, v.unit)
    dim_l, q_l = to_base(l.qty, l.unit)

    unit_compatible = (dim_v is not None and dim_l is not None and dim_v == dim_l)
    same_unit_name = (v.unit.strip().lower() == l.unit.strip().lower())

    qty_matched = False
    qty_ratio = None
    if unit_compatible and q_v is not None and q_l is not None:
        diff = abs(q_v - q_l)
        max_q = max(abs(q_l), 1e-9)
        qty_matched = (diff <= tol * max_q)
        qty_ratio = q_v / q_l if abs(q_l) > 1e-9 else None

    # Сравнение характеристик
    chars_ok, char_diff = compare_technical_characteristics(v.characteristics, l.characteristics)

    # Проверка явного совпадения чисел, если характеристики пусты
    if chars_ok and not char_diff:
        nums_v = v.characteristics.get("raw_nums", [])
        nums_l = l.characteristics.get("raw_nums", [])
        # Если в обоих наименованиях есть конкретные числа и они полностью не пересекаются
        if nums_v and nums_l and not (set(nums_v) & set(nums_l)):
            # Проверяем, не являются ли числа тривиальными (например '1', '2')
            non_trivial_v = {n for n in nums_v if float(n) > 2.0}
            non_trivial_l = {n for n in nums_l if float(n) > 2.0}
            if non_trivial_v and non_trivial_l and not (non_trivial_v & non_trivial_l):
                chars_ok = False
                char_diff = f"несовпадение параметров: ВОР={list(non_trivial_v)} vs ЛСР={list(non_trivial_l)}"

    # Расчет уверенности (Confidence Score)
    # Текст является ОПРЕДЕЛЯЮЩИМ. Объем и единица служат подтверждением или выявляют расхождения.
    confidence = combined_text_sim

    # Если текст уверенный (>= 0.5) и объемы совпали — уверенность повышается
    if combined_text_sim >= 0.50 and qty_matched:
        confidence = min(1.0, confidence + 0.15)
    # Если единицы несовместимы или характеристики расходятся — снижаем уверенность
    if not unit_compatible:
        confidence = max(0.0, confidence - 0.20)
    if not chars_ok:
        confidence = max(0.0, confidence - 0.20)

    # Классификация пары
    explanation_parts = []

    if not unit_compatible:
        classification = "Расхождение единиц"
        explanation_parts.append(f"Несовместимые единицы: '{v.unit}' ({dim_v}) vs '{l.unit}' ({dim_l})")
    elif not chars_ok:
        classification = "Расхождение характеристик"
        explanation_parts.append(f"Выявлены расхождения: {char_diff}")
    elif not qty_matched:
        classification = "Расхождение объёма"
        explanation_parts.append(f"Различие объема: ВОР={v.qty} {v.unit} ({q_v:.4f} базовых) vs ЛСР={l.qty} {l.unit} ({q_l:.4f} базовых)")
    else:
        if same_unit_name:
            classification = "Совпало"
            explanation_parts.append(f"Полное совпадение: объем={v.qty} {v.unit}")
        else:
            classification = "Совпало (с пересчетом единиц)"
            explanation_parts.append(f"Совпало после пересчета единиц: {v.qty} {v.unit} <-> {l.qty} {l.unit}")

    if combined_text_sim < 0.40:
        explanation_parts.append(f"Низкое текстовое сходство ({combined_text_sim:.2f})")
    elif combined_text_sim < 0.60:
        explanation_parts.append(f"Умеренное текстовое сходство ({combined_text_sim:.2f})")

    explanation = "; ".join(explanation_parts)

    return MatchCandidate(
        vor_item=v,
        lsr_item=l,
        sim_text=float(text_sim),
        token_overlap=float(tok_sim),
        char_match=chars_ok,
        char_diff_desc=char_diff,
        unit_compatible=unit_compatible,
        qty_matched=qty_matched,
        qty_ratio=qty_ratio,
        confidence=float(confidence),
        classification=classification,
        explanation=explanation,
        details={
            "combined_text_sim": combined_text_sim,
            "q_vor_base": q_v,
            "q_lsr_base": q_l,
            "dim": dim_v if unit_compatible else None
        }
    )


def match(vor: List[Item], lsr: List[Item], thr: float = 0.50,
          w_q: float = 0.1, w_o: float = 0.0,
          min_text_threshold: float = 0.20,
          use_global_optimization: bool = True) -> List[Dict[str, Any]]:
    """Основная функция сопоставления.
    
    Гарантирует:
    - Отсутствие ложных совпадений при отсутствии текстового сходства (min_text_threshold).
    - Оптимальный подбор пар без блокировки жадным выбором.
    - Полную объяснимость каждой пары.
    - Совместимость с форматом словарей исходного проекта.
    """
    if not vor:
        return [dict(vor=None, lsr=l.num, cls='Нет в ВОР', score=0.0, explanation='Нет в ВОР') for l in lsr]
    if not lsr:
        return [dict(vor=v.num, lsr=None, cls='Нет в рассматриваемой смете', score=0.0, explanation='Смета пуста') for v in vor]

    text_sim_matrix = similarity(vor, lsr)
    nv, nl = len(vor), len(lsr)

    # Формируем матрицу уверенности и матрицу кандидатов (нейтральная стоимость 0.0 исключает искажения назначений)
    cost_matrix = np.full((nv, nl), 0.0)
    candidate_matrix = {}

    for i, v in enumerate(vor):
        for j, l in enumerate(lsr):
            sim_t = float(text_sim_matrix[i, j])
            # Жесткий фильтр: если текст совсем чужой, кандидат отсекается сразу
            if sim_t < min_text_threshold and w_o == 0.0:
                continue

            cand = evaluate_pair(v, l, sim_t)
            score = cand.confidence

            # Учет совместимости со старыми флагами w_q и w_o (для сравнительного анализа)
            if w_q and cand.qty_matched:
                score += w_q
            if w_o:
                score += w_o * (1.0 - abs(i / max(nv, 1) - j / max(nl, 1)))

            candidate_matrix[(i, j)] = cand
            cost_matrix[i, j] = -score

    matched_v = {}
    matched_l = {}

    if use_global_optimization:
        # Глобальное венгерское сопоставление (минимизация -score = максимизация score)
        row_ind, col_ind = linear_sum_assignment(cost_matrix)
        for i, j in zip(row_ind, col_ind):
            cand = candidate_matrix.get((i, j))
            if cand is not None:
                # Проверяем критерии принятия пары:
                # 1) Высокая общая уверенность
                # 2) Либо уверенное сходство по тексту (>= 0.45) для выявления расхождений
                # 3) Либо умеренный текст (>= 0.35) при точном совпадении объема
                text_sim_comb = float(cand.details.get("combined_text_sim", cand.sim_text))
                # Критерии принятия кандидата в качестве пары:
                # 1) Общая уверенность выше порога thr
                # 2) Уверенное текстовое сходство (>= 0.40)
                # 3) Текстовое сходство >= 0.25 при наличии подтверждающих признаков
                #    (совпадение объема, либо явное обнаружение расхождения характеристик/объема)
                is_accepted = (
                    (cand.confidence >= thr) or
                    (text_sim_comb >= 0.40) or
                    (text_sim_comb >= 0.25 and (not cand.char_match or cand.qty_matched or not cand.unit_compatible))
                )
                if is_accepted:
                    matched_v[i] = (j, cand)
                    matched_l[j] = (i, cand)
    else:
        # Жадный выбор (для обратной совместимости при тестировании)
        sorted_pairs = sorted(
            candidate_matrix.items(),
            key=lambda x: (x[1].confidence if not w_o else x[1].confidence + w_o * (1 - abs(x[0][0]/nv - x[0][1]/nl))),
            reverse=True
        )
        for (i, j), cand in sorted_pairs:
            if cand.confidence < thr:
                break
            if i in matched_v or j in matched_l:
                continue
            matched_v[i] = (j, cand)
            matched_l[j] = (i, cand)

    # Второй проход (fallback): сопоставление оставшихся непарных строк по подтвержденной ссылке в ВОР и точному объёму
    for i in range(nv):
        if i not in matched_v:
            v = vor[i]
            v_ref = (getattr(v, 'ref', None) or '').strip()
            if not v_ref:
                continue
            for j in range(nl):
                if j not in matched_l:
                    l = lsr[j]
                    if v_ref == str(l.num).strip():
                        sim_t = float(text_sim_matrix[i, j])
                        cand = evaluate_pair(v, l, sim_t)
                        if cand.unit_compatible and cand.qty_matched:
                            cand.classification = "Кандидат — требуется проверка"
                            cand.explanation = (
                                f"Сопоставлено вторым проходом по ссылке № в ЛСР (#{l.num}) "
                                f"и совпадению объема ({v.qty} {v.unit}): требуется проверка наименования"
                            )
                            matched_v[i] = (j, cand)
                            matched_l[j] = (i, cand)
                            break

    results = []

    # Обработка позиций ВОР
    for i, v in enumerate(vor):
        # Все кандидаты для позиции ВОР i
        all_cands_i = sorted(
            [(c_j, candidate_matrix[(i, c_j)]) for c_j in range(nl) if (i, c_j) in candidate_matrix],
            key=lambda x: -x[1].confidence
        )

        if i in matched_v:
            j, cand = matched_v[i]
            l = lsr[j]
            status = cand.classification
            # Если текстовое сходство пограничное или уверенность невысокая, выносим на проверку специалиста
            if (cand.sim_text < 0.45 or cand.confidence < 0.50) and status in ("Совпало", "Совпало (с пересчетом единиц)"):
                status = "Кандидат — требуется проверка"

            # Анализ альтернатив и расчет маржи
            alt_pairs = [c for c in all_cands_i if c[0] != j]
            alt_j, alt_cand = alt_pairs[0] if alt_pairs else (None, None)
            margin = (cand.confidence - alt_cand.confidence) if alt_cand else 1.0

            is_ambiguous = False
            ambiguity_type = None
            conflict_reasons = []

            # 1. Конкуренция близких кандидатов (минимальный разрыв скора)
            if alt_cand is not None and margin < 0.12 and cand.confidence >= 0.35:
                # Фильтр дубликатов: если альтернатива - это текстуальный дубль работы из другой комнаты,
                # а текущий кандидат однозначно выбран по объему, или разница скора 0.00 при идентичном тексте,
                # отправка в модель не требуется
                is_exact_dup = abs(cand.sim_text - alt_cand.sim_text) < 0.001
                if is_exact_dup and cand.qty_matched and not alt_cand.qty_matched:
                    pass
                elif is_exact_dup and margin == 0.0:
                    pass
                else:
                    is_ambiguous = True
                    ambiguity_type = "competition"
                    conflict_reasons.append(
                        f"Конкуренция со строкой ЛСР №{lsr[alt_j].num} (разница уверенности {margin:.2f})"
                    )

            # 2. Конфликт параметров при высоком сходстве текста
            if cand.sim_text >= 0.45 and not cand.char_match:
                is_ambiguous = True
                ambiguity_type = ambiguity_type or "param_conflict"
                conflict_reasons.append(f"Конфликт характеристик: {cand.char_diff_desc}")

            # 3. Расхождение объемов > 20% при высоком текстовом сходстве
            if cand.sim_text >= 0.65 and cand.unit_compatible and not cand.qty_matched:
                if cand.qty_ratio is not None and (cand.qty_ratio < 0.80 or cand.qty_ratio > 1.25):
                    is_ambiguous = True
                    ambiguity_type = ambiguity_type or "qty_conflict"
                    conflict_reasons.append(
                        f"Расхождение объёма >20%: ВОР={v.qty} {v.unit} vs ЛСР={l.qty} {l.unit}"
                    )

            # 4. Несовместимые единицы измерения при похожем тексте
            if cand.sim_text >= 0.50 and not cand.unit_compatible:
                is_ambiguous = True
                ambiguity_type = ambiguity_type or "unit_conflict"
                conflict_reasons.append(f"Несовместимые единицы измерения: '{v.unit}' vs '{l.unit}'")

            # 5. Слабое текстовое сходство
            if cand.sim_text < 0.40 and cand.sim_text >= 0.20:
                is_ambiguous = True
                ambiguity_type = ambiguity_type or "weak_text"
                conflict_reasons.append(f"Пограничное текстовое сходство ({cand.sim_text:.2f})")

            competing_cands = []
            for c_j, c_cand in alt_pairs[:3]:
                c_l = lsr[c_j]
                competing_cands.append({
                    "lsr_num": c_l.num,
                    "lsr_row": c_l.row,
                    "lsr_name": c_l.name,
                    "lsr_unit": c_l.unit,
                    "lsr_qty": c_l.qty,
                    "lsr_section": getattr(c_l, "section", ""),
                    "score": round(c_cand.confidence, 4),
                    "text_sim": round(c_cand.sim_text, 4),
                    "reason": c_cand.explanation
                })

            results.append({
                "vor": v.num,
                "lsr": l.num,
                "cls": status,
                "score": round(cand.confidence, 4),
                "text_sim": round(cand.sim_text, 4),
                "explanation": cand.explanation,
                "candidate": cand,
                "vor_item": v,
                "lsr_item": l,
                "vor_row": v.row,
                "lsr_row": l.row,
                "is_ambiguous": is_ambiguous,
                "ambiguity_type": ambiguity_type,
                "conflict_reason": "; ".join(conflict_reasons),
                "competing_candidates": competing_cands,
                "margin": round(margin, 4) if margin is not None else 1.0,
            })
        else:
            # Позиция ВОР не нашла пары
            best_j = int(text_sim_matrix[i].argmax()) if nl > 0 else -1
            best_sim = float(text_sim_matrix[i, best_j]) if best_j >= 0 else 0.0

            is_dup = False
            if best_j in matched_l and best_sim >= thr:
                other_i, other_cand = matched_l[best_j]
                other_v = vor[other_i]
                if other_v.name == v.name and other_v.unit == v.unit and abs(other_v.qty - v.qty) < 1e-6:
                    results.append({
                        "vor": v.num,
                        "lsr": lsr[best_j].num,
                        "cls": "Дубль",
                        "score": round(best_sim, 4),
                        "text_sim": round(best_sim, 4),
                        "explanation": f"Дублирует позицию ВОР №{other_v.num}",
                        "candidate": None,
                        "vor_item": v,
                        "lsr_item": lsr[best_j],
                        "vor_row": v.row,
                        "lsr_row": lsr[best_j].row,
                        "is_ambiguous": False,
                        "ambiguity_type": None,
                        "conflict_reason": "",
                        "competing_candidates": [],
                        "margin": 1.0,
                    })
                    is_dup = True

            if not is_dup:
                expl = "В смете ЛСР не найдено подходящей расценки"
                if best_sim > 0.20:
                    expl += f" (наиболее близкая строка ЛСР №{lsr[best_j].num} имеет сходство {best_sim:.2f})"

                sorted_j = sorted(range(nl), key=lambda c_j: -text_sim_matrix[i, c_j])[:3] if nl > 0 else []
                competing_cands = []
                for c_j in sorted_j:
                    c_l = lsr[c_j]
                    c_sim = float(text_sim_matrix[i, c_j])
                    competing_cands.append({
                        "lsr_num": c_l.num,
                        "lsr_row": c_l.row,
                        "lsr_name": c_l.name,
                        "lsr_unit": c_l.unit,
                        "lsr_qty": c_l.qty,
                        "lsr_section": getattr(c_l, "section", ""),
                        "score": round(c_sim, 4),
                        "text_sim": round(c_sim, 4),
                        "reason": "Ближайший кандидат по n-граммам"
                    })

                results.append({
                    "vor": v.num,
                    "lsr": None,
                    "cls": "Нет в рассматриваемой смете",
                    "score": round(best_sim, 4),
                    "text_sim": round(best_sim, 4),
                    "explanation": expl,
                    "candidate": None,
                    "vor_item": v,
                    "lsr_item": None,
                    "vor_row": v.row,
                    "lsr_row": None,
                    "is_ambiguous": True,
                    "ambiguity_type": "unmatched",
                    "conflict_reason": "Позиция ВОР не нашла пары в смете ЛСР",
                    "competing_candidates": competing_cands,
                    "margin": 0.0,
                })

    # Обработка позиций ЛСР, оставшихся без пары
    for j, l in enumerate(lsr):
        if j not in matched_l:
            results.append({
                "vor": None,
                "lsr": l.num,
                "cls": "Нет в ВОР",
                "score": 0.0,
                "text_sim": 0.0,
                "explanation": "Сметная расценка отсутствует в ведомости объемов работ",
                "candidate": None,
                "vor_item": None,
                "lsr_item": l,
                "vor_row": None,
                "lsr_row": l.row,
            })

    return results
