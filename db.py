"""
Слой доступа к данным: подключение к SQLite и базовые запросы.
База данных — это один файл (по умолчанию lab_qc.db рядом с приложением).
Никакого отдельного сервера БД устанавливать не нужно.
"""

import os
import sqlite3
import pandas as pd
import streamlit as st

DB_PATH = os.environ.get("LAB_QC_DB_PATH", "lab_qc.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


@st.cache_resource
def get_connection() -> sqlite3.Connection:
    """
    Создаёт (или открывает существующее) подключение к файлу базы данных.
    check_same_thread=False нужен, потому что Streamlit может обращаться
    к соединению из разных потоков.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """При первом запуске создаёт таблицы, если их ещё нет."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()


# --- Методы контроля ---

def get_methods() -> pd.DataFrame:
    """Список всех методов/показателей контроля."""
    conn = get_connection()
    return pd.read_sql(
        "SELECT id, name, unit, target_value, target_sd FROM control_methods ORDER BY name",
        conn,
    )


def add_method(name: str, unit: str, target_value: float, target_sd: float) -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO control_methods (name, unit, target_value, target_sd)
           VALUES (?, ?, ?, ?)""",
        (name, unit, target_value, target_sd),
    )
    conn.commit()
    return cur.lastrowid


# --- Результаты контроля (точки карты Шухарта) ---

def get_results(method_id: int, limit: int = 200) -> pd.DataFrame:
    """Последние N результатов контроля по методу, отсортированные по дате."""
    conn = get_connection()
    df = pd.read_sql(
        """SELECT id, measured_value, measured_at, operator, comment
           FROM control_results
           WHERE method_id = ?
           ORDER BY measured_at DESC
           LIMIT ?""",
        conn,
        params=(method_id, limit),
    )
    df["measured_at"] = pd.to_datetime(df["measured_at"])
    return df.sort_values("measured_at")


def add_result(method_id: int, value: float, operator: str, comment: str = "") -> int:
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO control_results (method_id, measured_value, operator, comment)
           VALUES (?, ?, ?, ?)""",
        (method_id, value, operator, comment),
    )
    conn.commit()
    return cur.lastrowid


# --- Кривые угла смачивания ---

def add_wetting_curve(
    method_id: int,
    liquid_name: str,
    source_file: str,
    fit_model: str | None,
    theta_inf: float | None,
    fit_param2_name: str | None,
    fit_param2_value: float | None,
    r_squared: float | None,
    result_id: int | None = None,
) -> int:
    """Сохраняет метаданные обработанной кривой (без точек — см. add_wetting_points)."""
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO wetting_curves
           (method_id, liquid_name, source_file, fit_model, theta_inf,
            fit_param2_name, fit_param2_value, r_squared, result_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            method_id, liquid_name, source_file, fit_model, theta_inf,
            fit_param2_name, fit_param2_value, r_squared, result_id,
        ),
    )
    conn.commit()
    return cur.lastrowid


def add_wetting_points(curve_id: int, points_df: pd.DataFrame) -> None:
    """
    Сохраняет точки усреднённой кривой (время, среднее, SD, cos).
    points_df должен содержать колонки: time_s, angle_mean, angle_sd,
    angle_ci95, cos_theta.
    """
    conn = get_connection()
    rows = [
        (
            curve_id,
            float(r.time_s),
            float(r.angle_mean),
            None if pd.isna(r.angle_sd) else float(r.angle_sd),
            None if pd.isna(r.angle_ci95) else float(r.angle_ci95),
            None if pd.isna(r.cos_theta) else float(r.cos_theta),
        )
        for r in points_df.itertuples(index=False)
    ]
    conn.executemany(
        """INSERT INTO wetting_points
           (curve_id, time_s, angle_mean, angle_sd, angle_ci95, cos_theta)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()


def get_wetting_curves(method_id: int) -> pd.DataFrame:
    """Список ранее сохранённых кривых для данного метода (архив)."""
    conn = get_connection()
    df = pd.read_sql(
        """SELECT id, liquid_name, source_file, fit_model, theta_inf,
                  fit_param2_name, fit_param2_value, r_squared, result_id, created_at
           FROM wetting_curves
           WHERE method_id = ?
           ORDER BY created_at DESC""",
        conn,
        params=(method_id,),
    )
    df["created_at"] = pd.to_datetime(df["created_at"])
    return df


def get_wetting_points(curve_id: int) -> pd.DataFrame:
    """Точки конкретной сохранённой кривой."""
    conn = get_connection()
    return pd.read_sql(
        """SELECT time_s, angle_mean, angle_sd, angle_ci95, cos_theta
           FROM wetting_points
           WHERE curve_id = ?
           ORDER BY time_s""",
        conn,
        params=(curve_id,),
    )


def delete_wetting_curve(curve_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM wetting_points WHERE curve_id = ?", (curve_id,))
    conn.execute("DELETE FROM wetting_curves WHERE id = ?", (curve_id,))
    conn.commit()
