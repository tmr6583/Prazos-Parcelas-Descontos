from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import Settings
from app.db import SessionLocal
from app.services.execution import ExecutionService
from app.services.settings import SettingsService


class SchedulerService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.scheduler = BackgroundScheduler(timezone=settings.timezone)
        self.job_id = "olist-policy-check"

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()
        self.reschedule()

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def reschedule(self) -> None:
        with SessionLocal() as db:
            config = SettingsService(db).get()

        trigger = IntervalTrigger(minutes=config.frequency_minutes, timezone=config.timezone)
        if self.scheduler.get_job(self.job_id):
            self.scheduler.reschedule_job(self.job_id, trigger=trigger)
            return

        self.scheduler.add_job(
            func=self._run_scheduled_job,
            id=self.job_id,
            trigger=trigger,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    def _run_scheduled_job(self) -> None:
        with SessionLocal() as db:
            ExecutionService(db, self.settings).run(trigger_type="scheduled")
