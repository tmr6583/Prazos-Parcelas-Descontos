from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import OAuthToken
from app.services.policy import OrderData, PolicyEngine


class OlistService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def build_authorize_url(self) -> str:
        if not self.settings.olist_auth_url or not self.settings.olist_client_id:
            raise ValueError("Configure OLIST_AUTH_URL e OLIST_CLIENT_ID para iniciar a conexao.")

        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.settings.olist_client_id,
                "redirect_uri": self.settings.olist_redirect_uri,
                "scope": "openid",
            },
        )
        return f"{self.settings.olist_auth_url}?{query}"

    def exchange_code_for_token(self, code: str) -> OAuthToken:
        if not self.settings.olist_token_url:
            raise ValueError("Configure OLIST_TOKEN_URL para concluir a autenticacao.")

        response = httpx.post(
            self.settings.olist_token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "client_id": self.settings.olist_client_id,
                "client_secret": self.settings.olist_client_secret,
                "code": code,
                "redirect_uri": self.settings.olist_redirect_uri,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()
        return self._save_token_payload(payload)

    def get_valid_token(self) -> str | None:
        token = self.db.scalar(select(OAuthToken).where(OAuthToken.provider == "olist"))
        if token is None:
            return None

        if token.expires_at and token.expires_at <= datetime.now(UTC) + timedelta(minutes=5):
            refreshed = self.refresh_token(token.refresh_token)
            return refreshed.access_token
        return token.access_token

    def refresh_token(self, refresh_token: str) -> OAuthToken:
        response = httpx.post(
            self.settings.olist_token_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "client_id": self.settings.olist_client_id,
                "client_secret": self.settings.olist_client_secret,
                "refresh_token": refresh_token,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()
        return self._save_token_payload(payload)

    def fetch_orders(self, issued_from: datetime) -> list[OrderData]:
        token = self.get_valid_token()
        if token is None or not self.settings.olist_orders_path:
            return []

        url = f"{self.settings.olist_base_url.rstrip('/')}/{self.settings.olist_orders_path.lstrip('/')}"
        response = httpx.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params={"dataInicialEmissao": issued_from.date().isoformat()},
            timeout=30.0,
        )
        response.raise_for_status()
        payload = response.json()
        items = payload if isinstance(payload, list) else payload.get("items", payload.get("data", []))
        return [self.normalize_order(item) for item in items if isinstance(item, dict)]

    @staticmethod
    def normalize_order(payload: dict[str, Any]) -> OrderData:
        gross_amount = Decimal(str(payload.get("valor") or payload.get("valorTotal") or 0))
        discount_amount = Decimal(str(payload.get("desconto") or payload.get("valorDesconto") or 0))
        discount_percent = payload.get("percentualDesconto")
        if discount_percent is None:
            discount_percent = PolicyEngine.calculate_discount_percent(gross_amount, discount_amount)
        else:
            discount_percent = Decimal(str(discount_percent))

        installments_count = int(payload.get("parcelas") or payload.get("numeroParcelas") or 1)
        prazo_total_dias = int(payload.get("prazoTotalDias") or payload.get("diasPrazo") or 0)

        return OrderData(
            order_id=str(payload.get("id") or payload.get("pedidoId") or payload.get("codigo") or ""),
            order_number=str(payload.get("numero") or payload.get("numeroPedido") or payload.get("id") or ""),
            customer_name=payload.get("cliente") or payload.get("nomeCliente"),
            gross_amount=gross_amount,
            discount_amount=discount_amount,
            discount_percent=Decimal(str(discount_percent)),
            installments_count=installments_count,
            prazo_total_dias=prazo_total_dias,
            issue_date_display=str(payload.get("dataEmissao") or payload.get("emissao") or ""),
            payment_terms_description=payload.get("condicaoPagamento"),
            raw_payload=payload,
        )

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
