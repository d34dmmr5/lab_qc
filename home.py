"""
Карта Шухарта: выбор/создание метода контроля, добавление результатов,
визуализация с подсветкой нарушений Westgard.
"""

import streamlit as st

import config
import database as db
from charts import build_shewhart_chart
from database import ValidationError
from services.qc_service import check_westgard_violations
from utils import persistent_text_input, remember_text_input, show_validation_error

st.title("📊 Контроль качества измерений")

# --- Боковая панель: выбор или создание метода ---
with st.sidebar:
    st.header("Метод / показатель")
    methods = db.list_methods()

    if not methods:
        st.info("Пока нет ни одного метода. Добавьте первый.")
        selected_method = None
    else:
        method_names = [m.name for m in methods]
        method_name = st.selectbox("Выберите метод", method_names)
        selected_method = next(m for m in methods if m.name == method_name)

    with st.expander("➕ Добавить новый метод"):
        with st.form("new_method_form"):
            new_name = st.text_input("Название метода")
            new_unit = st.text_input("Единица измерения", value=config.DEFAULT_METHOD_UNIT)
            new_target = st.number_input("Целевое значение", format="%.4f")
            new_sd = st.number_input(
                "Стандартное отклонение (SD)", format="%.4f", min_value=config.MIN_METHOD_SD,
            )
            submitted = st.form_submit_button("Сохранить метод")
            if submitted:
                try:
                    db.add_method(new_name, new_unit, new_target, new_sd)
                    st.success(f"Метод «{new_name}» добавлен")
                    st.rerun()
                except ValidationError as e:
                    show_validation_error(e)

# --- Основная область: если метод выбран ---
if selected_method is not None:
    target = selected_method.target_value
    sd = selected_method.target_sd
    unit = selected_method.unit

    col_form, col_chart = st.columns([1, 3])

    with col_form:
        st.subheader("Новый результат")
        with st.form("new_result_form", clear_on_submit=True):
            value = st.number_input(f"Значение, {unit}", format="%.4f")
            operator = persistent_text_input("Оператор (ФИО)", "last_operator")
            comment = st.text_area("Комментарий", height=68)
            add_clicked = st.form_submit_button("Добавить точку")
            if add_clicked:
                try:
                    db.add_result(selected_method.id, value, operator, comment)
                    remember_text_input("last_operator", operator)
                    st.success("Результат сохранён")
                    st.rerun()
                except ValidationError as e:
                    show_validation_error(e)

        st.divider()
        st.caption(f"Целевое значение: **{target} {unit}**")
        st.caption(f"SD: **{sd} {unit}**")

    with col_chart:
        results = db.list_results(selected_method.id)
        if not results:
            st.warning("Нет результатов по этому методу — добавьте первую точку слева.")
        else:
            results_df = db.results_to_dataframe(results)
            fig = build_shewhart_chart(results_df, target, sd, unit)
            st.plotly_chart(fig, use_container_width=True)

            violations = check_westgard_violations(results_df["measured_value"], target, sd)
            if violations.any():
                st.error(
                    f"⚠️ Обнаружено нарушение правил Westgard в {violations.sum()} точках "
                    "— проверьте процесс измерения."
                )
            else:
                st.success("✅ Нарушений правил Westgard не обнаружено")

            with st.expander("Таблица результатов"):
                st.dataframe(
                    results_df[["measured_at", "measured_value", "operator", "comment"]],
                    use_container_width=True,
                )
else:
    st.info("Добавьте метод в боковой панели, чтобы начать работу.")
