from __future__ import annotations

from decimal import Decimal

import pytest

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
