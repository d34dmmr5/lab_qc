"""
Угол смачивания: загрузка .xls/.xlsx/.csv, усреднение параллельных
измерений, нелинейная аппроксимация и линеаризация через замену
переменных. Равновесное значение θ∞ можно сохранить на карту Шухарта.

Файл — только UI: вся математика в services/wetting_service.py,
весь доступ к БД — в database.py, построение графиков — в charts.py.
"""

import json

import pandas as pd
import streamlit as st

import config
import database as db
from charts import (
    build_archived_curve_chart,
    build_linearization_chart,
    build_wetting_fit_chart,
    build_wetting_raw_chart,
)
from database import ValidationError
from models import FitResult
from services import wetting_service as ws
from services.wetting_service import WettingDataError
from utils import download_csv_button, init_session_state, persistent_text_input, remember_text_input, show_validation_error

st.title("💧 Угол смачивания: обработка кривых")

MODEL_LABELS = {
    "exponential": "Экспоненциальная релаксация",
    "power_law": "Степенной закон",
    "polynomial": "Полином",
}

init_session_state({
    "wet_curve": None,           # models.AveragedCurve
    "wet_fit_exp": None,
    "wet_fit_pow": None,
    "wet_fit_poly": None,
})


def _param2_for(fit: FitResult) -> tuple[str | None, float | None]:
    """Второй ключевой параметр модели для компактного хранения в БД."""
    if fit.model == "exponential":
        return "tau", fit.params.get("tau")
    if fit.model == "power_law":
        return "n", fit.params.get("n")
    if fit.model == "polynomial":
        return "degree", float(fit.params.get("degree"))
    return None, None


# ==========================================================================
# Метод контроля
# ==========================================================================
with st.sidebar:
    st.header("Метод контроля")
    methods = db.list_methods()

    if not methods:
        st.info("Методов пока нет — создайте метод для угла смачивания.")
        selected_method = None
    else:
        method_name = st.selectbox("Метод (карта Шухарта)", [m.name for m in methods])
        selected_method = next(m for m in methods if m.name == method_name)
        st.caption(f"Целевое: {selected_method.target_value} {selected_method.unit}, SD: {selected_method.target_sd}")

    with st.expander("➕ Новый метод (напр. «Угол смачивания, вода, поверхность X»)"):
        with st.form("new_wetting_method_form"):
            nm_name = st.text_input("Название метода")
            nm_unit = st.text_input("Единица измерения", value=config.DEFAULT_WETTING_UNIT)
            nm_target = st.number_input("Целевое (ожидаемое) равновесное значение, °", format="%.2f")
            nm_sd = st.number_input("Целевое SD, °", format="%.3f", min_value=config.MIN_METHOD_SD, value=1.0)
            if st.form_submit_button("Создать метод"):
                try:
                    db.add_method(nm_name, nm_unit, nm_target, nm_sd)
                    st.success(f"Метод «{nm_name}» создан")
                    st.rerun()
                except ValidationError as e:
                    show_validation_error(e)

if selected_method is None:
    st.stop()

method_id = selected_method.id
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
    sheet_names = ws.list_excel_sheets(uploaded)
    sheet = st.selectbox("Лист книги", sheet_names, index=0) if sheet_names else None
    uploaded.seek(0)

    try:
        raw_df = ws.read_raw_file(uploaded, sheet_name=sheet if sheet is not None else 0)
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
        default_liquid = st.session_state["wet_curve"].liquid_name if st.session_state["wet_curve"] else \
            uploaded.name.rsplit(".", 1)[0]
        liquid_name = st.text_input("Название жидкости / серии", value=default_liquid)

    angle_cols = st.multiselect(
        "Столбцы с параллельными измерениями угла (обычно 5-6 столбцов, °)",
        [c for c in cols if c != time_col],
        help="Выберите все столбцы одной жидкости, которые нужно усреднить в одну точку "
             "на каждый момент времени. Для разных жидкостей в одном файле обработайте "
             "их по очереди — свой набор столбцов и, если нужно, свой столбец времени.",
    )

    confidence = st.slider(
        "Доверительная вероятность для SD (Стьюдент)",
        config.CONFIDENCE_SLIDER_MIN, config.CONFIDENCE_SLIDER_MAX,
        config.DEFAULT_CONFIDENCE, config.CONFIDENCE_SLIDER_STEP,
    )

    if st.button("Обработать выбранные столбцы", type="primary",
                  disabled=len(angle_cols) < config.MIN_PARALLEL_MEASUREMENTS):
        try:
            curve = ws.compute_averaged_curve(
                raw_df, time_col, angle_cols, liquid_name, uploaded.name, confidence=confidence,
            )
            st.session_state["wet_curve"] = curve
            st.session_state["wet_fit_exp"] = None
            st.session_state["wet_fit_pow"] = None
            st.session_state["wet_fit_poly"] = None
            st.success(f"Готово: {len(curve)} усреднённых точек по {len(angle_cols)} параллельным измерениям")
        except WettingDataError as e:
            show_validation_error(e)

