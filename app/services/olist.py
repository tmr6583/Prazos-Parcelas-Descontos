from __future__ import annotations

import secrets
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import OAuthToken, OlistConnectionSetting
from app.services.policy import OrderData, PolicyEngine
from app.services.runtime_log import write_runtime_event


OAUTH_STATE_DURATION_MINUTES = 10
DEFAULT_API_BASE_URL = "https://api.tiny.com.br/public-api/v3/"
DEFAULT_ORDERS_PATH = "pedidos"
DEFAULT_PAGE_SIZE = 100
LEGACY_API_BASE_URLS = {"https://erp.olist.com", "https://erp.olist.com/"}
OLIST_HTTP_RETRY_ATTEMPTS = 4
OLIST_HTTP_RETRY_BACKOFF_SECONDS = 1.0


class OlistService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def bootstrap_settings(self) -> OlistConnectionSetting:
        current = self.db.get(OlistConnectionSetting, 1)
        if current is not None:
            return current

        current = OlistConnectionSetting(
            id=1,
            client_id=self.settings.olist_client_id,
            client_secret=self.settings.olist_client_secret,
            redirect_uri=self.settings.olist_redirect_uri,
            auth_url=self.settings.olist_auth_url,
            token_url=self.settings.olist_token_url,
            api_base_url=self.settings.olist_base_url,
            orders_path=self.settings.olist_orders_path,
        )
        self.db.add(current)
        self.db.commit()
        self.db.refresh(current)
        return current

    def get_connection_settings(self) -> OlistConnectionSetting:
        current = self.db.get(OlistConnectionSetting, 1)
        if current is None:
            return self.bootstrap_settings()
        updated = False
        if not current.api_base_url.strip() or current.api_base_url.strip() in LEGACY_API_BASE_URLS:
            current.api_base_url = DEFAULT_API_BASE_URL
            updated = True
        if not current.orders_path.strip():
            current.orders_path = DEFAULT_ORDERS_PATH
            updated = True
        if updated:
            self.db.commit()
            self.db.refresh(current)
        return current

    def update_connection_settings(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        auth_url: str,
        token_url: str,
        api_base_url: str,
        orders_path: str,
    ) -> OlistConnectionSetting:
        current = self.get_connection_settings()
        if not client_id.strip():
            raise ValueError("Informe o ID do cliente da integração Olist.")
        if not redirect_uri.strip():
            raise ValueError("Informe a URI de redirecionamento da integração Olist.")
        if not auth_url.strip():
            raise ValueError("Informe a URL de autorização OAuth da Olist.")
        if not token_url.strip():
            raise ValueError("Informe a URL de token OAuth da Olist.")
        if not api_base_url.strip():
            raise ValueError("Informe a URL base da API Olist.")

        credentials_changed = False
        if current.client_id.strip() != client_id.strip():
            credentials_changed = True
        if current.redirect_uri.strip() != redirect_uri.strip():
            credentials_changed = True
        if current.auth_url.strip() != auth_url.strip():
            credentials_changed = True
        if current.token_url.strip() != token_url.strip():
            credentials_changed = True

        current.client_id = client_id.strip()
        if client_secret.strip():
            current.client_secret = client_secret.strip()
            credentials_changed = True
        current.redirect_uri = redirect_uri.strip()
        current.auth_url = auth_url.strip()
        current.token_url = token_url.strip()
        current.api_base_url = api_base_url.strip()
        current.orders_path = orders_path.strip()
        current.oauth_state = None
        current.oauth_state_expires_at = None
        if credentials_changed:
            self.clear_tokens(commit=False)
        self.db.commit()
        self.db.refresh(current)
        orders_path_value = self._resolve_orders_path(current.orders_path)
        write_runtime_event(
            "olist_settings_updated",
            (
                "Configuração da integração Olist atualizada. "
                f"Base da API: {current.api_base_url} | Endpoint de pedidos: {orders_path_value}."
            ),
            has_orders_path=bool(current.orders_path),
            redirect_uri=current.redirect_uri,
        )
        if credentials_changed:
            write_runtime_event(
                "olist_credentials_changed",
                "Credenciais da integração Olist alteradas. O token anterior foi invalidado.",
                level="WARNING",
            )
        return current

    def build_authorize_url(self) -> str:
        config = self.get_connection_settings()
        if not config.auth_url or not config.client_id:
            raise ValueError("Preencha a configuração da Olist antes de iniciar a conexão.")
        if not config.client_secret:
            raise ValueError("Informe o segredo do cliente da integração Olist antes de conectar.")
        if not config.redirect_uri:
            raise ValueError("Informe a URI de redirecionamento da integração Olist antes de conectar.")

        state = secrets.token_urlsafe(24)
        config.oauth_state = state
        config.oauth_state_expires_at = datetime.now(UTC) + timedelta(minutes=OAUTH_STATE_DURATION_MINUTES)
        config.last_connect_attempt_at = datetime.now(UTC)
        self.db.commit()
        write_runtime_event(
            "olist_authorization_requested",
            "Autorização OAuth da Olist iniciada.",
            redirect_uri=config.redirect_uri,
            expires_at=config.oauth_state_expires_at.isoformat() if config.oauth_state_expires_at else None,
        )

        query = urlencode(
            {
                "response_type": "code",
                "client_id": config.client_id,
                "redirect_uri": config.redirect_uri,
                "scope": "openid",
                "state": state,
            },
        )
        return f"{config.auth_url}?{query}"

    def exchange_code_for_token(self, code: str, state: str | None) -> OAuthToken:
        config = self.get_connection_settings()
        if not config.token_url:
            raise ValueError("Configure a URL de token OAuth para concluir a autenticação.")
        if not code.strip():
            raise ValueError("O retorno da Olist não trouxe um código de autorização válido.")
        if not state or not config.oauth_state or state != config.oauth_state:
            raise ValueError("O retorno da Olist trouxe um parâmetro state inválido.")
        if config.oauth_state_expires_at and self._normalize_datetime(config.oauth_state_expires_at) < datetime.now(UTC):
            raise ValueError("A autorização OAuth da Olist expirou. Gere uma nova tentativa.")

        response = httpx.post(
            config.token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "code": code,
                "redirect_uri": config.redirect_uri,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()
        token = self._save_token_payload(payload)
        config.oauth_state = None
        config.oauth_state_expires_at = None
        config.last_callback_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(config)
        write_runtime_event(
            "olist_authorized",
            "Olist conectada com sucesso.",
            expires_at=token.expires_at.isoformat() if token.expires_at else None,
        )
        return token

    def get_valid_token(self) -> str | None:
        token = self.db.scalar(select(OAuthToken).where(OAuthToken.provider == "olist"))
        if token is None:
            return None

        expires_at = self._normalize_datetime(token.expires_at)
        if expires_at and expires_at <= datetime.now(UTC) + timedelta(minutes=5):
            refreshed = self.refresh_token(token.refresh_token, mode="automatico")
            # "automático" é mantido apenas na mensagem de log; aqui o modo é um valor técnico.
            return refreshed.access_token
        return token.access_token

    def refresh_token(self, refresh_token: str | None = None, *, mode: str = "manual") -> OAuthToken:
        config = self.get_connection_settings()
        current_token = self.db.scalar(select(OAuthToken).where(OAuthToken.provider == "olist"))
        refresh_value = (refresh_token or (current_token.refresh_token if current_token else "")).strip()
        if not refresh_value:
            raise ValueError("Ainda não existe refresh token persistido para a Olist.")
        if not config.token_url:
            raise ValueError("Configure a URL de token OAuth para renovar a conexão.")

        response = httpx.post(
            config.token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "refresh_token": refresh_value,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()
        token = self._save_token_payload(payload)
        write_runtime_event(
            "olist_token_renewed",
            "Token Olist renovado com sucesso.",
            mode="automático" if mode == "automatico" else mode,
            expires_at=token.expires_at.isoformat() if token.expires_at else None,
        )
        return token

    def fetch_orders(self, issued_from: datetime) -> list[OrderData]:
        token = self.get_valid_token()
        config = self.get_connection_settings()
        if token is None:
            write_runtime_event(
                "olist_orders_query_skipped",
                "Consulta à Olist não executada porque não há token válido conectado.",
                level="WARNING",
            )
            return []

        orders_path = self._resolve_orders_path(config.orders_path)
        list_url = f"{config.api_base_url.rstrip('/')}/{orders_path.lstrip('/')}"
        write_runtime_event(
            "olist_orders_query_started",
            (
                "Consulta de pedidos na Olist iniciada. "
                f"Período inicial: {issued_from.date().isoformat()} | Endpoint: {orders_path}."
            ),
            api_base_url=config.api_base_url,
            orders_path=orders_path,
        )
        items = self._fetch_order_summaries(list_url, token, issued_from)

        normalized_orders: list[OrderData] = []
        for item in items:
            if not isinstance(item, dict):
                continue

            order_payload = item
            order_id = item.get("id")
            if order_id is not None:
                try:
                    order_payload = self._merge_order_payloads(
                        item,
                        self._fetch_order_detail(list_url, token, str(order_id)),
                    )
                except httpx.HTTPError as exc:
                    write_runtime_event(
                        "olist_order_detail_failed",
                        "Não foi possível obter o detalhe do pedido na Olist.",
                        level="WARNING",
                        order_id=str(order_id),
                        detail=str(exc),
                    )
                    self.record_last_error(str(exc))

            normalized_orders.append(self.normalize_order(order_payload))

        write_runtime_event(
            "olist_orders_query_finished",
            f"Consulta de pedidos na Olist concluída com {len(normalized_orders)} pedidos processados.",
            orders_count=len(normalized_orders),
            orders_path=orders_path,
        )
        return normalized_orders

    @staticmethod
    def normalize_order(payload: dict[str, Any]) -> OrderData:
        payload = OlistService._unwrap_order_payload(payload)
        customer = payload.get("cliente")
        payment = payload.get("pagamento")
        installments = []
        if isinstance(payment, dict) and isinstance(payment.get("parcelas"), list):
            installments = [item for item in payment.get("parcelas", []) if isinstance(item, dict)]
        elif isinstance(payload.get("parcelas"), list):
            installments = [item for item in payload.get("parcelas", []) if isinstance(item, dict)]

        gross_amount = Decimal(
            str(
                payload.get("valorTotalPedido")
                or payload.get("valorTotal")
                or payload.get("valor")
                or payload.get("valorTotalProdutos")
                or 0
            ),
        )
        discount_amount = Decimal(str(payload.get("desconto") or payload.get("valorDesconto") or 0))
        discount_percent = payload.get("percentualDesconto")
        if discount_percent is None:
            discount_percent = PolicyEngine.calculate_discount_percent(gross_amount, discount_amount)
        else:
            discount_percent = Decimal(str(discount_percent))

        installments_count = (
            len(installments)
            if installments
            else int(payload.get("parcelas") or payload.get("numeroParcelas") or 1)
        )
        prazo_total_dias = (
            max(int(item.get("dias") or 0) for item in installments)
            if installments
            else int(payload.get("prazoTotalDias") or payload.get("diasPrazo") or 0)
        )
        customer_name = (
            customer.get("nome")
            if isinstance(customer, dict)
            else payload.get("cliente") or payload.get("nomeCliente")
        )
        seller = payload.get("vendedor")
        seller_name = (
            seller.get("nome")
            if isinstance(seller, dict)
            else payload.get("nomeVendedor") or payload.get("vendedora")
        )
        payment_terms_description = (
            payment.get("condicaoPagamento") if isinstance(payment, dict) else payload.get("condicaoPagamento")
        )

        return OrderData(
            order_id=str(payload.get("id") or payload.get("pedidoId") or payload.get("codigo") or ""),
            order_number=str(payload.get("numero") or payload.get("numeroPedido") or payload.get("id") or ""),
            customer_name=customer_name,
            seller_name=seller_name,
            gross_amount=gross_amount,
            discount_amount=discount_amount,
            discount_percent=Decimal(str(discount_percent)),
            installments_count=installments_count,
            prazo_total_dias=prazo_total_dias,
            issue_date_display=OlistService._extract_issue_date_display(payload),
            payment_terms_description=payment_terms_description,
            raw_payload=payload,
        )

    def _fetch_order_summaries(self, list_url: str, token: str, issued_from: datetime) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 0

        while True:
            payload = self._request_json(
                list_url,
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "dataInicial": issued_from.date().isoformat(),
                    "dataFinal": datetime.now(UTC).date().isoformat(),
                    "orderBy": "desc",
                    "limit": DEFAULT_PAGE_SIZE,
                    "offset": offset,
                },
            )

            batch = payload if isinstance(payload, list) else payload.get("itens", payload.get("items", payload.get("data", [])))
            batch = [self._unwrap_order_payload(item) for item in batch if isinstance(item, dict)]
            items.extend(batch)

            if not isinstance(payload, dict):
                break

            pagination = payload.get("paginacao") or {}
            total = pagination.get("total")
            if total is not None and (offset + len(batch)) >= int(total):
                break
            if len(batch) < DEFAULT_PAGE_SIZE:
                break
            offset += DEFAULT_PAGE_SIZE

        return items

    @staticmethod
    def _fetch_order_detail(list_url: str, token: str, order_id: str) -> dict[str, Any]:
        payload = OlistService._request_json(
            f"{list_url.rstrip('/')}/{order_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        return OlistService._unwrap_order_payload(payload) if isinstance(payload, dict) else {}

    @staticmethod
    def _unwrap_order_payload(payload: dict[str, Any]) -> dict[str, Any]:
        wrapped_payload = payload.get("pedido")
        if not isinstance(wrapped_payload, dict):
            return payload

        merged_payload = dict(payload)
        merged_payload.pop("pedido", None)
        return OlistService._merge_order_payloads(merged_payload, wrapped_payload)

    @staticmethod
    def _merge_order_payloads(summary_payload: dict[str, Any], detail_payload: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = dict(summary_payload)
        for key, value in detail_payload.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = OlistService._merge_order_payloads(merged[key], value)
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _extract_issue_date_display(payload: dict[str, Any]) -> str:
        candidate_paths = (
            ("dataCriacao",),
            ("dataEmissao",),
            ("emissao",),
            ("dataFaturamento",),
            ("dataPedido",),
            ("dataVenda",),
            ("data",),
            ("pedido", "dataCriacao"),
            ("pedido", "dataEmissao"),
            ("pedido", "emissao"),
            ("pedido", "dataFaturamento"),
            ("pedido", "dataPedido"),
            ("pedido", "dataVenda"),
        )

        for path in candidate_paths:
            current: Any = payload
            for key in path:
                if not isinstance(current, dict):
                    current = None
                    break
                current = current.get(key)

            if current not in {None, ""}:
                return str(current)

        return ""

    def _save_token_payload(self, payload: dict[str, Any]) -> OAuthToken:
        token = self.db.scalar(select(OAuthToken).where(OAuthToken.provider == "olist"))
        expires_at = None
        expires_in = payload.get("expires_in")
        if expires_in:
            expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in))

        if token is None:
            token = OAuthToken(provider="olist", access_token="", refresh_token="")
            self.db.add(token)

        token.access_token = payload.get("access_token", "")
        token.refresh_token = payload.get("refresh_token", token.refresh_token)
        token.expires_at = expires_at
        token.scope = payload.get("scope")
        token.token_type = payload.get("token_type")
        token.last_error = None
        self.db.commit()
        self.db.refresh(token)
        return token

    def clear_tokens(self, *, commit: bool = True) -> None:
        token = self.db.scalar(select(OAuthToken).where(OAuthToken.provider == "olist"))
        if token is None:
            return
        token.access_token = ""
        token.refresh_token = ""
        token.expires_at = None
        token.scope = None
        token.token_type = None
        token.last_error = None
        if commit:
            self.db.commit()

    def record_last_error(self, message: str) -> None:
        token = self.db.scalar(select(OAuthToken).where(OAuthToken.provider == "olist"))
        if token is None:
            token = OAuthToken(provider="olist", access_token="", refresh_token="")
            self.db.add(token)
        token.last_error = message[:1000]
        self.db.commit()

    @staticmethod
    def _resolve_orders_path(orders_path: str | None) -> str:
        normalized = (orders_path or "").strip().strip("/")
        return normalized or DEFAULT_ORDERS_PATH

    @staticmethod
    def _request_json(
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> Any:
        last_exception: httpx.HTTPError | None = None

        for attempt in range(1, OLIST_HTTP_RETRY_ATTEMPTS + 1):
            try:
                response = httpx.get(url, headers=headers, params=params, timeout=timeout)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                last_exception = exc
                status_code = exc.response.status_code
                if status_code not in {429, 500, 502, 503, 504} or attempt >= OLIST_HTTP_RETRY_ATTEMPTS:
                    raise

                retry_after = exc.response.headers.get("Retry-After")
                try:
                    delay_seconds = float(retry_after) if retry_after else (OLIST_HTTP_RETRY_BACKOFF_SECONDS * attempt)
                except ValueError:
                    delay_seconds = OLIST_HTTP_RETRY_BACKOFF_SECONDS * attempt

                write_runtime_event(
                    "olist_http_retry",
                    "Nova tentativa de consulta à Olist agendada após erro temporário.",
                    level="WARNING",
                    url=url,
                    status_code=status_code,
                    attempt=attempt,
                    delay_seconds=delay_seconds,
                )
                time.sleep(delay_seconds)
            except httpx.HTTPError as exc:
                last_exception = exc
                if attempt >= OLIST_HTTP_RETRY_ATTEMPTS:
                    raise
                time.sleep(OLIST_HTTP_RETRY_BACKOFF_SECONDS * attempt)

        if last_exception is not None:
            raise last_exception
        raise RuntimeError("Falha inesperada ao consultar a Olist.")

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
