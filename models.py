"""
Типизированные модели данных.

DataFrame из pandas остаётся там, где он действительно уместен — для
табличных числовых рядов (усреднённая кривая угла смачивания, точки
на графике), потому что это ровно то, для чего pandas создан, и то,
что напрямую нужно plotly/scipy/numpy. Но сущности, которые хранятся
в БД как строки (методы контроля, результаты, кривые), теперь
представлены dataclass'ами — с этим удобнее работать в коде и
проверять типы, чем таскать `row["...']` из DataFrame без каких-либо
гарантий структуры.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------
# Карта Шухарта / контроль качества
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ControlMethod:
    id: int
    name: str
    unit: str
    target_value: float
    target_sd: float
    created_at: Optional[datetime] = None


@dataclass(frozen=True)
class ControlResult:
    id: int
    method_id: int
    measured_value: float
    measured_at: datetime
    operator: str
    comment: str = ""
    created_at: Optional[datetime] = None


# --------------------------------------------------------------------------
# Угол смачивания
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class WettingCurveRecord:
    """Метаданные сохранённой (обработанной + аппроксимированной) кривой."""
    id: int
    method_id: int
    liquid_name: str
    source_file: Optional[str]
    fit_model: Optional[str]
    theta_inf: Optional[float]
    fit_param2_name: Optional[str]
    fit_param2_value: Optional[float]
    r_squared: Optional[float]
    result_id: Optional[int]
    fit_coeffs_json: Optional[str]
    created_at: Optional[datetime] = None


@dataclass
class AveragedCurve:
    """
    Усреднённая по параллельным измерениям кривая угол(время).
    points — DataFrame с колонками time_s, angle_mean, angle_sd,
    angle_ci95, cos_theta (табличный числовой ряд — здесь pandas уместен).
    """
    liquid_name: str
    source_file: Optional[str]
    points: pd.DataFrame

    @property
    def t(self) -> np.ndarray:
        return self.points["time_s"].to_numpy(dtype=float)

    @property
    def theta(self) -> np.ndarray:
        return self.points["angle_mean"].to_numpy(dtype=float)

    def __len__(self) -> int:
        return len(self.points)


@dataclass
class FitResult:
    """Результат нелинейной (или полиномиальной) аппроксимации кривой."""
    success: bool
    model: str
    params: dict = field(default_factory=dict)
    r_squared: Optional[float] = None
    predict: Optional[Callable[[np.ndarray], np.ndarray]] = None
    error: Optional[str] = None

    @property
    def theta_inf(self) -> Optional[float]:
        return self.params.get("theta_inf")


@dataclass
class LinearizationResult:
    """Результат линеаризации кривой через замену переменных."""
    success: bool
    x: np.ndarray
    y: np.ndarray
    slope: Optional[float] = None
    intercept: Optional[float] = None
    r_squared: Optional[float] = None
    derived: dict = field(default_factory=dict)
    error: Optional[str] = None
    x_label: str = ""
    y_label: str = ""
