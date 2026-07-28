from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Setting


class SettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def bootstrap(self, settings: Settings) -> Setting:
        current = self.db.get(Setting, 1)
        if current is not None:
            return current

        current = Setting(
            id=1,
            frequency_minutes=settings.frequency_minutes,
            dias_retroativos_emissao=settings.dias_retroativos_emissao_default,
            timezone=settings.timezone,
            resend_from_email=str(settings.email_from_email),
            smtp_host=settings.smtp_host,
            smtp_port=int(settings.smtp_port),
            smtp_user=settings.smtp_user,
            smtp_password=settings.smtp_password,
            email_from_name=settings.email_from_name,
            email_from_email=str(settings.email_from_email),
        )
        self.db.add(current)
        self.db.commit()
        self.db.refresh(current)
        return current

    def get(self) -> Setting:
        current = self.db.get(Setting, 1)
        if current is None:
            raise RuntimeError("Configuração inicial não encontrada.")
        return current

    def update(
        self,
        frequency_minutes: int,
        dias_retroativos_emissao: int,
        resend_from_email: str,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_password: str,
        email_from_name: str,
        email_from_email: str,
    ) -> Setting:
        if frequency_minutes <= 0:
            raise ValueError("A frequência deve ser maior que zero.")
        if dias_retroativos_emissao <= 0:
            raise ValueError("Os dias retroativos devem ser maiores que zero.")
        if smtp_port <= 0:
            raise ValueError("A porta SMTP deve ser maior que zero.")

        current = self.get()
        current.frequency_minutes = frequency_minutes
        current.dias_retroativos_emissao = dias_retroativos_emissao
        current.resend_from_email = resend_from_email.strip().lower()
        current.smtp_host = smtp_host.strip()
        current.smtp_port = int(smtp_port)
        current.smtp_user = smtp_user.strip()
        if smtp_password != "":
            current.smtp_password = smtp_password
        current.email_from_name = email_from_name.strip()
        current.email_from_email = email_from_email.strip().lower()
        self.db.commit()
        self.db.refresh(current)
        return current

    @staticmethod
    def calculate_query_start(timezone_name: str, dias_retroativos_emissao: int) -> datetime:
        local_now = datetime.now(ZoneInfo(timezone_name))
        return local_now - timedelta(days=dias_retroativos_emissao)
