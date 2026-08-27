"""
Слой доступа к данным (DAO).

Отличия от предыдущей версии db.py:
  - методы возвращают типизированные dataclass'ы (models.py), а не голые DataFrame;
  - многошаговые операции (сохранение кривой + точек, удаление кривой + точек)
    выполняются в одной транзакции через `with conn:` — либо применяются
    целиком, либо откатываются целиком;
  - есть явная валидация входных данных (пустое имя, неположительное SD,
    пустой оператор и т.п.) с понятными сообщениями об ошибке вместо
    неявных ошибок SQLite или "тихого" некорректного состояния.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Optional

import pandas as pd
import streamlit as st

import config
from models import ControlMethod, ControlResult, WettingCurveRecord


class ValidationError(ValueError):
    """Ошибка валидации входных данных перед записью в БД."""


@st.cache_resource
def get_connection() -> sqlite3.Connection:
    """
    Создаёт (или открывает существующее) подключение к файлу базы данных.
    check_same_thread=False нужен, потому что Streamlit может обращаться
    к соединению из разных потоков.
    """
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """При первом запуске создаёт таблицы, если их ещё нет."""
    with open(config.SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    _run_migrations(conn)


def _run_migrations(conn: sqlite3.Connection) -> None:
    """
    Точечные миграции для баз, созданных до появления некоторых колонок.
    CREATE TABLE IF NOT EXISTS не добавляет новые колонки в уже существующую
    таблицу, поэтому недостающие столбцы добавляются вручную через ALTER TABLE.
    """
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(wetting_curves)")}
    if "fit_coeffs_json" not in existing_cols:
        conn.execute("ALTER TABLE wetting_curves ADD COLUMN fit_coeffs_json TEXT")
    conn.commit()


def _parse_dt(value) -> Optional[datetime]:
    if value is None:
        return None
    return pd.to_datetime(value).to_pydatetime()


# --------------------------------------------------------------------------
# Методы контроля
# --------------------------------------------------------------------------

def list_methods() -> list[ControlMethod]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, name, unit, target_value, target_sd, created_at "
        "FROM control_methods ORDER BY name"
    ).fetchall()
    return [
        ControlMethod(
            id=r["id"], name=r["name"], unit=r["unit"],
            target_value=r["target_value"], target_sd=r["target_sd"],
            created_at=_parse_dt(r["created_at"]),
        )
        for r in rows
    ]


def get_method(method_id: int) -> Optional[ControlMethod]:
    conn = get_connection()
    r = conn.execute(
        "SELECT id, name, unit, target_value, target_sd, created_at "
        "FROM control_methods WHERE id = ?",
        (method_id,),
    ).fetchone()
    if r is None:
        return None
    return ControlMethod(
        id=r["id"], name=r["name"], unit=r["unit"],
        target_value=r["target_value"], target_sd=r["target_sd"],
        created_at=_parse_dt(r["created_at"]),
    )


def add_method(name: str, unit: str, target_value: float, target_sd: float) -> int:
    name = (name or "").strip()
    unit = (unit or "").strip()
    if not name:
        raise ValidationError("Название метода не может быть пустым")
    if not unit:
        raise ValidationError("Единица измерения не может быть пустой")
    if target_sd < config.MIN_METHOD_SD:
        raise ValidationError(f"SD должно быть больше {config.MIN_METHOD_SD}")

    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO control_methods (name, unit, target_value, target_sd)
               VALUES (?, ?, ?, ?)""",
            (name, unit, target_value, target_sd),
        )
    return cur.lastrowid


# --------------------------------------------------------------------------
# Результаты контроля (точки карты Шухарта)
# --------------------------------------------------------------------------

