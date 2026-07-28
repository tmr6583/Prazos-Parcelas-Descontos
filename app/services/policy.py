from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PolicyRule


TWO_PLACES = Decimal("0.01")


@dataclass(slots=True)
class OrderData:
    order_id: str
    order_number: str
    customer_name: str | None
    seller_name: str | None
    gross_amount: Decimal
    discount_amount: Decimal
    discount_percent: Decimal
    installments_count: int
    prazo_total_dias: int
    issue_date_display: str = ""
    payment_terms_description: str | None = None
    raw_payload: dict | None = None


@dataclass(slots=True)
class PolicyViolation:
    policy_code: str
    description: str
    max_term_days: int
    max_discount_percent: Decimal


@dataclass(slots=True)
class PolicyRuleInput:
    rule_name: str
    value_min: Decimal
    value_max: Decimal | None
    max_term_days: int
    max_discount_percent: Decimal
    requires_cash_payment: bool
    is_active: bool
    sort_order: int


DEFAULT_POLICY_RULES: tuple[PolicyRuleInput, ...] = (
    PolicyRuleInput(
        rule_name="Faixa 1",
        value_min=Decimal("0.00"),
        value_max=Decimal("150.00"),
        max_term_days=0,
        max_discount_percent=Decimal("5.00"),
        requires_cash_payment=True,
        is_active=True,
        sort_order=1,
    ),
    PolicyRuleInput(
        rule_name="Faixa 2",
        value_min=Decimal("150.01"),
        value_max=Decimal("400.00"),
        max_term_days=7,
        max_discount_percent=Decimal("5.00"),
        requires_cash_payment=False,
        is_active=True,
        sort_order=2,
    ),
    PolicyRuleInput(
        rule_name="Faixa 3",
        value_min=Decimal("400.01"),
        value_max=Decimal("1000.00"),
        max_term_days=21,
        max_discount_percent=Decimal("8.00"),
        requires_cash_payment=False,
        is_active=True,
        sort_order=3,
    ),
    PolicyRuleInput(
        rule_name="Faixa 4",
        value_min=Decimal("1000.01"),
        value_max=None,
        max_term_days=28,
        max_discount_percent=Decimal("12.00"),
        requires_cash_payment=False,
        is_active=True,
        sort_order=4,
    ),
)


class PolicyRuleService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def bootstrap_defaults(self) -> list[PolicyRule]:
        if self._current_version_group() is not None:
            return self.list_current_rules()
        return self.replace_rules(DEFAULT_POLICY_RULES)

    def list_current_rules(self) -> list[PolicyRule]:
        version_group = self._current_version_group()
        if version_group is None:
            return []
        statement = (
            select(PolicyRule)
            .where(PolicyRule.version_group == version_group)
            .order_by(PolicyRule.sort_order.asc(), PolicyRule.id.asc())
        )
        return list(self.db.scalars(statement))

    def get_current_version_group(self) -> int | None:
        return self._current_version_group()

    def replace_rules(self, rules: Iterable[PolicyRuleInput]) -> list[PolicyRule]:
        normalized_rules = list(rules)
        self._validate_rules(normalized_rules)

        version_group = (self._current_version_group() or 0) + 1
        created_rules: list[PolicyRule] = []
        for rule in normalized_rules:
            model = PolicyRule(
                rule_name=rule.rule_name.strip(),
                value_min=rule.value_min.quantize(TWO_PLACES),
                value_max=rule.value_max.quantize(TWO_PLACES) if rule.value_max is not None else None,
                max_term_days=rule.max_term_days,
                max_discount_percent=rule.max_discount_percent.quantize(TWO_PLACES),
                requires_cash_payment=rule.requires_cash_payment,
                is_active=rule.is_active,
                sort_order=rule.sort_order,
                version_group=version_group,
            )
            self.db.add(model)
            created_rules.append(model)

        self.db.commit()
        for rule in created_rules:
            self.db.refresh(rule)
        return created_rules

    def restore_defaults(self) -> list[PolicyRule]:
        return self.replace_rules(DEFAULT_POLICY_RULES)

    def _current_version_group(self) -> int | None:
        return self.db.scalar(select(func.max(PolicyRule.version_group)))

    @staticmethod
    def _validate_rules(rules: list[PolicyRuleInput]) -> None:
        if not rules:
            raise ValueError("Informe pelo menos uma regra.")

        active_rules = [rule for rule in rules if rule.is_active]
        if not active_rules:
            raise ValueError("Pelo menos uma regra deve permanecer ativa.")

        sorted_rules = sorted(active_rules, key=lambda item: (item.value_min, item.sort_order))
        previous_max: Decimal | None = None
        for index, rule in enumerate(sorted_rules, start=1):
            if not rule.rule_name.strip():
                raise ValueError(f"A regra {index} precisa de um nome.")
            if rule.value_min < Decimal("0.00"):
                raise ValueError(f"A regra {rule.rule_name} possui valor inicial inválido.")
            if rule.value_max is not None and rule.value_max < rule.value_min:
                raise ValueError(f"A regra {rule.rule_name} possui faixa final menor que a inicial.")
            if rule.max_term_days < 0:
                raise ValueError(f"A regra {rule.rule_name} possui prazo máximo inválido.")
            if rule.max_discount_percent < Decimal("0.00"):
                raise ValueError(f"A regra {rule.rule_name} possui desconto máximo inválido.")
            if previous_max is not None and rule.value_min <= previous_max:
                raise ValueError("Existem faixas de valor sobrepostas.")
            if previous_max is not None and rule.value_min > (previous_max + Decimal("0.01")):
                raise ValueError("Existem lacunas entre as faixas ativas.")
            previous_max = rule.value_max

        if sorted_rules[-1].value_max is not None:
            raise ValueError("A última faixa ativa deve ficar aberta para valores acima do limite.")


