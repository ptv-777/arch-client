
# med-dicom-pipeline (MVP)

Минимально рабочий проект под ваши вводные: NAS (Synology) с DICOM, сервер обработки (API + индексация + паковка TAR.zst), клиенты на RED OS (Python/PySide6), ISO-инжест «+++».

## Быстрый старт (локально, без NAS)
1. Установить Python 3.10+ и создать venv:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Настроить переменные окружения (или `.env` — см. ниже):
   ```bash
   export DB_URL="sqlite:///dicom_index.sqlite3"
   export DICOM_ROOT="./_demo_studies"          # локальная папка с DICOM-файлами
   export CACHE_DIR="./cache"
   export INBOX_DIR="./_inbox_plus"
   ```
3. Инициализировать БД и прогнать индексацию демо-папки:
   ```bash
   python scripts/init_db.py
   python scripts/indexer.py --root "$DICOM_ROOT" --workers 8
   ```
4. Запустить API:
   ```bash
   uvicorn server.app:app --host 0.0.0.0 --port 8000
   ```
5. Запустить клиент:
   ```bash
   python client/client.py
   ```

## Переменные окружения
- `DB_URL` — строка подключения (SQLite или PostgreSQL), например:
  - SQLite: `sqlite:///dicom_index.sqlite3`
  - PostgreSQL: `postgresql+psycopg2://user:pass@host:5432/dicom`
- `DICOM_ROOT` — корень канонического хранилища `/studies/...`
- `CACHE_DIR` — каталог кэша архивов (`TAR.zst`)
- `INBOX_DIR` — папка «+++» для ISO
- `RADIANT_CMD` — команда запуска просмотрщика (если нужно автозапускать)

Создайте `.env` на основе `.env.example` или экспортируйте переменные.

## Эндпоинты (MVP)
- `GET /search?name=Иванов Иван&dob=19790101&sex=M&year=2024` → исследования (по `StudyInstanceUID`) с объёмами и количеством файлов.
- `GET /package?study_uid=<UID>` → формирование и выдача архива (если кэш есть — отдаёт сразу).

## Что уже есть
- Индексатор: читает заголовки DICOM (`stop_before_pixels=True`), сохраняет метаданные и пути.
- API FastAPI: поиск и упаковка в `TAR.zst` (кэшируется).
- Клиент PySide6: поиск → выбор → скачивание → распаковка → запуск просмотрщика на локальной папке, показывает индикатор прогресса и умеет работать как с `tar.zst`, так и с ZIP/TAR архивами.
- Скелет ISO-инжеста + systemd шаблоны.
- Схема БД через SQLAlchemy (можно переключить на PostgreSQL).

## Что осталось доделать (после MVP)
- Возобновляемые скачивания (HTTP Range) — сейчас выдача из файла целиком.
- Полный ISO-инжест (монтаж ISO, парсинг DICOMDIR) под вашу ОС.
- Дедуп по `SOPInstanceUID` + `pixeldata sha256`.
- RBAC/аудит, лимиты скорости, rpm-упаковка клиента под RED OS.

## Структура
```
server/
  app.py         # FastAPI, эндпоинты
  config.py      # загрузка env
  db.py          # модели и сессия SQLAlchemy
  packager.py    # TAR.zst упаковщик и кэш
  utils.py       # нормализация имени и т.п.
  ingest/
    ingest.py    # скелет ISO-инжеста
    systemd/
      iso-import@.service
      iso-watch.path
client/
  client.py      # GUI PySide6
  config.py
scripts/
  init_db.py     # создание таблиц
  indexer.py     # индексация каталога DICOM
.env.example
requirements.txt
README.md
```

## Лицензия
MIT (настраиваемо).
# arch-client
