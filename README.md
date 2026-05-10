# Tashkent Value Flats

MVP веб-сервиса для агрегирования объявлений о продаже квартир в Ташкенте и поиска вариантов минимум на 15% ниже рынка.

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

Импорт fixture-объявлений:

```bash
curl -X POST http://localhost:8000/api/admin/scrape/run \
  -H "Content-Type: application/json" \
  -d '{"source":"all"}'
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

По умолчанию сервис не ходит на внешние сайты. Адаптеры работают на fixture-HTML, чтобы MVP был воспроизводимым и не нарушал правила площадок. Перед включением live-сбора нужно проверить robots.txt/ToS, допустимую частоту запросов и наличие публичных или партнёрских фидов.
