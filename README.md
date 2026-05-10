# Tashkent Value Flats

MVP веб-сервиса для агрегирования объявлений о продаже квартир в Ташкенте и поиска вариантов минимум на 15% ниже рынка.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Asekesh/tashkent-value-flats)

## Что внутри

- FastAPI backend с SQLAlchemy, Alembic-ready структурой и SQLite по умолчанию.
- Адаптеры источников: OLX.uz, Uybor, Realt24.
- Нормализация объявлений, цена за м2, дедупликация и рыночная оценка по дому/району.
- React/Vite frontend с таблицей, фильтрами и карточкой объявления.
- Pytest tests для парсеров, дедупликации, оценки рынка и API.
- Docker Compose с PostgreSQL для окружения ближе к production.

## Быстрый старт backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
python3 -m uvicorn app.main:app --reload
```

Веб-интерфейс и API будут доступны на `http://127.0.0.1:8000`.

Ручной запуск сбора:

```bash
curl -X POST http://localhost:8000/api/admin/scrape/run \
  -H "Content-Type: application/json" \
  -d '{"source":"olx","mode":"live"}'
```

## Frontend

Основной интерфейс уже встроен в backend и открывается по `http://127.0.0.1:8000`.
Папка `frontend/` содержит React/Vite-версию для дальнейшей разработки, но для запуска MVP она не обязательна.

## Онлайн-запуск

Самый простой production-вариант: деплой `backend/` как Docker/FastAPI app и подключение PostgreSQL через `DATABASE_URL`.

Обязательные переменные окружения:

```bash
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DB_NAME
CORS_ORIGINS=https://your-domain.example
```

Команда запуска:

```bash
python3 -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Источники и live scraping

По умолчанию локальный запуск работает на fixture-HTML. В production live-сбор включается переменными `ALLOW_LIVE_SCRAPING=true`, `ENABLE_SCRAPE_SCHEDULER=true`, `SCRAPE_INTERVAL_MINUTES=15`.

В текущей версии live-сбор реализован для OLX.uz. Uybor и Realt24 остаются fixture-адаптерами до отдельного подключения.
