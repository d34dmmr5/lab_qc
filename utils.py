"""Общие UI-хелперы, переиспользуемые между страницами Streamlit."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st


def init_session_state(defaults: dict[str, Any]) -> None:
    """Заполняет st.session_state значениями по умолчанию, если их там ещё нет."""
    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default


def require_operator_input(label: str = "Оператор (ФИО) — для аудит-трейла") -> str:
    """Текстовое поле оператора + единообразное сообщение об ошибке, если пусто."""
    return st.text_input(label)


def persistent_text_input(label: str, state_key: str, help: str | None = None) -> str:
    """
    Текстовое поле, которое подставляет последнее введённое значение по
    умолчанию — удобно для полей вроде ФИО оператора, которые в течение
    смены/сессии обычно не меняются. Значение "запоминается" в рамках
    текущей сессии браузера (st.session_state), пока не введут новое —
    и не переживает перезапуск сервера/новую сессию.
    """
    default = st.session_state.get(state_key, "")
    return st.text_input(label, value=default, help=help)


def remember_text_input(state_key: str, value: str) -> None:
    """Сохраняет значение поля как значение по умолчанию для следующего ввода."""
    if value:
        st.session_state[state_key] = value


def show_validation_error(exc: Exception) -> None:
    """Единообразный вывод ошибок валидации/бизнес-логики через st.error."""
    st.error(str(exc))


def download_csv_button(df: pd.DataFrame, filename: str, label: str = "⬇️ Скачать таблицу (CSV)") -> None:
    """Кнопка скачивания DataFrame как CSV с BOM (корректно открывается в Excel с кириллицей)."""
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(label, csv_bytes, filename, "text/csv")


def format_metric(value: float | None, unit: str = "", digits: int = 3) -> str:
    """Единообразное форматирование числового значения с единицей измерения."""
    if value is None:
        return "—"
    return f"{value:.{digits}f}{(' ' + unit) if unit else ''}"
