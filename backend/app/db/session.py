from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
database_url = settings.database_url
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
is_sqlite = database_url.startswith("sqlite")
# Пул соединений к Postgres — реальный потолок параллелизма. Дефолт (5+10=15)
# тонок: FastAPI крутит sync-эндпоинты в threadpool (~40 нитей), которые все
# лезут в БД. Поднимаем до 10+20=30 (под лимитом Railway Postgres ~100, с
# запасом на bot+notifier). pool_pre_ping чинит протухшие после простоя
# соединения — иначе случайная ошибка на первом запросе после паузы. Для
# sqlite (dev/тесты) пул-параметры неприменимы — отдаём дефолт.
pool_kwargs = (
    {}
    if is_sqlite
    else {
        "pool_size": 10,
        "max_overflow": 20,
        "pool_timeout": 30,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }
)
engine = create_engine(database_url, connect_args=connect_args, future=True, **pool_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
