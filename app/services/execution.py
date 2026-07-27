from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import JobRun
from app.services.admin import AdminService
from app.services.alerts import AlertService
from app.services.olist import OlistService
from app.services.policy import PolicyEngine, PolicyRuleService
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
            raise RuntimeError("Nenhuma politica comercial ativa foi configurada.")

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

        try:
            recipients = self.admin_service.list_active_recipients()
            orders = self.olist_service.fetch_orders(query_start)
            irregular_orders = 0
            policy_engine = PolicyEngine(rules)

            for order in orders:
                violations = policy_engine.evaluate(order)
                if not violations:
                    continue

                irregular_orders += 1
                logical_window = query_start.date().isoformat()
                for violation in violations:
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

            job_run.status = "success"
            job_run.orders_evaluated = len(orders)
            job_run.orders_irregular = irregular_orders
        except Exception as exc:
            job_run.status = "failed"
            job_run.error_message = str(exc)
        finally:
            job_run.finished_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(job_run)

        return job_run
