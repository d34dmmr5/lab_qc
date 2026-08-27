-- Методы/показатели, по которым ведётся контроль качества
CREATE TABLE IF NOT EXISTS control_methods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,                -- напр. "Титрование HCl, метод X"
    unit TEXT NOT NULL,                -- напр. "мг/л"
    target_value REAL NOT NULL,        -- целевое значение контрольного образца
    target_sd REAL NOT NULL,           -- целевое стандартное отклонение (для карты Шухарта)
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Результаты контрольных измерений (точки на карте Шухарта)
CREATE TABLE IF NOT EXISTS control_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    method_id INTEGER NOT NULL REFERENCES control_methods(id),
    measured_value REAL NOT NULL,
    measured_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    operator TEXT NOT NULL,            -- аудит-трейл: кто ввёл результат
    comment TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Компоненты бюджета неопределённости (GUM) — понадобится на следующем шаге
CREATE TABLE IF NOT EXISTS uncertainty_components (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    method_id INTEGER NOT NULL REFERENCES control_methods(id),
    source_name TEXT NOT NULL,         -- напр. "повторяемость", "калибровка пипетки"
    component_type TEXT CHECK (component_type IN ('A', 'B')),
    value REAL NOT NULL,               -- стандартная неопределённость источника
    distribution TEXT DEFAULT 'normal',-- normal, rectangular, triangular
    sensitivity_coefficient REAL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_results_method_date
    ON control_results (method_id, measured_at);

-- Кривые угла смачивания: одна запись = одна обработанная серия
-- параллельных измерений для одной жидкости на одной поверхности.
-- method_id ссылается на control_methods (метод типа "угол смачивания"),
-- чтобы итоговое равновесное значение theta_inf можно было положить
-- на карту Шухарта как обычный control_results.
CREATE TABLE IF NOT EXISTS wetting_curves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    method_id INTEGER NOT NULL REFERENCES control_methods(id),
    liquid_name TEXT NOT NULL,         -- напр. "вода", "глицерин"
    source_file TEXT,                  -- имя исходного .xls/.csv файла
    fit_model TEXT,                    -- 'exponential' | 'power_law'
    theta_inf REAL,                    -- равновесный угол смачивания, °
    fit_param2_name TEXT,              -- 'tau' (экспонента) / 'n' (степенной закон) / 'degree' (полином)
    fit_param2_value REAL,
    r_squared REAL,                    -- качество аппроксимации
    fit_coeffs_json TEXT,              -- полный набор параметров модели (JSON), напр. все
                                        -- коэффициенты полинома c0..cN — для архива и повторного анализа
    result_id INTEGER REFERENCES control_results(id), -- если theta_inf сохранён на карту Шухарта
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Точки усреднённой (по параллельным измерениям) кривой угол(время)
CREATE TABLE IF NOT EXISTS wetting_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    curve_id INTEGER NOT NULL REFERENCES wetting_curves(id),
    time_s REAL NOT NULL,
    angle_mean REAL NOT NULL,          -- среднее по параллельным измерениям, °
    angle_sd REAL,                     -- выборочное СКО между параллельными измерениями
    angle_ci95 REAL,                   -- полуширина 95% ДИ по Стьюденту
    cos_theta REAL
);

CREATE INDEX IF NOT EXISTS idx_wetting_points_curve
    ON wetting_points (curve_id, time_s);

CREATE INDEX IF NOT EXISTS idx_wetting_curves_method
    ON wetting_curves (method_id, created_at);