curve = st.session_state["wet_curve"]
if curve is None:
    st.info("Загрузите файл и обработайте столбцы, чтобы продолжить.")
    st.stop()

st.divider()

# ==========================================================================
# 2. Усреднённая кривая
# ==========================================================================
st.header(f"2. Усреднённая кривая — {curve.liquid_name}")

with st.expander("Таблица усреднённых точек (время / среднее / SD / cos θ)", expanded=False):
    st.dataframe(curve.points, use_container_width=True)
    download_csv_button(curve.points, "wetting_curve_averaged.csv")

t, theta = curve.t, curve.theta
st.plotly_chart(
    build_wetting_raw_chart(t, theta, curve.points["angle_ci95"].to_numpy()),
    use_container_width=True,
)

st.divider()

# ==========================================================================
# 3. Нелинейная аппроксимация
# ==========================================================================
st.header("3. Аппроксимация нелинейного участка")

model_choice = st.multiselect(
    "Модели (можно выбрать несколько — для сравнения)",
    ["exponential", "power_law", "polynomial"],
    default=["exponential"],
    format_func=lambda k: MODEL_LABELS[k],
)

poly_degree = None
if "polynomial" in model_choice:
    poly_degree = st.slider(
        "Степень полинома", config.POLYNOMIAL_DEGREE_MIN, config.POLYNOMIAL_DEGREE_MAX,
        config.POLYNOMIAL_DEGREE_DEFAULT, 1,
        help="Чисто описательная модель: коэффициенты — методом наименьших квадратов "
             "напрямую, без логарифмирования. Не даёт физического θ∞.",
    )

if st.button("Подобрать аппроксимацию", disabled=len(model_choice) == 0):
    if "exponential" in model_choice:
        st.session_state["wet_fit_exp"] = ws.fit_exponential(t, theta)
    if "power_law" in model_choice:
        st.session_state["wet_fit_pow"] = ws.fit_power_law(t, theta)
    if "polynomial" in model_choice:
        st.session_state["wet_fit_poly"] = ws.fit_polynomial(t, theta, poly_degree)

fit_exp = st.session_state["wet_fit_exp"]
fit_pow = st.session_state["wet_fit_pow"]
fit_poly = st.session_state["wet_fit_poly"]
fits_to_show = [f for f in (fit_exp, fit_pow, fit_poly) if f is not None]

