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
            resend_from_email=str(settings.resend_from_email),
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
    ) -> Setting:
        if frequency_minutes <= 0:
            raise ValueError("A frequência deve ser maior que zero.")
        if dias_retroativos_emissao <= 0:
            raise ValueError("Os dias retroativos devem ser maiores que zero.")

        current = self.get()
        current.frequency_minutes = frequency_minutes
        current.dias_retroativos_emissao = dias_retroativos_emissao
        current.resend_from_email = resend_from_email.strip().lower()
        self.db.commit()
        self.db.refresh(current)
        return current

    @staticmethod
    def calculate_query_start(timezone_name: str, dias_retroativos_emissao: int) -> datetime:
        local_now = datetime.now(ZoneInfo(timezone_name))
        return local_now - timedelta(days=dias_retroativos_emissao)