class PolicyEngine:
    def __init__(self, rules: Iterable[PolicyRule]) -> None:
        self.rules = sorted(
            [rule for rule in rules if rule.is_active],
            key=lambda item: (item.sort_order, item.value_min),
        )

    def evaluate(self, order: OrderData) -> list[PolicyViolation]:
        rule = self._resolve_rule(order.gross_amount)
        if rule is None:
            return [
                PolicyViolation(
                    policy_code="SEM_POLITICA",
                    description="Pedido sem política comercial correspondente.",
                    max_term_days=0,
                    max_discount_percent=Decimal("0.00"),
                ),
            ]

        max_term_days = int(rule.max_term_days)
        max_discount_percent = Decimal(str(rule.max_discount_percent)).quantize(TWO_PLACES)
        violations: list[PolicyViolation] = []

        if rule.requires_cash_payment:
            if order.installments_count > 1 or order.prazo_total_dias > 0 or order.discount_percent > max_discount_percent:
                violations.append(
                    PolicyViolation(
                        policy_code=self._policy_code(rule.sort_order),
                        description=(
                            f"{rule.rule_name} exige pagamento à vista e desconto máximo de "
                            f"{max_discount_percent:.2f}%."
                        ),
                        max_term_days=0,
                        max_discount_percent=max_discount_percent,
                    ),
                )
        elif order.prazo_total_dias > max_term_days or order.discount_percent > max_discount_percent:
            violations.append(
                PolicyViolation(
                    policy_code=self._policy_code(rule.sort_order),
                    description=(
                        f"{rule.rule_name} permite até {max_term_days} dias e desconto máximo de "
                        f"{max_discount_percent:.2f}%."
                    ),
                    max_term_days=max_term_days,
                    max_discount_percent=max_discount_percent,
                ),
            )

        if order.installments_count > 1 and order.prazo_total_dias > max_term_days:
            violations.append(
                PolicyViolation(
                    policy_code="PARCELAMENTO_PRAZO",
                    description="Parcelamentos não podem ultrapassar o prazo máximo da faixa.",
                    max_term_days=max_term_days,
                    max_discount_percent=max_discount_percent,
                ),
            )

        return violations

    @staticmethod
    def calculate_discount_percent(gross_amount: Decimal, discount_amount: Decimal) -> Decimal:
        if gross_amount <= 0:
            return Decimal("0.00")
        return ((discount_amount / gross_amount) * Decimal("100")).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    def _resolve_rule(self, gross_amount: Decimal) -> PolicyRule | None:
        for rule in self.rules:
            upper_bound = Decimal(str(rule.value_max)) if rule.value_max is not None else None
            lower_bound = Decimal(str(rule.value_min))
            if upper_bound is None and gross_amount >= lower_bound:
                return rule
            if upper_bound is not None and lower_bound <= gross_amount <= upper_bound:
                return rule
        return None

    @staticmethod
    def _policy_code(sort_order: int) -> str:
        return f"FAIXA_{sort_order}"
