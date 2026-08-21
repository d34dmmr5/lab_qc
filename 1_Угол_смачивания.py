"""
Обработка кривых угла смачивания: загрузка .xls/.xlsx/.csv, усреднение
параллельных измерений, нелинейная аппроксимация и линеаризация через
замену переменных. Равновесное значение угла (θ∞) можно сохранить как
точку на карту Шухарта соответствующего метода.
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from db import (
    get_methods, add_method, add_result,
    add_wetting_curve, add_wetting_points,
    get_wetting_curves, get_wetting_points, delete_wetting_curve,
)
import wetting as w

st.set_page_config(page_title="Угол смачивания", layout="wide")
st.title("💧 Угол смачивания: обработка кривых")

MODEL_LABELS = {
    "exponential": "Экспоненциальная релаксация",
    "power_law": "Степенной закон",
}

# --- Сессионное состояние для промежуточных результатов ---
for key, default in [
    ("wet_avg_df", None), ("wet_liquid_name", ""), ("wet_source_file", None),
    ("wet_fit_exp", None), ("wet_fit_pow", None), ("wet_theta_inf_override", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# --- Боковая панель: метод контроля (угол смачивания — это тоже control_method) ---
with st.sidebar:
    st.header("Метод контроля")
    methods_df = get_methods()

    if methods_df.empty:
        st.info("Методов пока нет — создайте метод для угла смачивания.")
        method_id = None
    else:
        method_name = st.selectbox("Метод (карта Шухарта)", methods_df["name"])
        method_row = methods_df[methods_df["name"] == method_name].iloc[0]
        method_id = int(method_row["id"])
        st.caption(
            f"Целевое значение: {method_row['target_value']} {method_row['unit']}, "
            f"SD: {method_row['target_sd']}"
        )

    with st.expander("➕ Новый метод (напр. «Угол смачивания, вода, поверхность X»)"):
        with st.form("new_wetting_method_form"):
            nm_name = st.text_input("Название метода")
            nm_unit = st.text_input("Единица измерения", value="°")
            nm_target = st.number_input("Целевое (ожидаемое) равновесное значение, °", format="%.2f")
            nm_sd = st.number_input("Целевое SD, °", format="%.3f", min_value=0.001, value=1.0)
            if st.form_submit_button("Создать метод") and nm_name:
                new_id = add_method(nm_name, nm_unit, nm_target, nm_sd)
                st.success(f"Метод «{nm_name}» создан")
                st.rerun()

if method_id is None:
    st.stop()

st.divider()

# ==========================================================================
# 1. Загрузка файла и выбор столбцов
# ==========================================================================
st.header("1. Загрузка сырых данных")

uploaded = st.file_uploader(
    "Файл измерений (.xls, .xlsx, .csv)",
    type=["xls", "xlsx", "csv"],
    help="Файл, который сохраняет программа гониометра: время + столбцы с параллельными "
         "измерениями угла (напр. по 5-6 параллельным сериям на жидкость).",
)

if uploaded is not None:
    sheet_names = w.list_excel_sheets(uploaded)
    sheet = None
    if sheet_names:
        sheet = st.selectbox("Лист книги", sheet_names, index=0)
    uploaded.seek(0)

    try:
        raw_df = w.read_raw_file(uploaded, sheet_name=sheet if sheet is not None else 0)
    except Exception as e:
        st.error(f"Не удалось прочитать файл: {e}")
        st.stop()

    st.caption(f"Прочитано {len(raw_df)} строк, {len(raw_df.columns)} столбцов")
    with st.expander("Предпросмотр сырых данных", expanded=False):
        st.dataframe(raw_df.head(20), use_container_width=True)

    st.subheader("Разметка столбцов")
    cols = list(raw_df.columns)
    col_left, col_right = st.columns(2)
    with col_left:
        time_col = st.selectbox("Столбец времени", cols, key="time_col_select")
    with col_right:
        liquid_name = st.text_input(
            "Название жидкости / серии",
            value=st.session_state["wet_liquid_name"] or uploaded.name.rsplit(".", 1)[0],
        )

    angle_cols = st.multiselect(
        "Столбцы с параллельными измерениями угла (обычно 5-6 столбцов, °)",
        [c for c in cols if c != time_col],
        help="Выберите все столбцы одной жидкости, которые нужно усреднить в одну точку "
             "на каждый момент времени. Для разных жидкостей в одном файле обработайте "
             "их по очереди — свой набор столбцов и, если нужно, свой столбец времени.",
    )

    confidence = st.slider("Доверительная вероятность для SD (Стьюдент)", 0.80, 0.99, 0.95, 0.01)

    if st.button("Обработать выбранные столбцы", type="primary", disabled=len(angle_cols) < 2):
        try:
            avg_df = w.compute_averaged_curve(raw_df, time_col, angle_cols, confidence=confidence)
        except Exception as e:
            st.error(f"Ошибка обработки: {e}")
            avg_df = None

        if avg_df is not None and not avg_df.empty:
            st.session_state["wet_avg_df"] = avg_df
            st.session_state["wet_liquid_name"] = liquid_name
            st.session_state["wet_source_file"] = uploaded.name
            st.session_state["wet_fit_exp"] = None
            st.session_state["wet_fit_pow"] = None
            st.session_state["wet_theta_inf_override"] = None
            st.success(f"Готово: {len(avg_df)} усреднённых точек по {len(angle_cols)} параллельным измерениям")

avg_df = st.session_state["wet_avg_df"]
if avg_df is None:
    st.info("Загрузите файл и обработайте столбцы, чтобы продолжить.")
    st.stop()

st.divider()

# ==========================================================================
# 2. Усреднённая кривая
# ==========================================================================
st.header(f"2. Усреднённая кривая — {st.session_state['wet_liquid_name']}")

with st.expander("Таблица усреднённых точек (время / среднее / SD / cos θ)", expanded=False):
    st.dataframe(avg_df, use_container_width=True)
    csv_bytes = avg_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇️ Скачать таблицу (CSV)", csv_bytes, "wetting_curve_averaged.csv", "text/csv")

t = avg_df["time_s"].values
theta = avg_df["angle_mean"].values

fig_raw = go.Figure()
fig_raw.add_trace(go.Scatter(
    x=t, y=theta, mode="markers", name="Среднее по параллельным",
    error_y=dict(type="data", array=avg_df["angle_ci95"].values, visible=True),
    marker=dict(color="steelblue", size=6),
))
fig_raw.update_layout(
    title="Угол смачивания во времени", xaxis_title="Время, с",
    yaxis_title="Угол, °", height=420,
)
st.plotly_chart(fig_raw, use_container_width=True)

st.divider()

# ==========================================================================
# 3. Нелинейная аппроксимация
# ==========================================================================
st.header("3. Аппроксимация нелинейного участка")

model_choice = st.radio(
    "Модель",
    ["exponential", "power_law", "both"],
    format_func=lambda x: {"exponential": MODEL_LABELS["exponential"],
                            "power_law": MODEL_LABELS["power_law"],
                            "both": "Обе модели (сравнить)"}[x],
    horizontal=True,
)

if st.button("Подобрать аппроксимацию"):
    if model_choice in ("exponential", "both"):
        st.session_state["wet_fit_exp"] = w.fit_exponential(t, theta)
    if model_choice in ("power_law", "both"):
        st.session_state["wet_fit_pow"] = w.fit_power_law(t, theta)

fit_exp = st.session_state["wet_fit_exp"]
fit_pow = st.session_state["wet_fit_pow"]

fits_to_show = [f for f in (fit_exp, fit_pow) if f is not None]

if fits_to_show:
    fig_fit = go.Figure()
    fig_fit.add_trace(go.Scatter(
        x=t, y=theta, mode="markers", name="Данные",
        marker=dict(color="steelblue", size=6),
    ))
    t_dense = np.linspace(t.min(), t.max(), 300)

    summary_rows = []
    for fit in fits_to_show:
        label = MODEL_LABELS.get(fit.model, fit.model)
        if not fit.success:
            st.warning(f"{label}: аппроксимация не сошлась — {fit.error}")
            continue
        y_dense = fit.predict(t_dense)
        fig_fit.add_trace(go.Scatter(
            x=t_dense, y=y_dense, mode="lines", name=f"{label} (R²={fit.r_squared:.4f})",
        ))
        row = {"Модель": label, "θ∞, °": round(fit.params["theta_inf"], 3), "R²": round(fit.r_squared, 4)}
        if fit.model == "exponential":
            row["τ, с"] = round(fit.params["tau"], 3)
            row["θ0, °"] = round(fit.params["theta0"], 3)
        else:
            row["n"] = round(fit.params["n"], 4)
            row["a"] = round(fit.params["a"], 3)
        summary_rows.append(row)

    fig_fit.update_layout(
        title="Данные и аппроксимация", xaxis_title="Время, с", yaxis_title="Угол, °", height=450,
    )
    st.plotly_chart(fig_fit, use_container_width=True)

    if summary_rows:
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
        st.caption(
            "θ∞ — равновесный (предельный) угол смачивания. τ — характерное время релаксации "
            "(экспонента). n — показатель степени спада (степенной закон): чем больше n, тем "
            "быстрее кривая выходит на плато."
        )
else:
    st.info("Нажмите «Подобрать аппроксимацию», чтобы оценить θ∞ и параметры кинетики.")

st.divider()

# ==========================================================================
# 4. Линеаризация через замену переменных
# ==========================================================================
st.header("4. Линеаризация (проверка модели)")

available_models = [f for f in fits_to_show if f.success]
if not available_models:
    st.info("Сначала подберите хотя бы одну аппроксимацию в разделе 3.")
else:
    lin_model_key = st.selectbox(
        "Модель для линеаризации",
        [f.model for f in available_models],
        format_func=lambda k: MODEL_LABELS[k],
    )
    chosen_fit = next(f for f in available_models if f.model == lin_model_key)
    default_theta_inf = chosen_fit.params["theta_inf"]

    theta_inf_input = st.number_input(
        "θ∞ для линеаризации, ° (по умолчанию — из аппроксимации выше, можно скорректировать "
        "вручную, например по среднему последних точек плато)",
        value=float(default_theta_inf), format="%.3f",
    )

    if lin_model_key == "exponential":
        lin = w.linearize_exponential(t, theta, theta_inf_input)
    else:
        lin = w.linearize_power(t, theta, theta_inf_input)

    if not lin.success:
        st.warning(lin.error)
    else:
        fig_lin = go.Figure()
        fig_lin.add_trace(go.Scatter(x=lin.x, y=lin.y, mode="markers", name="Точки", marker=dict(color="steelblue")))
        x_line = np.array([lin.x.min(), lin.x.max()])
        y_line = lin.slope * x_line + lin.intercept
        fig_lin.add_trace(go.Scatter(x=x_line, y=y_line, mode="lines", name=f"Линейная регрессия (R²={lin.r_squared:.4f})", line=dict(color="firebrick")))
        fig_lin.update_layout(
            title="Спрямлённая кривая", xaxis_title=lin.x_label, yaxis_title=lin.y_label, height=420,
        )
        st.plotly_chart(fig_lin, use_container_width=True)

        c1, c2, c3 = st.columns(3)
        c1.metric("Наклон", f"{lin.slope:.5f}")
        c1.metric("R²", f"{lin.r_squared:.4f}")
        if lin_model_key == "exponential":
            c2.metric("τ (из наклона), с", f"{lin.derived['tau']:.3f}")
        else:
            c2.metric("n (из наклона)", f"{lin.derived['n']:.4f}")
            c3.metric("a (из пересечения)", f"{lin.derived['a']:.3f}")

        st.caption(
            "Если точки на этом графике ложатся близко к прямой (R² близко к 1) — выбранная "
            "модель и заданное θ∞ хорошо описывают кинетику. Систематическое отклонение от "
            "прямой (дуга, излом) означает, что модель или θ∞ подобраны неточно — попробуйте "
            "скорректировать θ∞ или сравните со второй моделью."
        )

st.divider()

# ==========================================================================
# 5. Сохранение результатов
# ==========================================================================
st.header("5. Сохранить результаты")

save_col1, save_col2 = st.columns(2)

with save_col1:
    st.subheader("На карту Шухарта")
    st.caption("Равновесное значение θ∞ как обычная контрольная точка метода.")
    savable_fits = {MODEL_LABELS[f.model]: f for f in available_models} if available_models else {}
    if not savable_fits:
        st.caption("Нет подобранной модели для сохранения.")
    else:
        chosen_label = st.selectbox("Взять θ∞ из модели", list(savable_fits.keys()))
        operator = st.text_input("Оператор (ФИО) — для аудит-трейла")
        comment = st.text_input(
            "Комментарий",
            value=f"{st.session_state['wet_liquid_name']}, модель: {chosen_label}",
        )
        if st.button("Сохранить точку θ∞ на карту Шухарта"):
            if not operator:
                st.error("Укажите оператора")
            else:
                fit = savable_fits[chosen_label]
                theta_inf_value = float(fit.params["theta_inf"])
                result_id = add_result(method_id, theta_inf_value, operator, comment)

                param2_name = "tau" if fit.model == "exponential" else "n"
                param2_value = fit.params.get(param2_name)
                add_wetting_curve(
                    method_id=method_id,
                    liquid_name=st.session_state["wet_liquid_name"],
                    source_file=st.session_state["wet_source_file"],
                    fit_model=fit.model,
                    theta_inf=theta_inf_value,
                    fit_param2_name=param2_name,
                    fit_param2_value=float(param2_value) if param2_value is not None else None,
                    r_squared=float(fit.r_squared),
                    result_id=result_id,
                )
                st.success(f"θ∞ = {theta_inf_value:.3f}° сохранён как точка контроля и в архив кривых")

with save_col2:
    st.subheader("В архив кривых (без карты Шухарта)")
    st.caption("Сохранить обработанную кривую и параметры для истории, не трогая карту Шухарта.")
    if st.button("Сохранить кривую в архив"):
        fit_model = None
        theta_inf_value = None
        param2_name = None
        param2_value = None
        r2 = None
        if available_models:
            f = available_models[0]
            fit_model = f.model
            theta_inf_value = float(f.params["theta_inf"])
            param2_name = "tau" if f.model == "exponential" else "n"
            param2_value = float(f.params.get(param2_name))
            r2 = float(f.r_squared)

        curve_id = add_wetting_curve(
            method_id=method_id,
            liquid_name=st.session_state["wet_liquid_name"],
            source_file=st.session_state["wet_source_file"],
            fit_model=fit_model,
            theta_inf=theta_inf_value,
            fit_param2_name=param2_name,
            fit_param2_value=param2_value,
            r_squared=r2,
        )
        add_wetting_points(curve_id, avg_df)
        st.success("Кривая сохранена в архив")

st.divider()

# ==========================================================================
# 6. Архив ранее сохранённых кривых
# ==========================================================================
st.header("6. Архив кривых по выбранному методу")

curves_df = get_wetting_curves(method_id)
if curves_df.empty:
    st.caption("Пока ничего не сохранено для этого метода.")
else:
    st.dataframe(
        curves_df[["id", "liquid_name", "source_file", "fit_model", "theta_inf",
                   "fit_param2_name", "fit_param2_value", "r_squared", "created_at"]],
        use_container_width=True, hide_index=True,
    )
    with st.expander("Посмотреть / удалить сохранённую кривую"):
        curve_id_to_view = st.selectbox(
            "Кривая", curves_df["id"],
            format_func=lambda cid: f"#{cid} — {curves_df.set_index('id').loc[cid, 'liquid_name']}",
        )
        points = get_wetting_points(int(curve_id_to_view))
        if not points.empty:
            fig_arch = go.Figure()
            fig_arch.add_trace(go.Scatter(x=points["time_s"], y=points["angle_mean"], mode="markers+lines"))
            fig_arch.update_layout(xaxis_title="Время, с", yaxis_title="Угол, °", height=350)
            st.plotly_chart(fig_arch, use_container_width=True)
        if st.button("🗑️ Удалить эту кривую из архива"):
            delete_wetting_curve(int(curve_id_to_view))
            st.success("Удалено")
            st.rerun()
