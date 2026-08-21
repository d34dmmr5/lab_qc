# Установка и запуск — Контроль качества лаборатории

Приложение хранит все данные в одном файле `lab_qc.db` (SQLite) рядом
с программой. Отдельный сервер баз данных устанавливать не нужно.

## 1. Установите Python (если ещё не установлен)

Нужна версия 3.9 или новее.

- **Windows**: скачайте с https://www.python.org/downloads/ и при установке
  обязательно поставьте галочку **"Add Python to PATH"**.
- **RED OS / Linux**: обычно Python уже есть в системе. Проверить:
  ```
  python3 --version
  ```
  Если версии нет — установите через пакетный менеджер:
  ```
  sudo dnf install python3 python3-pip
  ```

## 2. Скопируйте файлы проекта

Положите все файлы (`app.py`, `db.py`, `charts.py`, `schema.sql`,
`requirements.txt`) в одну папку, например `lab_qc/`.

## 3. Установите зависимости

Откройте терминал (Windows: PowerShell или "Командная строка";
RED OS: обычный терминал), перейдите в папку проекта и выполните:

**Windows:**
```
cd путь\до\lab_qc
pip install -r requirements.txt
```

**RED OS / Linux:**
```
cd путь/до/lab_qc
pip3 install -r requirements.txt
```

Если пакетов в интернете нет (закрытый контур) — соберите их заранее
на машине с доступом в интернет через `pip download -r requirements.txt
-d ./packages`, перенесите папку `packages` на целевой компьютер и
установите командой `pip install --no-index --find-links=./packages
-r requirements.txt`.

## 4. Запустите приложение

**Windows:**
```
streamlit run app.py
```

**RED OS / Linux:**
```
python3 -m streamlit run app.py
```

После запуска в терминале появится адрес, например:
```
Local URL: http://localhost:8501
Network URL: http://192.168.1.50:8501
```

- **Local URL** — открывается в браузере на том же компьютере.
- **Network URL** — этот адрес можно дать коллегам в той же локальной
  сети, чтобы они открыли приложение в своём браузере без установки
  чего-либо у себя.

При первом запуске файл `lab_qc.db` и все таблицы в нём создаются
автоматически — ничего дополнительно настраивать не нужно.

## 5. Автозапуск при перезагрузке компьютера (опционально)

Если приложение должно работать постоянно на одном компьютере в
лаборатории:

**Windows** — создайте .bat-файл `start_lab_qc.bat`:
```
cd /d C:\путь\до\lab_qc
streamlit run app.py
```
и добавьте ярлык на него в папку автозагрузки
(`shell:startup` в строке "Выполнить").

**RED OS / Linux** — создайте systemd-сервис
`/etc/systemd/system/lab-qc.service`:
```ini
[Unit]
Description=Lab QC Streamlit App
After=network.target

[Service]
WorkingDirectory=/opt/lab_qc
ExecStart=/usr/bin/python3 -m streamlit run app.py --server.port 8501
Restart=always
User=labqc

[Install]
WantedBy=multi-user.target
```
и включите его:
```
sudo systemctl enable --now lab-qc
```

## 6. Резервное копирование

Файл `lab_qc.db` — это вся база данных. Регулярно копируйте его
(например, раз в день на сетевой диск или в облако) — это и есть
полный бэкап всех результатов контроля.
