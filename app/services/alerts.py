from __future__ import annotations

from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from tenacity import Retrying, stop_after_attempt, wait_fixed

from app.config import Settings
from app.models import AlertSent, Setting
from app.services.policy import OrderData, PolicyViolation


class AlertService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def already_sent(self, dedupe_key: str, email_to: str) -> bool:
        statement = select(AlertSent).where(
            AlertSent.dedupe_key == dedupe_key,
            AlertSent.email_to == email_to,
            AlertSent.status == "sent",
        )
        return self.db.scalar(statement) is not None

    def create_record(
        self,
        *,
        job_run_id: int,
        order: OrderData,
        violation: PolicyViolation,
        dedupe_key: str,
        email_to: str,
        status: str,
        provider_message_id: str | None = None,
        error_message: str | None = None,
    ) -> AlertSent:
        record = AlertSent(
            job_run_id=job_run_id,
            order_id=order.order_id,
            order_number=order.order_number,
            policy_code=violation.policy_code,
            dedupe_key=dedupe_key,
            email_to=email_to,
            status=status,
            provider_message_id=provider_message_id,
            error_message=error_message,
            sent_at=datetime.now(timezone.utc),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def send(self, email_to: str, subject: str, html: str) -> str:
        if not self.settings.resend_api_key:
            raise ValueError("RESEND_API_KEY nao configurada.")
        retrying = Retrying(
            stop=stop_after_attempt(self.settings.resend_retry_attempts),
            wait=wait_fixed(self.settings.resend_retry_backoff_seconds),
            reraise=True,
        )
        for attempt in retrying:
            with attempt:
                return self._send_once(email_to=email_to, subject=subject, html=html)
        raise RuntimeError("Falha inesperada no envio de email.")

    def _send_once(self, *, email_to: str, subject: str, html: str) -> str:
        current_settings = self.db.get(Setting, 1)
        from_email = (
            current_settings.resend_from_email
            if current_settings is not None
            else str(self.settings.resend_from_email)
        )
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {self.settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": from_email,
                "to": [email_to],
                "subject": subject,
                "html": html,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()
        return str(payload.get("id", ""))

    @staticmethod
    def build_subject(order: OrderData) -> str:
        return f"Alerta ERP - Pedido fora da politica - {order.order_number}"

    @staticmethod
    def build_body(order: OrderData, violation: PolicyViolation) -> str:
        customer = order.customer_name or "Nao informado"
        return f"""
        <h2>Pedido fora da politica</h2>
        <p><strong>Pedido:</strong> {order.order_number}</p>
        <p><strong>Cliente:</strong> {customer}</p>
        <p><strong>Data de emissao:</strong> {order.issue_date_display or "Nao informado"}</p>
        <p><strong>Valor bruto:</strong> R$ {order.gross_amount:.2f}</p>
        <p><strong>Desconto:</strong> {order.discount_percent:.2f}%</p>
        <p><strong>Parcelas:</strong> {order.installments_count}</p>
        <p><strong>Prazo total:</strong> {order.prazo_total_dias} dias</p>
        <p><strong>Violacao:</strong> {violation.description}</p>
        """
