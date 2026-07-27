from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AlertSent, JobRun, OAuthToken, Recipient


class AdminService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def bootstrap_recipients(self, initial_email: str) -> None:
        if not initial_email:
            return

        recipient = self.db.scalar(select(Recipient).where(Recipient.email == initial_email))
        if recipient is None:
            self.db.add(Recipient(email=initial_email))
            self.db.commit()

    def list_recipients(self) -> list[Recipient]:
        statement = (
            select(Recipient)
            .where(Recipient.is_deleted.is_(False))
            .order_by(Recipient.is_active.desc(), Recipient.email.asc())
        )
        return list(self.db.scalars(statement))

    def list_active_recipients(self) -> list[Recipient]:
        statement = (
            select(Recipient)
            .where(Recipient.is_deleted.is_(False), Recipient.is_active.is_(True))
            .order_by(Recipient.email.asc())
        )
        return list(self.db.scalars(statement))

    def add_recipient(self, email: str) -> Recipient:
        normalized_email = email.strip().lower()
        existing = self.db.scalar(select(Recipient).where(Recipient.email == normalized_email))
        if existing and not existing.is_deleted:
            raise ValueError("Ja existe um destinatario com este email.")

        if existing and existing.is_deleted:
            existing.is_deleted = False
            existing.is_active = True
            self.db.commit()
            self.db.refresh(existing)
            return existing

        recipient = Recipient(email=normalized_email)
        self.db.add(recipient)
        self.db.commit()
        self.db.refresh(recipient)
        return recipient

    def toggle_recipient(self, recipient_id: int) -> None:
        recipient = self.db.get(Recipient, recipient_id)
        if recipient is None or recipient.is_deleted:
            raise ValueError("Destinatario nao encontrado.")
        recipient.is_active = not recipient.is_active
        self.db.commit()

    def soft_delete_recipient(self, recipient_id: int) -> None:
        recipient = self.db.get(Recipient, recipient_id)
        if recipient is None or recipient.is_deleted:
            raise ValueError("Destinatario nao encontrado.")
        recipient.is_deleted = True
        recipient.is_active = False
        self.db.commit()

    def get_olist_token(self) -> OAuthToken | None:
        return self.db.scalar(select(OAuthToken).where(OAuthToken.provider == "olist"))

    def list_recent_runs(self, limit: int = 20) -> list[JobRun]:
        return list(self.db.scalars(select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)))

    def list_recent_alerts(self, limit: int = 50) -> list[AlertSent]:
        return list(self.db.scalars(select(AlertSent).order_by(AlertSent.sent_at.desc()).limit(limit)))
