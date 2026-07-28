from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import tomllib
from pydantic import BaseModel, ConfigDict, EmailStr, Field


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    app_name: str = "Sistema de Alertas ERP"
    port: int = 3600
    timezone: str = "America/Sao_Paulo"
    database_url: str = "sqlite:///./data/app.db"
    session_secret: str = "change-me"
    log_level: str = "INFO"

    frequency_minutes: int = 30
    dias_retroativos_emissao_default: int = 7
    resend_retry_attempts: int = 3
    resend_retry_backoff_seconds: int = 2

    olist_base_url: str = "https://api.tiny.com.br/public-api/v3/"
    olist_client_id: str = ""
    olist_client_secret: str = ""
    olist_redirect_uri: str = "http://localhost:3600/olist/callback"
    olist_auth_url: str = "https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/auth"
    olist_token_url: str = "https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/token"
    olist_orders_path: str = "pedidos"

    resend_api_key: str = ""
    resend_from_email: EmailStr = Field(default="financeiro@betinalimpeza.com.br")

    master_user_email: EmailStr = Field(default="admin@empresa.com")
    master_user_password: str = "Betin@01012023"


def _read_toml() -> dict[str, Any]:
    config_path = BASE_DIR / "app.toml"
    if not config_path.exists():
        return {}

    with config_path.open("rb") as file:
        raw = tomllib.load(file)

    return {
        "port": raw.get("app", {}).get("port", 3600),
        "timezone": raw.get("app", {}).get("timezone", "America/Sao_Paulo"),
        "database_url": raw.get("app", {}).get("database_url", "sqlite:///./data/app.db"),
        "frequency_minutes": raw.get("scheduler", {}).get("frequency_minutes", 30),
        "dias_retroativos_emissao_default": raw.get("scheduler", {}).get(
            "default_dias_retroativos_emissao",
            7,
        ),
        "resend_retry_attempts": raw.get("alerts", {}).get("retry_attempts", 3),
        "resend_retry_backoff_seconds": raw.get("alerts", {}).get("retry_backoff_seconds", 2),
        "log_level": raw.get("logging", {}).get("level", "INFO"),
    }


def _read_env() -> dict[str, Any]:
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            normalized = line.strip()
            if not normalized or normalized.startswith("#") or "=" not in normalized:
                continue
            key, value = normalized.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

    mapping: dict[str, tuple[str, Any]] = {
        "session_secret": ("APP_SESSION_SECRET", "change-me"),
        "olist_client_id": ("OLIST_CLIENT_ID", ""),
        "olist_client_secret": ("OLIST_CLIENT_SECRET", ""),
        "olist_redirect_uri": ("OLIST_REDIRECT_URI", "http://localhost:3600/olist/callback"),
        "olist_base_url": ("OLIST_BASE_URL", "https://api.tiny.com.br/public-api/v3/"),
        "olist_auth_url": (
            "OLIST_AUTH_URL",
            "https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/auth",
        ),
        "olist_token_url": (
            "OLIST_TOKEN_URL",
            "https://accounts.tiny.com.br/realms/tiny/protocol/openid-connect/token",
        ),
        "olist_orders_path": ("OLIST_ORDERS_PATH", "pedidos"),
        "resend_api_key": ("RESEND_API_KEY", ""),
        "resend_from_email": ("RESEND_FROM_EMAIL", "financeiro@betinalimpeza.com.br"),
        "master_user_email": ("MASTER_USER_EMAIL", "admin@empresa.com"),
        "master_user_password": ("MASTER_USER_PASSWORD", "Betin@01012023"),
    }
    resolved: dict[str, Any] = {}
    for field, (env_name, fallback) in mapping.items():
        resolved[field] = os.getenv(env_name, fallback)

    return resolved


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    data = {**_read_toml(), **_read_env()}
    return Settings(**data)
