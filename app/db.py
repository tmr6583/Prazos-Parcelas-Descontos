from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import BASE_DIR, get_settings


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_path(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return

    relative_path = database_url.removeprefix("sqlite:///")
    db_path = (BASE_DIR / relative_path).resolve()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)


settings = get_settings()
_ensure_sqlite_path(settings.database_url)

engine = create_engine(settings.database_url, future=True, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
