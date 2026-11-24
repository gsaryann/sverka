"""Модуль расчёта физических разниц объёмов и финансового риска по Методике Минстроя РФ № 421/пр."""
from typing import Optional, Tuple
import units


def calculate_item_risk(
    vor_qty: Optional[float],
    vor_unit: Optional[str],
    lsr_qty: Optional[float],
    lsr_unit: Optional[str],
    unit_price: Optional[float]
) -> Tuple[Optional[float], Optional[float], str]:
    """
    Рассчитывает:
      1. Разницу объёмов в единицах ЛСР (единицах цены): delta_v_lsr = q_lsr - (q_vor в единицах lsr)
      2. Финансовый риск: |delta_v_lsr| * unit_price (только при совпадающих размерностях)
      3. Статус риска: 'OK', 'Расхождение', 'нельзя оценить', 'цена не найдена'

    Возвращает: (delta_v_lsr, risk_rub, status_str)
    """
    if vor_qty is None or lsr_qty is None:
        if vor_qty is not None and lsr_qty is None:
            # Нет в смете -> риск не начисляется без сметной расценки (0.0)
            return None, 0.0, "нет в смете"
        if vor_qty is None and lsr_qty is not None:
            # Лишняя позиция в смете
            if unit_price is not None and unit_price > 0:
                return float(lsr_qty), round(float(lsr_qty) * float(unit_price), 2), "лишняя позиция"
            return float(lsr_qty), 0.0, "лишняя позиция"
        return None, None, "нельзя оценить"

    dim_v, base_v = units.to_base(vor_qty, vor_unit or "")
    dim_l, k_l = units.parse_unit(lsr_unit or "")

    if not dim_v or not dim_l or dim_v != dim_l or not k_l:
        return None, None, "нельзя оценить"

    # Объём ВОР, переведённый в единицы ЛСР
    vor_in_lsr_units = base_v / k_l
    dv = float(lsr_qty) - vor_in_lsr_units

    if abs(dv) < 1e-4:
        return 0.0, 0.0, "OK"

    dv_rounded = round(dv, 4)
    if unit_price is not None and unit_price > 0:
        risk_rub = round(abs(dv) * float(unit_price), 2)
        return dv_rounded, risk_rub, "Расхождение"
    else:
        return dv_rounded, 0.0, "цена не найдена"
