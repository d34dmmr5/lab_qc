"""
Точка входа Streamlit-приложения контроля качества для аналитической
лаборатории. Запуск: streamlit run app.py

Сам файл не содержит бизнес-логики — только конфигурацию страницы и
навигацию между pages/home.py (карта Шухарта) и pages/wetting.py
(угол смачивания). Логика — в database.py и services/.
"""

import streamlit as st

import config

st.set_page_config(page_title=config.PAGE_TITLE, layout=config.PAGE_LAYOUT)

home_page = st.Page("pages/home.py", title="Карта Шухарта", icon="📊", default=True)
wetting_page = st.Page("pages/wetting.py", title="Угол смачивания", icon="💧")

navigation = st.navigation([home_page, wetting_page])
navigation.run()
