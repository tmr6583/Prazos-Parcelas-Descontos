from __future__ import annotations

import secrets
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
            raise ValueError("Informe o Client ID da integracao Olist.")
        if not redirect_uri.strip():
            raise ValueError("Informe a Redirect URI da integracao Olist.")
        if not auth_url.strip():
            raise ValueError("Informe a URL de autorizacao OAuth da Olist.")
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
        write_runtime_event(
            "olist_settings_updated",
            "Configuracao da integracao Olist atualizada.",
            has_orders_path=bool(current.orders_path),
            redirect_uri=current.redirect_uri,
        )
        return current

    def build_authorize_url(self) -> str:
        config = self.get_connection_settings()
        if not config.auth_url or not config.client_id:
            raise ValueError("Preencha a configuracao Olist antes de iniciar a conexao.")
        if not config.client_secret:
            raise ValueError("Informe o Client Secret da integracao Olist antes de conectar.")
        if not config.redirect_uri:
            raise ValueError("Informe a Redirect URI da integracao Olist antes de conectar.")

        state = secrets.token_urlsafe(24)
        config.oauth_state = state
        config.oauth_state_expires_at = datetime.now(UTC) + timedelta(minutes=OAUTH_STATE_DURATION_MINUTES)
        config.last_connect_attempt_at = datetime.now(UTC)
        self.db.commit()
        write_runtime_event(
            "olist_authorization_requested",
            "Autorizacao OAuth da Olist iniciada.",
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
            raise ValueError("Configure a URL de token OAuth para concluir a autenticacao.")
        if not code.strip():
            raise ValueError("O callback Olist nao trouxe um codigo de autorizacao valido.")
        if not state or not config.oauth_state or state != config.oauth_state:
            raise ValueError("O callback Olist retornou com state invalido.")
        if config.oauth_state_expires_at and self._normalize_datetime(config.oauth_state_expires_at) < datetime.now(UTC):
            raise ValueError("A autorizacao OAuth da Olist expirou. Gere uma nova tentativa.")

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
            return refreshed.access_token
        return token.access_token

    def refresh_token(self, refresh_token: str | None = None, *, mode: str = "manual") -> OAuthToken:
        config = self.get_connection_settings()
        current_token = self.db.scalar(select(OAuthToken).where(OAuthToken.provider == "olist"))
        refresh_value = (refresh_token or (current_token.refresh_token if current_token else "")).strip()
        if not refresh_value:
            raise ValueError("Ainda nao existe refresh token persistido para a Olist.")
        if not config.token_url:
            raise ValueError("Configure a URL de token OAuth para renovar a conexao.")

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
            mode=mode,
            expires_at=token.expires_at.isoformat() if token.expires_at else None,
        )
        return token

    def fetch_orders(self, issued_from: datetime) -> list[OrderData]:
        token = self.get_valid_token()
        config = self.get_connection_settings()
        if token is None or not config.orders_path:
            return []

        url = f"{config.api_base_url.rstrip('/')}/{config.orders_path.lstrip('/')}"
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
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
