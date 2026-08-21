"""
Построение карты Шухарта (Plotly) и проверка правил Westgard на нарушения.
"""

import pandas as pd
import plotly.graph_objects as go


def check_westgard_violations(values: pd.Series, target: float, sd: float) -> pd.Series:
    """
    Возвращает булеву серию: True там, где нарушено хотя бы одно правило Westgard.
    Реализованы базовые правила:
      1_3s  — одна точка за пределами 3 SD
      2_2s  — две подряд точки за пределами 2 SD с одной стороны
      4_1s  — четыре подряд точки за пределами 1 SD с одной стороны
      10x   — десять подряд точек с одной стороны от среднего
    """
    z = (values - target) / sd  # нормированное отклонение в единицах SD
    violation = pd.Series(False, index=values.index)

    # 1_3s
    violation |= z.abs() > 3

    # 2_2s
    for i in range(1, len(z)):
        if z.iloc[i] > 2 and z.iloc[i - 1] > 2:
            violation.iloc[i] = True
            violation.iloc[i - 1] = True
        if z.iloc[i] < -2 and z.iloc[i - 1] < -2:
            violation.iloc[i] = True
            violation.iloc[i - 1] = True

    # 4_1s
    for i in range(3, len(z)):
        window = z.iloc[i - 3 : i + 1]
        if (window > 1).all() or (window < -1).all():
            violation.iloc[i - 3 : i + 1] = True

    # 10x
    for i in range(9, len(z)):
        window = z.iloc[i - 9 : i + 1]
        if (window > 0).all() or (window < 0).all():
            violation.iloc[i - 9 : i + 1] = True

    return violation


def build_shewhart_chart(df: pd.DataFrame, target: float, sd: float, unit: str) -> go.Figure:
    """
    df должен содержать колонки: measured_at, measured_value.
    Рисует центральную линию, зоны 1/2/3 SD и точки, подсвечивая нарушения.
    """
    violations = check_westgard_violations(df["measured_value"], target, sd)

    fig = go.Figure()

    # закрашенные зоны ±1SD, ±2SD, ±3SD (визуальные "коридоры")
    for k, opacity in [(3, 0.06), (2, 0.10), (1, 0.14)]:
        fig.add_hrect(
            y0=target - k * sd, y1=target + k * sd,
            fillcolor="green", opacity=opacity, line_width=0,
        )

    # центральная линия и границы
    fig.add_hline(y=target, line_color="black", line_dash="dash", annotation_text="Целевое значение")
    for k in (1, 2, 3):
        fig.add_hline(y=target + k * sd, line_color="gray", line_width=1)
        fig.add_hline(y=target - k * sd, line_color="gray", line_width=1)

    colors = ["red" if v else "steelblue" for v in violations]

    fig.add_trace(
        go.Scatter(
            x=df["measured_at"],
            y=df["measured_value"],
            mode="lines+markers",
            marker=dict(color=colors, size=9),
            line=dict(color="steelblue", width=1),
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
