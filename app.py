"""
Главная страница приложения контроля качества для аналитической лаборатории.
Запуск: streamlit run app.py
"""

import streamlit as st
from datetime import datetime

from db import get_methods, add_method, get_results, add_result
from charts import build_shewhart_chart, check_westgard_violations

st.set_page_config(page_title="Контроль качества лаборатории", layout="wide")
st.title("📊 Контроль качества измерений")

# --- Боковая панель: выбор или создание метода ---
with st.sidebar:
    st.header("Метод / показатель")
    methods_df = get_methods()

    if methods_df.empty:
        st.info("Пока нет ни одного метода. Добавьте первый.")
        method_id = None
    else:
        method_name = st.selectbox("Выберите метод", methods_df["name"])
        method_row = methods_df[methods_df["name"] == method_name].iloc[0]
        method_id = int(method_row["id"])

    with st.expander("➕ Добавить новый метод"):
        with st.form("new_method_form"):
            new_name = st.text_input("Название метода")
            new_unit = st.text_input("Единица измерения", value="мг/л")
            new_target = st.number_input("Целевое значение", format="%.4f")
            new_sd = st.number_input("Стандартное отклонение (SD)", format="%.4f", min_value=0.0001)
            submitted = st.form_submit_button("Сохранить метод")
            if submitted and new_name:
                add_method(new_name, new_unit, new_target, new_sd)
                st.success(f"Метод «{new_name}» добавлен")
                st.rerun()

# --- Основная область: если метод выбран ---
if method_id is not None:
    target = float(method_row["target_value"])
    sd = float(method_row["target_sd"])
    unit = method_row["unit"]

    col_form, col_chart = st.columns([1, 3])

    with col_form:
        st.subheader("Новый результат")
        with st.form("new_result_form", clear_on_submit=True):
            value = st.number_input(f"Значение, {unit}", format="%.4f")
            operator = st.text_input("Оператор (ФИО)")
            comment = st.text_area("Комментарий", height=68)
            add_clicked = st.form_submit_button("Добавить точку")
            if add_clicked:
                if not operator:
                    st.error("Укажите оператора — это нужно для аудит-трейла")
                else:
                    add_result(method_id, value, operator, comment)
                    st.success("Результат сохранён")
                    st.rerun()

        st.divider()
        st.caption(f"Целевое значение: **{target} {unit}**")
        st.caption(f"SD: **{sd} {unit}**")

    with col_chart:
        results_df = get_results(method_id)
        if results_df.empty:
            st.warning("Нет результатов по этому методу — добавьте первую точку слева.")
        else:
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
