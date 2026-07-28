from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import IdentifiedOrder, JobRun
from app.services.admin import AdminService
from app.services.alerts import AlertService
from app.services.olist import OlistService
from app.services.policy import PolicyEngine, PolicyRuleService
from app.services.runtime_log import write_runtime_event
from app.services.settings import SettingsService


class ExecutionService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.settings_service = SettingsService(db)
        self.admin_service = AdminService(db)
        self.olist_service = OlistService(db, settings)
        self.alert_service = AlertService(db, settings)
        self.policy_rule_service = PolicyRuleService(db)

    def run(self, trigger_type: str) -> JobRun:
        config = self.settings_service.get()
        rules = self.policy_rule_service.list_current_rules()
        if not rules:
            raise RuntimeError("Nenhuma política comercial ativa foi configurada.")

        version_group = self.policy_rule_service.get_current_version_group()
        query_start = self.settings_service.calculate_query_start(
            timezone_name=config.timezone,
            dias_retroativos_emissao=config.dias_retroativos_emissao,
        )

        job_run = JobRun(
            trigger_type=trigger_type,
            query_start_date=query_start,
            policy_version_group=version_group,
        )
        self.db.add(job_run)
        self.db.commit()
        self.db.refresh(job_run)

        write_runtime_event(
            "execution_started",
            "Execução da rotina iniciada.",
            trigger_type=trigger_type,
            query_start_date=query_start.isoformat(),
            policy_version_group=version_group,
        )

        try:
            recipients = self.admin_service.list_active_recipients()
            orders = self.olist_service.fetch_orders(query_start)
            irregular_orders = 0
            policy_engine = PolicyEngine(rules)

            write_runtime_event(
                "execution_olist_summary",
                (
                    "Consulta operacional da Olist recebida pela rotina. "
                    f"Pedidos avaliáveis: {len(orders)} | Destinatários ativos: {len(recipients)}."
                ),
                trigger_type=trigger_type,
                orders_evaluated=len(orders),
                recipients_count=len(recipients),
            )

            for order in orders:
                violations = policy_engine.evaluate(order)
                if not violations:
                    continue

                irregular_orders += 1
                logical_window = query_start.date().isoformat()
                for violation in violations:
                    self.db.add(
                        IdentifiedOrder(
                            job_run_id=job_run.id,
                            order_id=order.order_id,
                            order_number=order.order_number,
                            policy_code=violation.policy_code,
                            violation_description=violation.description,
                            sale_date_display=order.issue_date_display or None,
                            gross_amount=order.gross_amount,
                            discount_amount=order.discount_amount,
                            discount_percent=order.discount_percent,
                            seller_name=order.seller_name,
                            customer_name=order.customer_name,
                        ),
                    )
                    dedupe_key = f"{violation.policy_code}:{order.order_id}:{logical_window}"
                    for recipient in recipients:
                        if self.alert_service.already_sent(dedupe_key, recipient.email):
                            continue

                        try:
                            provider_id = self.alert_service.send(
                                email_to=recipient.email,
                                subject=self.alert_service.build_subject(order),
                                html=self.alert_service.build_body(order, violation),
                            )
                            self.alert_service.create_record(
                                job_run_id=job_run.id,
                                order=order,
                                violation=violation,
                                dedupe_key=dedupe_key,
                                email_to=recipient.email,
                                status="sent",
                                provider_message_id=provider_id,
                            )
                        except Exception as exc:
                            self.alert_service.create_record(
                                job_run_id=job_run.id,
                                order=order,
                                violation=violation,
                                dedupe_key=dedupe_key,
                                email_to=recipient.email,
                                status="failed",
                                error_message=str(exc),
                            )

                    write_runtime_event(
                        "identified_order_recorded",
                        (
                            "Pedido identificado fora da política comercial. "
                            f"Pedido: {order.order_number} | Cliente: {order.customer_name or 'Não informado'} | "
                            f"Valor total: R$ {order.gross_amount:.2f} | Desconto: {order.discount_percent:.2f}%."
                        ),
                        order_id=order.order_id,
                        order_number=order.order_number,
                        policy_code=violation.policy_code,
                        customer_name=order.customer_name,
                    )

            job_run.status = "success"
            job_run.orders_evaluated = len(orders)
            job_run.orders_irregular = irregular_orders
            write_runtime_event(
                "execution_finished",
                "Execução da rotina concluída.",
                trigger_type=trigger_type,
                status=job_run.status,
                orders_evaluated=job_run.orders_evaluated,
                orders_irregular=job_run.orders_irregular,
            )
        except Exception as exc:
            job_run.status = "failed"
            job_run.error_message = str(exc)
            write_runtime_event(
                "execution_failed",
                "Execução da rotina falhou.",
                level="ERROR",
                trigger_type=trigger_type,
                detail=str(exc),
            )
        finally:
            job_run.finished_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(job_run)

        return job_run
