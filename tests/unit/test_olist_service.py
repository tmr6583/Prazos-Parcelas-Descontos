from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.config import Settings
from app.services.olist import OlistService


class DummyResponse:
    def __init__(self, payload, *, status_code: int = 200, headers: dict[str, str] | None = None, url: str = "https://api.tiny.com.br/public-api/v3/test"):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            request = httpx.Request("GET", self.url)
            response = httpx.Response(self.status_code, request=request, json=self._payload, headers=self.headers)
            raise httpx.HTTPStatusError("erro", request=request, response=response)
        return None

    def json(self):
        return self._payload


def test_fetch_orders_uses_pedidos_endpoints_and_detail_payload(db_session, monkeypatch) -> None:
    service = OlistService(db_session, Settings())
    config = service.bootstrap_settings()
    config.api_base_url = "https://erp.olist.com/"
    config.orders_path = ""
    db_session.commit()

    monkeypatch.setattr(service, "get_valid_token", lambda: "token-valido")
    recorded_events: list[str] = []
    monkeypatch.setattr(
        "app.services.olist.write_runtime_event",
        lambda event, message, level="INFO", **context: recorded_events.append(event),
    )

    calls: list[tuple[str, dict | None]] = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append((url, params))
        assert headers == {"Authorization": "Bearer token-valido"}
        assert timeout == 30.0

        if url == "https://api.tiny.com.br/public-api/v3/pedidos":
            assert params is not None
            assert params["dataInicial"] == "2026-07-20"
            assert params["orderBy"] == "desc"
            assert params["limit"] == 100
            assert params["offset"] == 0
            return DummyResponse(
                {
                    "itens": [{"id": 987, "numeroPedido": 12345}],
                    "paginacao": {"limit": 100, "offset": 0, "total": 1},
                },
            )

        if url == "https://api.tiny.com.br/public-api/v3/pedidos/987":
            assert params is None
            return DummyResponse(
                {
                    "id": 987,
                    "numeroPedido": 12345,
                    "dataCriacao": "2026-07-25",
                    "valorTotalPedido": 1500.24,
                    "valorDesconto": 180.03,
                    "cliente": {"nome": "Cliente Teste"},
                    "pagamento": {
                        "condicaoPagamento": "3x 14/21/28",
                        "parcelas": [
                            {"dias": 14, "valor": 500.08},
                            {"dias": 21, "valor": 500.08},
                            {"dias": 28, "valor": 500.08},
                        ],
                    },
                },
            )

        raise AssertionError(f"URL inesperada: {url}")

    monkeypatch.setattr("app.services.olist.httpx.get", fake_get)

    orders = service.fetch_orders(datetime(2026, 7, 20, 0, 0, 0, tzinfo=UTC))

    assert len(orders) == 1
    order = orders[0]
    assert order.order_id == "987"
    assert order.order_number == "12345"
    assert order.customer_name == "Cliente Teste"
    assert order.gross_amount == Decimal("1500.24")
    assert order.discount_amount == Decimal("180.03")
    assert order.discount_percent == Decimal("12.00")
    assert order.installments_count == 3
    assert order.prazo_total_dias == 28
    assert order.seller_name is None
    assert order.payment_terms_description == "3x 14/21/28"
    assert calls[0][0] == "https://api.tiny.com.br/public-api/v3/pedidos"
    assert calls[0][1]["dataInicial"] == "2026-07-20"
    assert calls[0][1]["dataFinal"] == datetime.now(UTC).date().isoformat()
    assert calls[1] == ("https://api.tiny.com.br/public-api/v3/pedidos/987", None)
    assert recorded_events == ["olist_orders_query_started", "olist_orders_query_finished"]


def test_normalize_order_uses_nested_payment_and_customer_fields(db_session) -> None:
    service = OlistService(db_session, Settings())

    order = service.normalize_order(
        {
            "id": 456,
            "numeroPedido": 2222,
            "dataCriacao": "2026-07-21",
            "valorTotalPedido": 420.00,
            "valorDesconto": 25.20,
            "cliente": {"nome": "Acme Ltda"},
            "vendedor": {"nome": "Patricia"},
            "pagamento": {
                "condicaoPagamento": "2x",
                "parcelas": [{"dias": 7, "valor": 210.00}, {"dias": 14, "valor": 210.00}],
            },
        },
    )

    assert order.customer_name == "Acme Ltda"
    assert order.seller_name == "Patricia"
    assert order.discount_percent == Decimal("6.00")
    assert order.installments_count == 2
    assert order.prazo_total_dias == 14
    assert order.payment_terms_description == "2x"
    assert order.issue_date_display == "2026-07-21"


