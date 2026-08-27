"""
Бизнес-логика контроля качества измерений: правила Westgard.

Раньше эта логика жила прямо внутри charts.py вперемешку с построением
графика (Plotly ничего не должен знать про то, ЧТО считается нарушением —
только КАК это нарисовать). Здесь же пороги — не литералы 1/2/3/4/9/10 по
тексту функции, а именованные константы из config.py, чтобы правило и его
параметр были видны сразу, без необходимости листать код.
"""

import pandas as pd

import config


def check_westgard_violations(values: pd.Series, target: float, sd: float) -> pd.Series:
    """
    Возвращает булеву серию: True там, где нарушено хотя бы одно правило Westgard.

    Реализованы базовые правила:
      1_3s  — одна точка за пределами 3 SD
      2_2s  — две подряд точки за пределами 2 SD с одной стороны
      4_1s  — четыре подряд точки за пределами 1 SD с одной стороны
      10x   — десять подряд точек с одной стороны от среднего
    """
    if sd <= 0:
        raise ValueError("SD метода должно быть положительным для проверки правил Westgard")

    z = (values - target) / sd  # нормированное отклонение в единицах SD
    violation = pd.Series(False, index=values.index)

    # 1_3s
    violation |= z.abs() > config.WESTGARD_1_3S_THRESHOLD

    # 2_2s
    w = config.WESTGARD_2_2S_WINDOW
    thr = config.WESTGARD_2_2S_THRESHOLD
    for i in range(w - 1, len(z)):
        window = z.iloc[i - w + 1: i + 1]
        if (window > thr).all() or (window < -thr).all():
            violation.iloc[i - w + 1: i + 1] = True

    # 4_1s
    w = config.WESTGARD_4_1S_WINDOW
    thr = config.WESTGARD_4_1S_THRESHOLD
    for i in range(w - 1, len(z)):
        window = z.iloc[i - w + 1: i + 1]
        if (window > thr).all() or (window < -thr).all():
            violation.iloc[i - w + 1: i + 1] = True

    # 10x — все подряд с одной стороны от среднего (порог 0)
    w = config.WESTGARD_10X_WINDOW
    for i in range(w - 1, len(z)):
        window = z.iloc[i - w + 1: i + 1]
        if (window > 0).all() or (window < 0).all():
            violation.iloc[i - w + 1: i + 1] = True

    return violation
