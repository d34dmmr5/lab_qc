"""
Единая точка конфигурации: все "магические числа" и настраиваемые
параметры приложения собраны здесь, чтобы не дублироваться по модулям
и не расходиться друг с другом при изменении.
"""

import os
from pathlib import Path

# --- Пути и подключение к БД ---
APP_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get("LAB_QC_DB_PATH", str(APP_DIR / "lab_qc.db"))
SCHEMA_PATH = APP_DIR / "schema.sql"

# --- Общие параметры Streamlit-страниц ---
PAGE_TITLE = "Контроль качества лаборатории"
PAGE_LAYOUT = "wide"

# --- Карта Шухарта / результаты контроля ---
MAX_RESULTS_PER_METHOD = 200        # сколько последних точек подтягивать из БД для графика
SHEWHART_SIGMA_ZONES = (1, 2, 3)    # какие зоны ±kSD рисовать на карте
SHEWHART_ZONE_OPACITY = {1: 0.14, 2: 0.10, 3: 0.06}
SHEWHART_ZONE_COLOR = "green"
SHEWHART_LINE_COLOR = "gray"
SHEWHART_TARGET_LINE_COLOR = "black"
SHEWHART_POINT_COLOR = "steelblue"
SHEWHART_VIOLATION_COLOR = "red"

# --- Правила Westgard: окно (число подряд идущих точек) -> порог в единицах SD ---
WESTGARD_1_3S_THRESHOLD = 3.0
WESTGARD_2_2S_WINDOW = 2
WESTGARD_2_2S_THRESHOLD = 2.0
WESTGARD_4_1S_WINDOW = 4
WESTGARD_4_1S_THRESHOLD = 1.0
WESTGARD_10X_WINDOW = 10

# --- Угол смачивания: усреднение параллельных измерений ---
MIN_PARALLEL_MEASUREMENTS = 2       # минимум столбцов, чтобы вообще считать SD
DEFAULT_CONFIDENCE = 0.95           # доверительная вероятность для интервала по Стьюденту
CONFIDENCE_SLIDER_MIN = 0.80
CONFIDENCE_SLIDER_MAX = 0.99
CONFIDENCE_SLIDER_STEP = 0.01

# --- Угол смачивания: нелинейная аппроксимация ---
FIT_DENSE_POINTS = 300              # сколько точек для гладкой линии аппроксимации на графике
CURVE_FIT_MAXFEV = 20000            # макс. число итераций scipy.optimize.curve_fit
POLYNOMIAL_DEGREE_MIN = 2
POLYNOMIAL_DEGREE_MAX = 5
POLYNOMIAL_DEGREE_DEFAULT = 3
POWER_LAW_N_MIN = 1e-4              # границы для показателя степени в power-law fit
POWER_LAW_N_MAX = 10.0

# --- Валидация ввода ---
MIN_METHOD_SD = 1e-4                # SD метода должно быть строго положительным
REQUIRE_OPERATOR_FOR_RESULTS = True # обязателен ли оператор в аудит-трейле

# --- Единицы измерения по умолчанию для новых методов ---
DEFAULT_METHOD_UNIT = "мг/л"
DEFAULT_WETTING_UNIT = "°"