if fits_to_show:
    st.plotly_chart(build_wetting_fit_chart(t, theta, fits_to_show, MODEL_LABELS), use_container_width=True)

    summary_rows = []
    for fit in fits_to_show:
        label = MODEL_LABELS.get(fit.model, fit.model)
        if not fit.success:
            st.warning(f"{label}: аппроксимация не сошлась — {fit.error}")
            continue
        if fit.model == "polynomial":
            row = {
                "Модель": f"{label} (степень {fit.params['degree']})",
                "θ на посл. точке, °": round(fit.theta_inf, 3),
                "R²": round(fit.r_squared, 4),
                "Коэффициенты": ", ".join(
                    f"c{p}={fit.params[f'c{p}']:.5g}" for p in range(fit.params["degree"], -1, -1)
                ),
            }
        else:
            row = {"Модель": label, "θ∞, °": round(fit.theta_inf, 3), "R²": round(fit.r_squared, 4)}
            if fit.model == "exponential":
                row["τ, с"] = round(fit.params["tau"], 3)
                row["θ0, °"] = round(fit.params["theta0"], 3)
            else:
                row["n"] = round(fit.params["n"], 4)
                row["a"] = round(fit.params["a"], 3)
        summary_rows.append(row)

    if summary_rows:
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
        st.caption(
            "θ∞ — равновесный (предельный) угол смачивания. τ — характерное время релаксации "
            "(экспонента). n — показатель степени спада (степенной закон). Для полинома "
            "«θ на посл. точке» — значение модели в последней измеренной точке, а не "
            "физический параметр равновесия: полином — описательная кривая, не кинетическая модель."
        )
else:
    st.info("Нажмите «Подобрать аппроксимацию», чтобы оценить θ∞ и параметры кинетики.")

st.divider()

# ==========================================================================
# 4. Линеаризация через замену переменных
# ==========================================================================
st.header("4. Линеаризация (проверка модели)")

available_models = [f for f in fits_to_show if f.success]
linearizable_models = [f for f in available_models if f.model in ("exponential", "power_law")]

if fit_poly is not None and fit_poly.success and not linearizable_models:
    st.info(
        "Полином уже линеен по коэффициентам (см. раздел 3) — отдельная логарифмическая "
        "линеаризация ему не нужна. Этот раздел применим к экспоненциальной релаксации и "
        "степенному закону."
    )

if not linearizable_models:
    if not (fit_poly is not None and fit_poly.success):
        st.info("Сначала подберите хотя бы одну аппроксимацию в разделе 3.")
