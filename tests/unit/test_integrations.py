from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

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


class DummySMTPSSL:
    def __init__(self, host: str, port: int, context: object, timeout: int) -> None:
        self.host = host
        self.port = port
        self.context = context
        self.timeout = timeout
        self.attempts: list[dict] = []

    def __enter__(self) -> "DummySMTPSSL":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def ehlo(self) -> None:
        self.attempts.append({"action": "ehlo"})

    def login(self, username: str, password: str) -> None:
        self.attempts.append({"action": "login", "username": username, "password": password})

    def sendmail(self, from_addr: str, to_addrs: list[str], message: str) -> None:
        self.attempts.append(
            {
                "action": "sendmail",
                "from_addr": from_addr,
                "to_addrs": to_addrs,
                "message": message,
            },
        )


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


def test_alert_service_smtp_retries_and_succeeds(db_session, monkeypatch) -> None:
    db_session.add(
        Setting(
            id=1,
            frequency_minutes=30,
            dias_retroativos_emissao=7,
            timezone="America/Sao_Paulo",
            resend_from_email="financeiro@betinalimpeza.com.br",
            smtp_host="email-ssl.com.br",
            smtp_port=465,
            smtp_user="financeiro@betinalimpeza.com.br",
            smtp_password="senha-atual",
            email_from_name="Betina Limpeza",
            email_from_email="financeiro@betinalimpeza.com.br",
        ),
    )
    db_session.commit()

    settings = Settings(
        email_retry_attempts=3,
        email_retry_backoff_seconds=0,
        smtp_host="email-ssl.com.br",
        smtp_port=465,
        smtp_user="financeiro@betinalimpeza.com.br",
        smtp_password="senha-atual",
        email_from_name="Betina Limpeza",
        email_from_email="financeiro@betinalimpeza.com.br",
    )
    service = AlertService(db_session, settings)
    attempts_count = {"count": 0}
    last_instance: DummySMTPSSL | None = None

    def fake_smtp_ssl(host: str, port: int, context: object, timeout: int) -> DummySMTPSSL:
        attempts_count["count"] += 1
        nonlocal last_instance
        instance = DummySMTPSSL(host, port, context, timeout)
        last_instance = instance
        if attempts_count["count"] < 3:

            class FailingSMTPSSL(DummySMTPSSL):
                def sendmail(self, from_addr, to_addrs, message):
                    super().sendmail(from_addr, to_addrs, message)
                    raise RuntimeError("falha temporaria")

            failing = FailingSMTPSSL(host, port, context, timeout)
            last_instance = failing
            return failing
        return instance

    monkeypatch.setattr("app.services.alerts.smtplib.SMTP_SSL", fake_smtp_ssl)

    message_id = service.send("destino@empresa.com", "Assunto", "<p>teste</p>")

    assert message_id == "smtp:email-ssl.com.br:465"
    assert attempts_count["count"] == 3
    assert last_instance is not None
    login_attempt = next(item for item in last_instance.attempts if item["action"] == "login")
    assert login_attempt["username"] == "financeiro@betinalimpeza.com.br"
    assert login_attempt["password"] == "senha-atual"
    sendmail_attempts = [item for item in last_instance.attempts if item["action"] == "sendmail"]
    assert len(sendmail_attempts) >= 1
    assert "Betina Limpeza" in sendmail_attempts[-1]["from_addr"]
    assert "financeiro@betinalimpeza.com.br" in sendmail_attempts[-1]["from_addr"]
    assert sendmail_attempts[-1]["to_addrs"] == ["destino@empresa.com"]
    message_text = sendmail_attempts[-1]["message"]
    assert "Subject: Assunto" in message_text
    assert "multipart/alternative" in message_text
    assert "PHA+dGVzdGU8L3A+" in message_text or "<p>teste</p>" in base64.b64decode(
        message_text.split("PHA+")[1].split("=")[0] + "=="
    ).decode("utf-8")
