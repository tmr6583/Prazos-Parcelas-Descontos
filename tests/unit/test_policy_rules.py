from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.config import Settings
from app.services.execution import ExecutionService
from app.services.policy import (
    DEFAULT_POLICY_RULES,
    OrderData,
    PolicyEngine,
    PolicyRuleInput,
    PolicyRuleService,
)


def test_bootstrap_defaults_creates_four_ranges(db_session) -> None:
    service = PolicyRuleService(db_session)

    rules = service.bootstrap_defaults()

    assert len(rules) == 4
    assert rules[0].version_group == 1
    assert rules[-1].value_max is None


def test_policy_engine_evaluates_default_rules(db_session) -> None:
    service = PolicyRuleService(db_session)
    rules = service.bootstrap_defaults()
    engine = PolicyEngine(rules)

    regular = OrderData(
        order_id="1",
        order_number="1001",
        customer_name="Cliente A",
        seller_name="Vendedora A",
        gross_amount=Decimal("150.00"),
        discount_amount=Decimal("7.50"),
        discount_percent=Decimal("5.00"),
        installments_count=1,
        prazo_total_dias=0,
    )
    irregular = OrderData(
        order_id="2",
        order_number="1002",
        customer_name="Cliente B",
        seller_name="Vendedora B",
        gross_amount=Decimal("1000.01"),
        discount_amount=Decimal("0.00"),
        discount_percent=Decimal("12.00"),
        installments_count=2,
        prazo_total_dias=29,
    )

    assert engine.evaluate(regular) == []
    violations = engine.evaluate(irregular)
    assert {item.policy_code for item in violations} == {"FAIXA_4", "PARCELAMENTO_PRAZO"}


def test_replace_rules_rejects_overlapping_ranges(db_session) -> None:
    service = PolicyRuleService(db_session)

    with pytest.raises(ValueError, match="sobrepostas"):
        service.replace_rules(
            [
                PolicyRuleInput("Faixa A", Decimal("0.00"), Decimal("200.00"), 0, Decimal("5.00"), True, True, 1),
                PolicyRuleInput("Faixa B", Decimal("150.00"), None, 7, Decimal("5.00"), False, True, 2),
            ],
        )


def test_restore_defaults_creates_new_version_group(db_session) -> None:
    service = PolicyRuleService(db_session)
    service.bootstrap_defaults()
    customized = [
        PolicyRuleInput("Faixa custom 1", Decimal("0.00"), Decimal("99.99"), 0, Decimal("3.00"), True, True, 1),
        PolicyRuleInput("Faixa custom 2", Decimal("100.00"), None, 10, Decimal("7.00"), False, True, 2),
    ]

    new_rules = service.replace_rules(customized)
    restored_rules = service.restore_defaults()

    assert new_rules[0].version_group == 2
    assert restored_rules[0].version_group == 3
    assert [rule.rule_name for rule in restored_rules] == [item.rule_name for item in DEFAULT_POLICY_RULES]


def test_execution_service_uses_latest_saved_policy_rules(db_session, monkeypatch) -> None:
    service = PolicyRuleService(db_session)
    service.bootstrap_defaults()
    service.replace_rules(
        [
            PolicyRuleInput("Faixa 1", Decimal("0.00"), Decimal("150.00"), 0, Decimal("5.00"), True, True, 1),
            PolicyRuleInput("Faixa 2 Flex", Decimal("150.01"), Decimal("400.00"), 7, Decimal("10.00"), False, True, 2),
            PolicyRuleInput("Faixa 3", Decimal("400.01"), Decimal("1000.00"), 21, Decimal("8.00"), False, True, 3),
            PolicyRuleInput("Faixa 4", Decimal("1000.01"), None, 28, Decimal("12.00"), False, True, 4),
        ],
    )

    execution_service = ExecutionService(db_session, Settings())
    monkeypatch.setattr(
        execution_service.settings_service,
        "get",
        lambda: type("Cfg", (), {"timezone": "America/Sao_Paulo", "dias_retroativos_emissao": 7})(),
    )
    monkeypatch.setattr(
        execution_service.settings_service,
        "calculate_query_start",
        lambda timezone_name, dias_retroativos_emissao: datetime(2026, 7, 27, 0, 0, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(execution_service.admin_service, "list_active_recipients", lambda: [])
    monkeypatch.setattr(
        execution_service.olist_service,
        "fetch_orders",
        lambda query_start: [
            OrderData(
                order_id="pedido-200",
                order_number="200",
                customer_name="Cliente Flex",
                seller_name="Vendedora Flex",
                gross_amount=Decimal("200.00"),
                discount_amount=Decimal("18.00"),
                discount_percent=Decimal("9.00"),
                installments_count=1,
                prazo_total_dias=7,
                issue_date_display="2026-07-27",
            ),
        ],
    )
    monkeypatch.setattr("app.services.execution.write_runtime_event", lambda *args, **kwargs: None)

    job_run = execution_service.run(trigger_type="manual")

    assert job_run.status == "success"
    assert job_run.orders_evaluated == 1
    assert job_run.orders_irregular == 0
