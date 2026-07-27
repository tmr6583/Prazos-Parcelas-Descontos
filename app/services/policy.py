from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


TWO_PLACES = Decimal("0.01")


@dataclass(slots=True)
class OrderData:
    order_id: str
    order_number: str
    customer_name: str | None
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


class PolicyEngine:
    def evaluate(self, order: OrderData) -> list[PolicyViolation]:
        max_term_days, max_discount_percent, faixa_code = self._resolve_bracket(order.gross_amount)
        violations: list[PolicyViolation] = []

        if faixa_code == "FAIXA_1":
            if order.installments_count > 1 or order.prazo_total_dias > 0 or order.discount_percent > Decimal("5.00"):
                violations.append(
                    PolicyViolation(
                        policy_code="FAIXA_1",
                        description="Pedido ate R$ 150,00 deve ser a vista com desconto maximo de 5%.",
                        max_term_days=0,
                        max_discount_percent=Decimal("5.00"),
                    ),
                )
        elif faixa_code == "FAIXA_2" and (
            order.prazo_total_dias > 7 or order.discount_percent > Decimal("5.00")
        ):
            violations.append(
                PolicyViolation(
                    policy_code="FAIXA_2",
                    description="Pedido entre R$ 150,01 e R$ 400,00 permite ate 7 dias e 5% de desconto.",
                    max_term_days=7,
                    max_discount_percent=Decimal("5.00"),
                ),
            )
        elif faixa_code == "FAIXA_3" and (
            order.prazo_total_dias > 21 or order.discount_percent > Decimal("8.00")
        ):
            violations.append(
                PolicyViolation(
                    policy_code="FAIXA_3",
                    description="Pedido entre R$ 400,01 e R$ 1.000,00 permite ate 21 dias e 8% de desconto.",
                    max_term_days=21,
                    max_discount_percent=Decimal("8.00"),
                ),
            )
        elif faixa_code == "FAIXA_4" and (
            order.prazo_total_dias > 28 or order.discount_percent > Decimal("12.00")
        ):
            violations.append(
                PolicyViolation(
                    policy_code="FAIXA_4",
                    description="Pedido acima de R$ 1.000,00 permite ate 28 dias e 12% de desconto.",
                    max_term_days=28,
                    max_discount_percent=Decimal("12.00"),
                ),
            )

        if order.installments_count > 1 and order.prazo_total_dias > max_term_days:
            violations.append(
                PolicyViolation(
                    policy_code="PARCELAMENTO_PRAZO",
                    description="Parcelamentos nao podem ultrapassar o prazo maximo da faixa.",
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

    @staticmethod
    def _resolve_bracket(gross_amount: Decimal) -> tuple[int, Decimal, str]:
        if gross_amount <= Decimal("150.00"):
            return 0, Decimal("5.00"), "FAIXA_1"
        if gross_amount <= Decimal("400.00"):
            return 7, Decimal("5.00"), "FAIXA_2"
        if gross_amount <= Decimal("1000.00"):
            return 21, Decimal("8.00"), "FAIXA_3"
        return 28, Decimal("12.00"), "FAIXA_4"