def list_results(method_id: int, limit: int = config.MAX_RESULTS_PER_METHOD) -> list[ControlResult]:
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, method_id, measured_value, measured_at, operator, comment, created_at
           FROM control_results
           WHERE method_id = ?
           ORDER BY measured_at DESC
           LIMIT ?""",
        (method_id, limit),
    ).fetchall()
    results = [
        ControlResult(
            id=r["id"], method_id=r["method_id"], measured_value=r["measured_value"],
            measured_at=_parse_dt(r["measured_at"]), operator=r["operator"],
            comment=r["comment"] or "", created_at=_parse_dt(r["created_at"]),
        )
        for r in rows
    ]
    return sorted(results, key=lambda x: x.measured_at)


def results_to_dataframe(results: list[ControlResult]) -> pd.DataFrame:
    """Табличное представление для графиков — pandas здесь уместен и удобен."""
    return pd.DataFrame(
        {
            "id": [r.id for r in results],
            "measured_value": [r.measured_value for r in results],
            "measured_at": [r.measured_at for r in results],
            "operator": [r.operator for r in results],
            "comment": [r.comment for r in results],
        }
    )


def add_result(method_id: int, value: float, operator: str, comment: str = "") -> int:
    operator = (operator or "").strip()
    if config.REQUIRE_OPERATOR_FOR_RESULTS and not operator:
        raise ValidationError("Оператор обязателен для аудит-трейла")
    if get_method(method_id) is None:
        raise ValidationError(f"Метод с id={method_id} не найден")

    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO control_results (method_id, measured_value, operator, comment)
               VALUES (?, ?, ?, ?)""",
            (method_id, value, operator, comment),
        )
    return cur.lastrowid


# --------------------------------------------------------------------------
# Кривые угла смачивания
# --------------------------------------------------------------------------

def save_wetting_curve(
    method_id: int,
    liquid_name: str,
    source_file: Optional[str],
    points: pd.DataFrame,
    fit_model: Optional[str] = None,
    theta_inf: Optional[float] = None,
    fit_param2_name: Optional[str] = None,
    fit_param2_value: Optional[float] = None,
    r_squared: Optional[float] = None,
    result_id: Optional[int] = None,
    fit_coeffs_json: Optional[str] = None,
) -> int:
    """
    Сохраняет кривую (метаданные + точки) атомарно в одной транзакции:
    если вставка точек упадёт, метаданные кривой тоже не сохранятся.
    """
    liquid_name = (liquid_name or "").strip()
    if not liquid_name:
        raise ValidationError("Название жидкости/серии не может быть пустым")
    if points is None or points.empty:
        raise ValidationError("Нет точек кривой для сохранения")
    if get_method(method_id) is None:
        raise ValidationError(f"Метод с id={method_id} не найден")

    conn = get_connection()
    with conn:
        cur = conn.execute(
            """INSERT INTO wetting_curves
               (method_id, liquid_name, source_file, fit_model, theta_inf,
                fit_param2_name, fit_param2_value, r_squared, result_id, fit_coeffs_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                method_id, liquid_name, source_file, fit_model, theta_inf,
                fit_param2_name, fit_param2_value, r_squared, result_id, fit_coeffs_json,
            ),
        )
        curve_id = cur.lastrowid

        rows = [
            (
                curve_id, float(r.time_s), float(r.angle_mean),
                None if pd.isna(r.angle_sd) else float(r.angle_sd),
                None if pd.isna(r.angle_ci95) else float(r.angle_ci95),
                None if pd.isna(r.cos_theta) else float(r.cos_theta),
            )
            for r in points.itertuples(index=False)
        ]
        conn.executemany(
            """INSERT INTO wetting_points
               (curve_id, time_s, angle_mean, angle_sd, angle_ci95, cos_theta)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
    return curve_id


def list_wetting_curves(method_id: int) -> list[WettingCurveRecord]:
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, method_id, liquid_name, source_file, fit_model, theta_inf,
                  fit_param2_name, fit_param2_value, r_squared, result_id,
                  fit_coeffs_json, created_at
           FROM wetting_curves
           WHERE method_id = ?
           ORDER BY created_at DESC""",
        (method_id,),
    ).fetchall()
    return [
        WettingCurveRecord(
            id=r["id"], method_id=r["method_id"], liquid_name=r["liquid_name"],
            source_file=r["source_file"], fit_model=r["fit_model"], theta_inf=r["theta_inf"],
            fit_param2_name=r["fit_param2_name"], fit_param2_value=r["fit_param2_value"],
            r_squared=r["r_squared"], result_id=r["result_id"],
            fit_coeffs_json=r["fit_coeffs_json"], created_at=_parse_dt(r["created_at"]),
        )
        for r in rows
    ]


def get_wetting_points(curve_id: int) -> pd.DataFrame:
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
    """Удаляет кривую и все её точки атомарно (в одной транзакции)."""
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM wetting_points WHERE curve_id = ?", (curve_id,))
        conn.execute("DELETE FROM wetting_curves WHERE id = ?", (curve_id,))
