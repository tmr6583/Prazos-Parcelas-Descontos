from __future__ import annotations

from datetime import timedelta

from app.config import Settings
from app.services.auth import AuthService
from app.services.settings import SettingsService


def test_bootstrap_master_user_and_authenticate(db_session) -> None:
    settings = Settings(master_user_password="SenhaSegura123")
    auth = AuthService(db_session)

    user = auth.bootstrap_master_user(settings)
    authenticated = auth.authenticate(str(settings.master_user_email), "SenhaSegura123")

    assert user.is_master is True
    assert authenticated is not None
    assert authenticated.email == str(settings.master_user_email)


def test_calculate_query_start_uses_configured_window() -> None:
    start = SettingsService.calculate_query_start("America/Sao_Paulo", 7)
    now = SettingsService.calculate_query_start("America/Sao_Paulo", 0)

    delta = now - start
    assert timedelta(days=6, hours=23, minutes=59) <= delta <= timedelta(days=7, minutes=1)
