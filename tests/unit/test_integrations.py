from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.config import Settings
from app.models import Setting
from app.services.alerts import AlertService
from app.services.olist import OlistService


class DummyResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


def test_refresh_token_persists_new_tokens(db_session, monkeypatch) -> None:
    settings = Settings(
        olist_client_id="client-id",
        olist_client_secret="client-secret",
        olist_token_url="https://example.com/token",
    )
    service = OlistService(db_session, settings)

    def fake_post(url: str, headers: dict, data: dict, timeout: float):
        assert url == "https://example.com/token"
        assert data["grant_type"] == "refresh_token"
        return DummyResponse(
            {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
                "scope": "openid",
                "token_type": "Bearer",
            },
        )

    monkeypatch.setattr("app.services.olist.httpx.post", fake_post)

    token = service.refresh_token("old-refresh")

    assert token.access_token == "new-access"
    assert token.refresh_token == "new-refresh"
    assert token.expires_at is not None
    normalized_expires_at = token.expires_at if token.expires_at.tzinfo else token.expires_at.replace(tzinfo=UTC)
    assert normalized_expires_at > datetime.now(UTC) + timedelta(minutes=50)


def test_alert_service_retries_and_succeeds(db_session, monkeypatch) -> None:
    db_session.add(
        Setting(
            id=1,
            frequency_minutes=30,
            dias_retroativos_emissao=7,
            timezone="America/Sao_Paulo",
            resend_from_email="financeiro@betinalimpeza.com.br",
        ),
    )
    db_session.commit()

    settings = Settings(
        resend_api_key="resend-key",
        resend_retry_attempts=3,
        resend_retry_backoff_seconds=0,
    )
    service = AlertService(db_session, settings)
    attempts = {"count": 0}

    def fake_post(url: str, headers: dict, json: dict, timeout: float):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("falha temporaria")
        return DummyResponse({"id": "email-123"})

    monkeypatch.setattr("app.services.alerts.httpx.post", fake_post)

    message_id = service.send("destino@empresa.com", "Assunto", "<p>teste</p>")

    assert message_id == "email-123"
    assert attempts["count"] == 3
