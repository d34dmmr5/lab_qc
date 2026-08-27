"""
Обработка кривых угла смачивания — вся математика и парсинг файлов,
без единой строчки Streamlit-кода (страница pages/wetting.py дергает
эти функции и только рисует UI).

Пайплайн:
  1. read_raw_file            — читает загруженный .xls/.xlsx/.csv как есть
  2. compute_averaged_curve   — среднее по параллельным измерениям, SD,
                                 доверительный интервал по Стьюденту, cos(угла)
  3. fit_exponential / fit_power_law / fit_polynomial — аппроксимация
  4. linearize_exponential / linearize_power — линеаризация через замену
     переменных (только для моделей, нелинейных по параметрам)
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import curve_fit

import config
from models import AveragedCurve, FitResult, LinearizationResult


class WettingDataError(ValueError):
    """Ошибка входных данных (не хватает точек, не выбраны нужные столбцы и т.п.)."""


# --------------------------------------------------------------------------
# Чтение файлов
# --------------------------------------------------------------------------

def read_raw_file(uploaded_file, sheet_name=0) -> pd.DataFrame:
    """Читает загруженный файл в DataFrame без интерпретации структуры."""
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
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
    """Список листов книги Excel (для .xls/.xlsx). Для .csv — пустой список."""
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
    liquid_name: str,
    source_file: Optional[str] = None,
    confidence: float = config.DEFAULT_CONFIDENCE,
) -> AveragedCurve:
    """
    Считает среднее по параллельным измерениям угла смачивания, выборочное SD,
    полуширину доверительного интервала по распределению Стьюдента и
    cos(угла). Угол в исходных данных предполагается в градусах.
    """
    if len(angle_cols) < config.MIN_PARALLEL_MEASUREMENTS:
        raise WettingDataError(
            f"Нужно минимум {config.MIN_PARALLEL_MEASUREMENTS} столбца(ов) "
            f"с параллельными измерениями угла, выбрано {len(angle_cols)}"
        )
    if time_col in angle_cols:
        raise WettingDataError("Столбец времени не может совпадать со столбцом угла")

    work = df[[time_col] + angle_cols].copy()
    work[time_col] = pd.to_numeric(work[time_col], errors="coerce")
    for c in angle_cols:
        work[c] = pd.to_numeric(work[c], errors="coerce")
    work = work.dropna(subset=[time_col])

    if work.empty:
        raise WettingDataError("После преобразования столбца времени в число не осталось строк")

    values = work[angle_cols]
    n_per_row = values.notna().sum(axis=1)
    mean = values.mean(axis=1)
    sd = values.std(axis=1, ddof=1)

    t_value = n_per_row.apply(
        lambda n: stats.t.ppf(1 - (1 - confidence) / 2, df=n - 1) if n > 1 else np.nan
    )
    ci_halfwidth = t_value * sd / np.sqrt(n_per_row.where(n_per_row > 0))
    cos_theta = np.cos(np.radians(mean))

    points = pd.DataFrame(
        {
            "time_s": work[time_col].values,
            "angle_mean": mean.values,
            "angle_sd": sd.values,
            "angle_ci95": ci_halfwidth.values,
            "cos_theta": cos_theta.values,
        }
    ).dropna(subset=["angle_mean"]).sort_values("time_s").reset_index(drop=True)

    if points.empty:
        raise WettingDataError("Нет валидных точек после усреднения — проверьте выбор столбцов")

    return AveragedCurve(liquid_name=liquid_name, source_file=source_file, points=points)


# --------------------------------------------------------------------------
# Нелинейная аппроксимация
# --------------------------------------------------------------------------

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
    """theta(t) = theta_inf + (theta0 - theta_inf) * exp(-t / tau) — релаксация к равновесию."""
    if len(t) < 4:
        return FitResult(success=False, model="exponential", error="Недостаточно точек (нужно минимум 4)")

    theta0_guess = float(theta[0])
    theta_inf_guess = float(theta[-1])
    span = max(float(t[-1] - t[0]), 1e-6)
    p0 = [theta_inf_guess, theta0_guess, span / 5]
    try:
        popt, _ = curve_fit(_exp_model, t, theta, p0=p0, maxfev=config.CURVE_FIT_MAXFEV)
    except (RuntimeError, ValueError) as e:
        return FitResult(success=False, model="exponential", error=str(e))

    pred_fn = lambda tt: _exp_model(np.asarray(tt, dtype=float), *popt)
    r2 = _r_squared(theta, pred_fn(t))
    return FitResult(
        success=True, model="exponential",
        params={"theta_inf": popt[0], "theta0": popt[1], "tau": popt[2]},
        r_squared=r2, predict=pred_fn,
    )


def fit_power_law(t: np.ndarray, theta: np.ndarray) -> FitResult:
    """theta(t) = theta_inf + a * t^(-n), t > 0 — степенной закон растекания."""
    mask = t > 0
    t_fit, theta_fit = t[mask], theta[mask]
    if len(t_fit) < 4:
        return FitResult(success=False, model="power_law", error="Недостаточно точек с t > 0 (нужно минимум 4)")

    theta_inf_guess = float(theta_fit[-1])
    a_guess = float(theta_fit[0] - theta_inf_guess) or 1.0
    p0 = [theta_inf_guess, a_guess, 0.3]
    try:
        popt, _ = curve_fit(
            _power_model, t_fit, theta_fit, p0=p0, maxfev=config.CURVE_FIT_MAXFEV,
            bounds=([-np.inf, -np.inf, config.POWER_LAW_N_MIN], [np.inf, np.inf, config.POWER_LAW_N_MAX]),
        )
    except (RuntimeError, ValueError) as e:
        return FitResult(success=False, model="power_law", error=str(e))

    pred_fn = lambda tt: _power_model(np.asarray(tt, dtype=float), *popt)
    r2 = _r_squared(theta_fit, pred_fn(t_fit))
    return FitResult(
        success=True, model="power_law",
        params={"theta_inf": popt[0], "a": popt[1], "n": popt[2]},
        r_squared=r2, predict=pred_fn,
    )


def fit_polynomial(t: np.ndarray, theta: np.ndarray, degree: int = config.POLYNOMIAL_DEGREE_DEFAULT) -> FitResult:
    """
    Полиномиальная регрессия theta(t) = c_n*t^n + ... + c_0.
    Уже линейна по коэффициентам — находятся напрямую МНК (np.polyfit),
    без замены переменных. theta_inf здесь — значение модели в последней
    измеренной точке (не физический параметр равновесия).
    """
    degree = int(degree)
    if not (config.POLYNOMIAL_DEGREE_MIN <= degree <= config.POLYNOMIAL_DEGREE_MAX):
        return FitResult(
            success=False, model="polynomial",
            error=f"Степень полинома должна быть от {config.POLYNOMIAL_DEGREE_MIN} "
                  f"до {config.POLYNOMIAL_DEGREE_MAX}",
        )
    if len(t) < degree + 2:
        return FitResult(
            success=False, model="polynomial",
            error=f"Недостаточно точек для полинома степени {degree} "
                  f"(нужно минимум {degree + 2}, есть {len(t)})",
        )

    coeffs = np.polyfit(t, theta, degree)
    poly = np.poly1d(coeffs)
    pred_fn = lambda tt: poly(np.asarray(tt, dtype=float))
    r2 = _r_squared(theta, pred_fn(t))

    params = {"degree": degree, "theta_inf": float(poly(t[-1]))}
    for power, c in zip(range(degree, -1, -1), coeffs):
        params[f"c{power}"] = float(c)

    return FitResult(success=True, model="polynomial", params=params, r_squared=r2, predict=pred_fn)


# --------------------------------------------------------------------------
# Линеаризация через замену переменных
# --------------------------------------------------------------------------

def linearize_exponential(t: np.ndarray, theta: np.ndarray, theta_inf: float) -> LinearizationResult:
    """ln(theta - theta_inf) = ln(theta0 - theta_inf) - t/tau — прямая с наклоном -1/tau."""
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
        success=True, x=x, y=y, slope=slope, intercept=intercept, r_squared=r_value ** 2,
        derived={"tau": tau, "theta0_est": np.exp(intercept) + theta_inf},
        x_label="t, с", y_label="ln(θ − θ∞)",
    )


def linearize_power(t: np.ndarray, theta: np.ndarray, theta_inf: float) -> LinearizationResult:
    """log10(theta - theta_inf) = log10(a) - n*log10(t) — прямая с наклоном -n."""
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
        success=True, x=x, y=y, slope=slope, intercept=intercept, r_squared=r_value ** 2,
        derived={"n": n, "a": a}, x_label="log10(t)", y_label="log10(θ − θ∞)",
    )
