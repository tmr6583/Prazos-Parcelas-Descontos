from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import Base
from app.main import app
from app.services.admin import AdminService
from app.services.auth import AuthService
from app.services.olist import OlistService
from app.services.policy import PolicyRuleService
from app.services.settings import SettingsService


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


class DummyScheduler:
    def __init__(self) -> None:
        self.rescheduled = False

    def reschedule(self) -> None:
        self.rescheduled = True


@pytest.fixture()
def web_client(db_session: Session):
    original_overrides = dict(app.dependency_overrides)
    original_scheduler = getattr(app.state, "scheduler", None)

    settings = Settings()
    AuthService(db_session).bootstrap_master_user(settings)
    SettingsService(db_session).bootstrap(settings)
    AdminService(db_session).bootstrap_recipients("thiago@betinalimpeza.com.br")
    OlistService(db_session, settings).bootstrap_settings()
    PolicyRuleService(db_session).bootstrap_defaults()

    def override_get_db():
        yield db_session

    app.dependency_overrides = {**app.dependency_overrides}
    from app.db import get_db

    app.dependency_overrides[get_db] = override_get_db
    app.state.scheduler = DummyScheduler()

    client = TestClient(app)
    try:
        yield client, db_session, app.state.scheduler
    finally:
        client.close()
        app.dependency_overrides = original_overrides
        if original_scheduler is None and hasattr(app.state, "scheduler"):
            delattr(app.state, "scheduler")
        else:
            app.state.scheduler = original_scheduler