else:
    lin_model_key = st.selectbox(
        "Модель для линеаризации",
        [f.model for f in linearizable_models],
        format_func=lambda k: MODEL_LABELS[k],
    )
    chosen_fit = next(f for f in linearizable_models if f.model == lin_model_key)

    theta_inf_input = st.number_input(
        "θ∞ для линеаризации, ° (по умолчанию — из аппроксимации выше, можно скорректировать "
        "вручную, например по среднему последних точек плато)",
        value=float(chosen_fit.theta_inf), format="%.3f",
    )

    lin = (ws.linearize_exponential if lin_model_key == "exponential" else ws.linearize_power)(
        t, theta, theta_inf_input
    )

    if not lin.success:
        st.warning(lin.error)
    else:
        st.plotly_chart(build_linearization_chart(lin), use_container_width=True)

        c1, c2, c3 = st.columns(3)
        c1.metric("Наклон", f"{lin.slope:.5f}")
        c1.metric("R²", f"{lin.r_squared:.4f}")
        if lin_model_key == "exponential":
            c2.metric("τ (из наклона), с", f"{lin.derived['tau']:.3f}")
        else:
            c2.metric("n (из наклона)", f"{lin.derived['n']:.4f}")
            c3.metric("a (из пересечения)", f"{lin.derived['a']:.3f}")

        st.caption(
            "Если точки ложатся близко к прямой (R² близко к 1) — модель и заданное θ∞ хорошо "
            "описывают кинетику. Систематическое отклонение (дуга, излом) означает, что модель "
            "или θ∞ подобраны неточно — скорректируйте θ∞ или сравните со второй моделью."
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
    savable_fits = {MODEL_LABELS[f.model]: f for f in available_models}
    if not savable_fits:
        st.caption("Нет подобранной модели для сохранения.")
    else:
        chosen_label = st.selectbox("Взять θ∞ из модели", list(savable_fits.keys()))
        chosen_preview = savable_fits[chosen_label]
        if chosen_preview.model == "polynomial":
            st.warning(
                "Для полинома это значение в последней точке, а не физический равновесный "
                "угол — обычно лучше использовать θ∞ из экспоненты или степенного закона."
            )
        operator = persistent_text_input("Оператор (ФИО) — для аудит-трейла", "last_operator_wetting")
        comment = st.text_input("Комментарий", value=f"{curve.liquid_name}, модель: {chosen_label}")

        if st.button("Сохранить точку θ∞ на карту Шухарта"):
            fit = savable_fits[chosen_label]
            try:
                theta_inf_value = float(fit.theta_inf)
                result_id = db.add_result(method_id, theta_inf_value, operator, comment)
                remember_text_input("last_operator_wetting", operator)
                param2_name, param2_value = _param2_for(fit)
                db.save_wetting_curve(
                    method_id=method_id, liquid_name=curve.liquid_name, source_file=curve.source_file,
                    points=curve.points, fit_model=fit.model, theta_inf=theta_inf_value,
                    fit_param2_name=param2_name,
                    fit_param2_value=float(param2_value) if param2_value is not None else None,
                    r_squared=float(fit.r_squared), result_id=result_id,
                    fit_coeffs_json=json.dumps(fit.params),
                )
                st.success(f"θ∞ = {theta_inf_value:.3f}° сохранён как точка контроля и в архив кривых")
            except ValidationError as e:
                show_validation_error(e)

with save_col2:
    st.subheader("В архив кривых (без карты Шухарта)")
    st.caption("Сохранить обработанную кривую и параметры для истории, не трогая карту Шухарта.")
    archive_fits = {MODEL_LABELS[f.model]: f for f in available_models}
    archive_label = st.selectbox(
        "Какую модель приложить к архивной записи", list(archive_fits.keys()), key="archive_model_select",
    ) if archive_fits else None

    if st.button("Сохранить кривую в архив"):
        fit_model = theta_inf_value = param2_name = param2_value = r2 = coeffs_json = None
        if archive_label:
            f = archive_fits[archive_label]
            fit_model, theta_inf_value, r2 = f.model, float(f.theta_inf), float(f.r_squared)
            param2_name, param2_value = _param2_for(f)
            coeffs_json = json.dumps(f.params)
        try:
            db.save_wetting_curve(
                method_id=method_id, liquid_name=curve.liquid_name, source_file=curve.source_file,
                points=curve.points, fit_model=fit_model, theta_inf=theta_inf_value,
                fit_param2_name=param2_name, fit_param2_value=param2_value, r_squared=r2,
                fit_coeffs_json=coeffs_json,
            )
            st.success("Кривая сохранена в архив")
        except ValidationError as e:
            show_validation_error(e)

st.divider()

# ==========================================================================
# 6. Архив ранее сохранённых кривых
# ==========================================================================
st.header("6. Архив кривых по выбранному методу")

curves = db.list_wetting_curves(method_id)
if not curves:
    st.caption("Пока ничего не сохранено для этого метода.")
else:
    curves_df = pd.DataFrame([{
        "id": c.id, "liquid_name": c.liquid_name, "source_file": c.source_file,
        "fit_model": c.fit_model, "theta_inf": c.theta_inf,
        "fit_param2_name": c.fit_param2_name, "fit_param2_value": c.fit_param2_value,
        "r_squared": c.r_squared, "created_at": c.created_at,
    } for c in curves])
    st.dataframe(curves_df, use_container_width=True, hide_index=True)

    with st.expander("Посмотреть / удалить сохранённую кривую"):
        curve_by_id = {c.id: c for c in curves}
        curve_id_to_view = st.selectbox(
            "Кривая", list(curve_by_id.keys()),
            format_func=lambda cid: f"#{cid} — {curve_by_id[cid].liquid_name}",
        )
        points = db.get_wetting_points(int(curve_id_to_view))
        if not points.empty:
            st.plotly_chart(build_archived_curve_chart(points), use_container_width=True)

        raw_coeffs = curve_by_id[curve_id_to_view].fit_coeffs_json
        if raw_coeffs:
            st.caption("Полный набор параметров сохранённой модели:")
            st.json(json.loads(raw_coeffs))

        if st.button("🗑️ Удалить эту кривую из архива"):
            db.delete_wetting_curve(int(curve_id_to_view))
            st.success("Удалено")
            st.rerun()
