"""
Построение графиков (Plotly). Только визуализация — решение о том, что
считать нарушением Westgard, принимает services/qc_service.py, а не этот
модуль (раньше эта логика была перемешана прямо внутри build_shewhart_chart).
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go

import config
from models import FitResult, LinearizationResult
from services.qc_service import check_westgard_violations


def build_shewhart_chart(df: pd.DataFrame, target: float, sd: float, unit: str) -> go.Figure:
    """
    df должен содержать колонки: measured_at, measured_value.
    Рисует центральную линию, зоны 1/2/3 SD и точки, подсвечивая нарушения.
    """
    violations = check_westgard_violations(df["measured_value"], target, sd)

    fig = go.Figure()

    for k in config.SHEWHART_SIGMA_ZONES:
        fig.add_hrect(
            y0=target - k * sd, y1=target + k * sd,
            fillcolor=config.SHEWHART_ZONE_COLOR,
            opacity=config.SHEWHART_ZONE_OPACITY.get(k, 0.1),
            line_width=0,
        )

    fig.add_hline(
        y=target, line_color=config.SHEWHART_TARGET_LINE_COLOR,
        line_dash="dash", annotation_text="Целевое значение",
    )
    for k in config.SHEWHART_SIGMA_ZONES:
        fig.add_hline(y=target + k * sd, line_color=config.SHEWHART_LINE_COLOR, line_width=1)
        fig.add_hline(y=target - k * sd, line_color=config.SHEWHART_LINE_COLOR, line_width=1)

    colors = [config.SHEWHART_VIOLATION_COLOR if v else config.SHEWHART_POINT_COLOR for v in violations]

    fig.add_trace(
        go.Scatter(
            x=df["measured_at"], y=df["measured_value"],
            mode="lines+markers",
            marker=dict(color=colors, size=9),
            line=dict(color=config.SHEWHART_POINT_COLOR, width=1),
            name="Результаты",
            hovertemplate="%{x}<br>Значение: %{y}<extra></extra>",
        )
    )

    fig.update_layout(
        title="Карта Шухарта",
        yaxis_title=f"Значение, {unit}",
        xaxis_title="Дата измерения",
        showlegend=False,
        height=500,
    )
    return fig


def build_wetting_raw_chart(t: np.ndarray, theta: np.ndarray, ci: Optional[np.ndarray] = None) -> go.Figure:
    """Точки усреднённой кривой угол(время) с доверительными интервалами."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=t, y=theta, mode="markers", name="Среднее по параллельным",
        error_y=dict(type="data", array=ci, visible=ci is not None),
        marker=dict(color=config.SHEWHART_POINT_COLOR, size=6),
    ))
    fig.update_layout(
        title="Угол смачивания во времени", xaxis_title="Время, с",
        yaxis_title="Угол, °", height=420,
    )
    return fig


def build_wetting_fit_chart(
    t: np.ndarray, theta: np.ndarray, fits: list[FitResult], model_labels: dict[str, str],
) -> go.Figure:
    """Данные + одна или несколько наложенных кривых аппроксимации."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=t, y=theta, mode="markers", name="Данные",
        marker=dict(color=config.SHEWHART_POINT_COLOR, size=6),
    ))
    if len(t) > 0:
        t_dense = np.linspace(t.min(), t.max(), config.FIT_DENSE_POINTS)
        for fit in fits:
            if not fit.success:
                continue
            label = model_labels.get(fit.model, fit.model)
            y_dense = fit.predict(t_dense)
            fig.add_trace(go.Scatter(
                x=t_dense, y=y_dense, mode="lines", name=f"{label} (R²={fit.r_squared:.4f})",
            ))
    fig.update_layout(
        title="Данные и аппроксимация", xaxis_title="Время, с", yaxis_title="Угол, °", height=450,
    )
    return fig


def build_linearization_chart(lin: LinearizationResult) -> go.Figure:
    """Спрямлённая кривая + линия линейной регрессии."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=lin.x, y=lin.y, mode="markers", name="Точки",
        marker=dict(color=config.SHEWHART_POINT_COLOR),
    ))
    if len(lin.x) > 0:
        x_line = np.array([lin.x.min(), lin.x.max()])
        y_line = lin.slope * x_line + lin.intercept
        fig.add_trace(go.Scatter(
            x=x_line, y=y_line, mode="lines",
            name=f"Линейная регрессия (R²={lin.r_squared:.4f})",
            line=dict(color="firebrick"),
        ))
    fig.update_layout(
        title="Спрямлённая кривая", xaxis_title=lin.x_label, yaxis_title=lin.y_label, height=420,
    )
    return fig


def build_archived_curve_chart(points: pd.DataFrame) -> go.Figure:
    """Простой график сохранённой в архиве кривой (без аппроксимации)."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=points["time_s"], y=points["angle_mean"], mode="markers+lines"))
    fig.update_layout(xaxis_title="Время, с", yaxis_title="Угол, °", height=350)
    return fig
