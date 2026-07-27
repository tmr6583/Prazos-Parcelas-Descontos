from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BASE_DIR, get_settings
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

    def get_last_irregular_alert_for_run(self, job_run_id: int | None) -> AlertSent | None:
        if job_run_id is None:
            return None

        statement = (
            select(AlertSent)
            .where(AlertSent.job_run_id == job_run_id)
            .order_by(AlertSent.sent_at.desc(), AlertSent.id.desc())
            .limit(1)
        )
        return self.db.scalar(statement)

    def get_online_log_lines(self, limit: int = 10) -> list[str]:
        log_candidates = [
            BASE_DIR / "Cagoete.runtime.err.log",
            BASE_DIR / "Cagoete.runtime.log",
            BASE_DIR / "Cagoete.log",
        ]

        entries: list[tuple[datetime, str]] = []
        for path in log_candidates:
            if not path.exists() or path.stat().st_size == 0:
                continue
            entries.extend(self._read_log_entries(path))

        entries.sort(key=lambda item: item[0])
        return [line for _, line in entries[-limit:]]

    @staticmethod
    def _read_last_lines(path: Path, limit: int) -> list[str]:
        with path.open("r", encoding="utf-8", errors="replace") as file:
            return file.readlines()[-limit:]

    def _read_log_entries(self, path: Path) -> list[tuple[datetime, str]]:
        entries: list[tuple[datetime, str]] = []
        for raw_line in self._read_last_lines(path, 200):
            parsed = self._parse_log_line(raw_line)
            if parsed is not None:
                entries.append(parsed)
        return entries

    def _parse_log_line(self, raw_line: str) -> tuple[datetime, str] | None:
        line = raw_line.strip()
        if not line:
            return None

        if line.startswith("{"):
            return self._parse_json_log_line(line)
        return self._parse_text_log_line(line)

    def _parse_json_log_line(self, line: str) -> tuple[datetime, str] | None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None

        timestamp = str(payload.get("timestamp", "")).replace("Z", "+00:00")
        if not timestamp:
            return None

        try:
            parsed_at = datetime.fromisoformat(timestamp)
        except ValueError:
            return None

        level = str(payload.get("level", "INFO")).upper()
        event = str(payload.get("event", "")).strip()
        message = str(payload.get("message", "")).strip()
        context = payload.get("context") or {}

        suffix = ""
        if isinstance(context, dict):
            detail = context.get("detail")
            grant_type = context.get("grant_type")
            mode = context.get("mode")
            if detail:
                suffix = f" | {detail}"
            elif grant_type:
                suffix = f" | grant={grant_type}"
            elif mode:
                suffix = f" | modo={mode}"

        formatted = f"[{self._format_for_ui(parsed_at)}] [{level}] {message}"
        if event:
            formatted += f" ({event})"
        formatted += suffix
        return self._ensure_tz(parsed_at), formatted

    def _parse_text_log_line(self, line: str) -> tuple[datetime, str] | None:
        match = re.match(r"^\[(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})\]\s*(.+)$", line)
        if match is None:
            return None

        parsed_at = datetime.strptime(match.group(1), "%d/%m/%Y %H:%M:%S")
        formatted = f"[{self._format_for_ui(parsed_at)}] {match.group(2)}"
        return self._ensure_tz(parsed_at), formatted

    @staticmethod
    def _ensure_tz(value: datetime) -> datetime:
        timezone = ZoneInfo(get_settings().timezone)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone)
        return value.astimezone(timezone)

    def _format_for_ui(self, value: datetime) -> str:
        return self._ensure_tz(value).strftime("%Y-%m-%d %H:%M:%S")
