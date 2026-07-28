from __future__ import annotations

import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

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
        statement = select(AlertSent).where(
            AlertSent.dedupe_key == dedupe_key,
            AlertSent.email_to == email_to,
        )
        record = self.db.scalar(statement)

        if record is None:
            record = AlertSent(
                job_run_id=job_run_id,
                order_id=order.order_id,
                order_number=order.order_number,
                policy_code=violation.policy_code,
                dedupe_key=dedupe_key,
                email_to=email_to,
            )
            self.db.add(record)

        record.job_run_id = job_run_id
        record.order_id = order.order_id
        record.order_number = order.order_number
        record.policy_code = violation.policy_code
        record.status = status
        record.provider_message_id = provider_message_id
        record.error_message = error_message
        record.sent_at = datetime.now(timezone.utc)

        self.db.commit()
        self.db.refresh(record)
        return record

    def _resolve_smtp_config(self) -> tuple[str, int, str, str, str, str]:
        current_settings = self.db.get(Setting, 1)
        if current_settings is not None:
            smtp_host = current_settings.smtp_host or self.settings.smtp_host
            smtp_port = int(current_settings.smtp_port or self.settings.smtp_port)
            smtp_user = current_settings.smtp_user or self.settings.smtp_user
            smtp_password = current_settings.smtp_password or self.settings.smtp_password
            email_from_name = current_settings.email_from_name or self.settings.email_from_name
            email_from_email = current_settings.email_from_email or str(self.settings.email_from_email)
        else:
            smtp_host = self.settings.smtp_host
            smtp_port = int(self.settings.smtp_port)
            smtp_user = self.settings.smtp_user
            smtp_password = self.settings.smtp_password
            email_from_name = self.settings.email_from_name
            email_from_email = str(self.settings.email_from_email)

        if not smtp_host:
            raise ValueError("Servidor SMTP não configurado.")
        if smtp_port <= 0:
            raise ValueError("Porta SMTP inválida.")
        if not smtp_user:
            raise ValueError("Usuário de e-mail não configurado.")
        if not smtp_password:
            raise ValueError("Senha de e-mail não configurada.")
        if not email_from_email:
            raise ValueError("Remetente de e-mail não configurado.")

        return (
            smtp_host.strip(),
            smtp_port,
            smtp_user.strip(),
            smtp_password,
            email_from_name.strip() or email_from_email.split("@", 1)[0],
            email_from_email.strip().lower(),
        )

    def send(self, email_to: str, subject: str, html: str) -> str:
        retrying = Retrying(
            stop=stop_after_attempt(self.settings.email_retry_attempts),
            wait=wait_fixed(self.settings.email_retry_backoff_seconds),
            reraise=True,
        )
        for attempt in retrying:
            with attempt:
                return self._send_once(email_to=email_to, subject=subject, html=html)
        raise RuntimeError("Falha inesperada no envio de e-mail.")

    def _send_once(self, *, email_to: str, subject: str, html: str) -> str:
        (
            smtp_host,
            smtp_port,
            smtp_user,
            smtp_password,
            email_from_name,
            email_from_email,
        ) = self._resolve_smtp_config()

        from_header = formataddr((email_from_name, email_from_email))
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_header
        msg["To"] = email_to

        msg.attach(MIMEText(html, "html", "utf-8"))

        context = ssl.create_default_context()
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context, timeout=30) as smtp:
                smtp.ehlo()
                smtp.login(smtp_user, smtp_password)
                smtp.sendmail(from_header, [email_to], msg.as_string())
                return f"smtp:{smtp_host}:{smtp_port}"
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            if smtp.has_extn("starttls"):
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(smtp_user, smtp_password)
            smtp.sendmail(from_header, [email_to], msg.as_string())
            return f"smtp:{smtp_host}:{smtp_port}"

    @staticmethod
    def build_subject(order: OrderData) -> str:
        return f"Alerta ERP - Pedido fora da política - {order.order_number}"

    @staticmethod
    def build_body(order: OrderData, violation: PolicyViolation) -> str:
        customer = order.customer_name or "Não informado"
        return f"""
        <h2>Pedido fora da política</h2>
        <p><strong>Pedido:</strong> {order.order_number}</p>
        <p><strong>Cliente:</strong> {customer}</p>
        <p><strong>Data de emissão:</strong> {order.issue_date_display or "Não informado"}</p>
        <p><strong>Valor bruto:</strong> R$ {order.gross_amount:.2f}</p>
        <p><strong>Desconto:</strong> {order.discount_percent:.2f}%</p>
        <p><strong>Parcelas:</strong> {order.installments_count}</p>
        <p><strong>Prazo total:</strong> {order.prazo_total_dias} dias</p>
        <p><strong>Violação:</strong> {violation.description}</p>
        """
