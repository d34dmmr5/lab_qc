# lab_qc — контроль качества лаборатории

Приложение на Streamlit + SQLite: карта Шухарта с проверкой правил
Westgard и модуль обработки кривых угла смачивания (усреднение,
нелинейная аппроксимация, линеаризация).

## Архитектура

```
app.py                 — точка входа: st.set_page_config + st.navigation
config.py              — все константы и настраиваемые параметры
models.py               — dataclasses: ControlMethod, ControlResult,
                           WettingCurveRecord, AveragedCurve, FitResult, ...
database.py             — DAO: транзакции, валидация, типизированные модели
charts.py                — переиспользуемые Plotly-графики (без бизнес-логики)
utils.py                 — общие UI-хелперы (session_state, CSV-экспорт, ...)
schema.sql                — схема БД
requirements.txt

services/
  qc_service.py           — правила Westgard
  wetting_service.py       — парсинг файлов, усреднение, аппроксимация,
                              линеаризация (без единой строчки Streamlit)

pages/
  home.py                  — карта Шухарта (UI поверх database.py + charts.py)
  wetting.py                — угол смачивания (UI поверх services/wetting_service.py)
```

**Принцип разделения:** страницы (`pages/`) отвечают только за UI и
вызовы сервисов/DAO. Вся математика — в `services/`, весь SQL — в
`database.py`, все графики — в `charts.py`. Ни один модуль вне
`pages/` и `app.py` не импортирует `streamlit`, кроме `database.py`
(нужен `@st.cache_resource` для соединения) и `utils.py` (UI-хелперы).
Это позволяет тестировать `services/` и `database.py` обычными
Python-скриптами, без поднятия Streamlit.

## Установка и запуск

```
python -m venv venv
venv\Scripts\activate      # Windows
# или: source venv/bin/activate   # Linux
pip install -r requirements.txt
streamlit run app.py
```

При первом запуске `lab_qc.db` создаётся автоматически по `schema.sql`.
При обновлении с более старой версии приложения `database.py` сам
докатывает недостающие колонки через миграцию — существующие данные
не теряются.

## Как добавить новую модель аппроксимации

1. Добавить функцию `fit_<model>()` в `services/wetting_service.py`,
   возвращающую `models.FitResult`.
2. Добавить константы (границы параметров и т.п.), если нужны, в `config.py`.
3. Добавить пункт в `MODEL_LABELS` на странице `pages/wetting.py`
   и включить модель в список `st.multiselect(...)`.

## Как добавить новое правило Westgard

Добавить константы порога/окна в `config.py` (`WESTGARD_*`) и
соответствующий блок проверки в `services/qc_service.py::check_westgard_violations`.
`charts.py` ничего менять не нужно — он просто раскрашивает точки по
результату этой функции.