def test_fetch_orders_preserves_sale_date_from_summary_when_detail_omits_it(db_session, monkeypatch) -> None:
    service = OlistService(db_session, Settings())
    config = service.bootstrap_settings()
    config.api_base_url = "https://api.tiny.com.br/public-api/v3/"
    config.orders_path = "pedidos"
    db_session.commit()

    monkeypatch.setattr(service, "get_valid_token", lambda: "token-valido")
    monkeypatch.setattr("app.services.olist.write_runtime_event", lambda *args, **kwargs: None)

    def fake_get(url, headers=None, params=None, timeout=None):
        if url == "https://api.tiny.com.br/public-api/v3/pedidos":
            return DummyResponse(
                {
                    "itens": [
                        {
                            "id": 321,
                            "numeroPedido": 7890,
                            "dataCriacao": "2026-07-26",
                        },
                    ],
                    "paginacao": {"limit": 100, "offset": 0, "total": 1},
                },
            )

        if url == "https://api.tiny.com.br/public-api/v3/pedidos/321":
            return DummyResponse(
                {
                    "id": 321,
                    "numeroPedido": 7890,
                    "valorTotalPedido": 980.00,
                    "valorDesconto": 49.00,
                    "cliente": {"nome": "Cliente Sem Data no Detalhe"},
                },
            )

        raise AssertionError(f"URL inesperada: {url}")

    monkeypatch.setattr("app.services.olist.httpx.get", fake_get)

    orders = service.fetch_orders(datetime(2026, 7, 20, 0, 0, 0, tzinfo=UTC))

    assert len(orders) == 1
    assert orders[0].issue_date_display == "2026-07-26"


def test_fetch_orders_unwraps_nested_pedido_payloads(db_session, monkeypatch) -> None:
    service = OlistService(db_session, Settings())
    config = service.bootstrap_settings()
    config.api_base_url = "https://api.tiny.com.br/public-api/v3/"
    config.orders_path = "pedidos"
    db_session.commit()

    monkeypatch.setattr(service, "get_valid_token", lambda: "token-valido")
    monkeypatch.setattr("app.services.olist.write_runtime_event", lambda *args, **kwargs: None)

    def fake_get(url, headers=None, params=None, timeout=None):
        if url == "https://api.tiny.com.br/public-api/v3/pedidos":
            return DummyResponse(
                {
                    "itens": [
                        {
                            "pedido": {
                                "id": 654,
                                "numeroPedido": 4567,
                                "dataVenda": "2026-07-24",
                            },
                        },
                    ],
                    "paginacao": {"limit": 100, "offset": 0, "total": 1},
                },
            )

        if url == "https://api.tiny.com.br/public-api/v3/pedidos/654":
            return DummyResponse(
                {
                    "pedido": {
                        "id": 654,
                        "numeroPedido": 4567,
                        "valorTotalPedido": 1100.00,
                        "valorDesconto": 55.00,
                        "cliente": {"nome": "Cliente Encapsulado"},
                    },
                },
            )

        raise AssertionError(f"URL inesperada: {url}")

    monkeypatch.setattr("app.services.olist.httpx.get", fake_get)

    orders = service.fetch_orders(datetime(2026, 7, 20, 0, 0, 0, tzinfo=UTC))

    assert len(orders) == 1
    assert orders[0].order_id == "654"
    assert orders[0].customer_name == "Cliente Encapsulado"
    assert orders[0].issue_date_display == "2026-07-24"
    assert orders[0].gross_amount == Decimal("1100.0")
    assert orders[0].discount_amount == Decimal("55.0")
    assert orders[0].discount_percent == Decimal("5.00")


def test_get_connection_settings_migrates_legacy_base_url_and_blank_orders_path(db_session) -> None:
    service = OlistService(db_session, Settings())
    config = service.bootstrap_settings()
    config.api_base_url = "https://erp.olist.com/"
    config.orders_path = ""
    db_session.commit()

    normalized = service.get_connection_settings()

    assert normalized.api_base_url == "https://api.tiny.com.br/public-api/v3/"
    assert normalized.orders_path == "pedidos"


def test_request_json_retries_on_rate_limit(db_session, monkeypatch) -> None:
    service = OlistService(db_session, Settings())
    attempts = {"count": 0}

    def fake_get(url, headers=None, params=None, timeout=None):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return DummyResponse(
                {"mensagem": "rate limited"},
                status_code=429,
                headers={"Retry-After": "0"},
                url=url,
            )
        return DummyResponse({"ok": True}, url=url)

    monkeypatch.setattr("app.services.olist.httpx.get", fake_get)
    monkeypatch.setattr("app.services.olist.time.sleep", lambda seconds: None)

    payload = service._request_json("https://api.tiny.com.br/public-api/v3/pedidos", headers={"Authorization": "Bearer token"})

    assert payload == {"ok": True}
    assert attempts["count"] == 2
