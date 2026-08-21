"""
Обработка кривых угла смачивания.

Пайплайн:
  1. read_raw_file       — читает загруженный .xls/.xlsx/.csv в DataFrame как есть
  2. compute_averaged_curve — по выбранным столбцам считает среднее по
                              параллельным измерениям, SD, доверительный
                              интервал по Стьюденту и cos(угла)
  3. fit_exponential / fit_power_law — нелинейная аппроксимация всей кривой
  4. linearize_exponential / linearize_power — та же кривая в спрямляющих
     координатах (замена переменных), с обычной линейной регрессией
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import curve_fit


# --------------------------------------------------------------------------
# Чтение файлов
# --------------------------------------------------------------------------

def read_raw_file(uploaded_file, sheet_name=0) -> pd.DataFrame:
    """
    Читает загруженный через st.file_uploader объект в DataFrame без какой-либо
    интерпретации структуры — дальше пользователь сам указывает столбцы.
    """
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        # Пробуем автоматически определить разделитель (',' или ';' — частый
        # случай для файлов, сохранённых в русской локали Excel).
        try:
            return pd.read_csv(uploaded_file, sep=None, engine="python")
        except Exception:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file)
    elif name.endswith(".xls"):
        return pd.read_excel(uploaded_file, sheet_name=sheet_name, engine="xlrd")
    else:  # .xlsx, .xlsm
        return pd.read_excel(uploaded_file, sheet_name=sheet_name, engine="openpyxl")


def list_excel_sheets(uploaded_file) -> list[str]:
    """Список листов книги Excel (для .xls/.xlsx). Для .csv возвращает []."""
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return []
    engine = "xlrd" if name.endswith(".xls") else "openpyxl"
    uploaded_file.seek(0)
    xls = pd.ExcelFile(uploaded_file, engine=engine)
    return xls.sheet_names


# --------------------------------------------------------------------------
# Усреднение параллельных измерений
# --------------------------------------------------------------------------

def compute_averaged_curve(
    df: pd.DataFrame,
    time_col: str,
    angle_cols: list[str],
    confidence: float = 0.95,
) -> pd.DataFrame:
    """
    Считает среднее по параллельным измерениям угла смачивания, выборочное SD,
    полуширину доверительного интервала по распределению Стьюдента и
    cos(угла). Угол в исходных данных предполагается в градусах.

    Возвращает DataFrame с колонками:
      time_s, angle_mean, angle_sd, angle_ci95, cos_theta
    отсортированный по времени.
    """
    if len(angle_cols) < 2:
        raise ValueError("Нужно минимум 2 столбца с параллельными измерениями угла")

    work = df[[time_col] + angle_cols].copy()
    work[time_col] = pd.to_numeric(work[time_col], errors="coerce")
    for c in angle_cols:
        work[c] = pd.to_numeric(work[c], errors="coerce")
    work = work.dropna(subset=[time_col])

    values = work[angle_cols]
    n_per_row = values.notna().sum(axis=1)
    mean = values.mean(axis=1)
    sd = values.std(axis=1, ddof=1)

    # t-коэффициент зависит от числа непустых параллельных измерений в строке
    # (обычно одинаково для всех строк, но считаем по месту на всякий случай)
    t_value = n_per_row.apply(
        lambda n: stats.t.ppf(1 - (1 - confidence) / 2, df=n - 1) if n > 1 else np.nan
    )
    ci_halfwidth = t_value * sd / np.sqrt(n_per_row.where(n_per_row > 0))
    cos_theta = np.cos(np.radians(mean))

    result = pd.DataFrame(
        {
            "time_s": work[time_col].values,
            "angle_mean": mean.values,
            "angle_sd": sd.values,
            "angle_ci95": ci_halfwidth.values,
            "cos_theta": cos_theta.values,
        }
    ).dropna(subset=["angle_mean"])

    return result.sort_values("time_s").reset_index(drop=True)


# --------------------------------------------------------------------------
# Нелинейная аппроксимация
# --------------------------------------------------------------------------

@dataclass
class FitResult:
    success: bool
    model: str
    params: dict = field(default_factory=dict)
    r_squared: float | None = None
    predict: Callable[[np.ndarray], np.ndarray] | None = None
    error: str | None = None


def _exp_model(t, theta_inf, theta0, tau):
    return theta_inf + (theta0 - theta_inf) * np.exp(-t / tau)


def _power_model(t, theta_inf, a, n):
    t_safe = np.where(t <= 0, np.nan, t)
    return theta_inf + a * np.power(t_safe, -n)


def _r_squared(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = ~np.isnan(y_pred)
    y_true, y_pred = y_true[mask], y_pred[mask]
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    return float(1 - ss_res / ss_tot) if ss_tot > 0 else float("nan")


def fit_exponential(t: np.ndarray, theta: np.ndarray) -> FitResult:
    """
    theta(t) = theta_inf + (theta0 - theta_inf) * exp(-t / tau)

    Модель релаксации к равновесию — подходит, когда угол монотонно
    приближается к плато без долгого степенного "хвоста".
    """
    theta0_guess = float(theta[0])
    theta_inf_guess = float(theta[-1])
    span = max(float(t[-1] - t[0]), 1e-6)
    p0 = [theta_inf_guess, theta0_guess, span / 5]
    try:
        popt, _ = curve_fit(_exp_model, t, theta, p0=p0, maxfev=20000)
    except (RuntimeError, ValueError) as e:
        return FitResult(success=False, model="exponential", error=str(e))

    pred_fn = lambda tt: _exp_model(np.asarray(tt, dtype=float), *popt)
    r2 = _r_squared(theta, pred_fn(t))
    return FitResult(
        success=True,
        model="exponential",
        params={"theta_inf": popt[0], "theta0": popt[1], "tau": popt[2]},
        r_squared=r2,
        predict=pred_fn,
    )


def fit_power_law(t: np.ndarray, theta: np.ndarray) -> FitResult:
    """
    theta(t) = theta_inf + a * t^(-n),  t > 0

    Степенной закон растекания (Таннер/Хоффман) — подходит, когда кривая
    имеет длинный нелинейный "хвост" и не описывается одной экспонентой.
    Точки с t <= 0 из аппроксимации исключаются.
    """
    mask = t > 0
    t_fit, theta_fit = t[mask], theta[mask]
    if len(t_fit) < 4:
        return FitResult(success=False, model="power_law", error="Недостаточно точек с t > 0")

    theta_inf_guess = float(theta_fit[-1])
    a_guess = float(theta_fit[0] - theta_inf_guess) or 1.0
    p0 = [theta_inf_guess, a_guess, 0.3]
    try:
        popt, _ = curve_fit(
            _power_model, t_fit, theta_fit, p0=p0, maxfev=20000,
            bounds=([-np.inf, -np.inf, 1e-4], [np.inf, np.inf, 10]),
        )
    except (RuntimeError, ValueError) as e:
        return FitResult(success=False, model="power_law", error=str(e))

    pred_fn = lambda tt: _power_model(np.asarray(tt, dtype=float), *popt)
    r2 = _r_squared(theta_fit, pred_fn(t_fit))
    return FitResult(
        success=True,
        model="power_law",
        params={"theta_inf": popt[0], "a": popt[1], "n": popt[2]},
        r_squared=r2,
        predict=pred_fn,
    )


# --------------------------------------------------------------------------
# Линеаризация через замену переменных
# --------------------------------------------------------------------------

@dataclass
class LinearizationResult:
    success: bool
    x: np.ndarray
    y: np.ndarray
    slope: float | None = None
    intercept: float | None = None
    r_squared: float | None = None
    derived: dict = field(default_factory=dict)
    error: str | None = None
    x_label: str = ""
    y_label: str = ""


def linearize_exponential(t: np.ndarray, theta: np.ndarray, theta_inf: float) -> LinearizationResult:
    """
    Из theta(t) = theta_inf + (theta0-theta_inf)*exp(-t/tau) следует:
        ln(theta - theta_inf) = ln(theta0 - theta_inf) - t/tau
    То есть в осях [t ; ln(theta - theta_inf)] кривая должна лечь на прямую
    с наклоном -1/tau. Точки, где theta <= theta_inf, исключаются (лог не определён).
    """
    diff = theta - theta_inf
    mask = diff > 0
    if mask.sum() < 3:
        return LinearizationResult(
            success=False, x=np.array([]), y=np.array([]),
            error="Слишком мало точек с theta > theta_inf для линеаризации "
                  "(проверьте значение theta_inf)",
        )
    x = t[mask]
    y = np.log(diff[mask])
    slope, intercept, r_value, _, _ = stats.linregress(x, y)
    tau = -1 / slope if slope != 0 else float("inf")
    return LinearizationResult(
        success=True, x=x, y=y,
        slope=slope, intercept=intercept, r_squared=r_value ** 2,
        derived={"tau": tau, "theta0_est": intercept and (np.exp(intercept) + theta_inf)},
        x_label="t, с",
        y_label="ln(θ − θ∞)",
    )


def linearize_power(t: np.ndarray, theta: np.ndarray, theta_inf: float) -> LinearizationResult:
    """
    Из theta(t) = theta_inf + a*t^(-n) следует:
        log10(theta - theta_inf) = log10(a) - n*log10(t)
    В осях [log10(t) ; log10(theta - theta_inf)] — прямая с наклоном -n.
    """
    diff = theta - theta_inf
    mask = (diff > 0) & (t > 0)
    if mask.sum() < 3:
        return LinearizationResult(
            success=False, x=np.array([]), y=np.array([]),
            error="Слишком мало точек с theta > theta_inf и t > 0 для линеаризации "
                  "(проверьте значение theta_inf)",
        )
    x = np.log10(t[mask])
    y = np.log10(diff[mask])
    slope, intercept, r_value, _, _ = stats.linregress(x, y)
    n = -slope
    a = 10 ** intercept
    return LinearizationResult(
        success=True, x=x, y=y,
        slope=slope, intercept=intercept, r_squared=r_value ** 2,
        derived={"n": n, "a": a},
        x_label="log10(t)",
        y_label="log10(θ − θ∞)",
    )
