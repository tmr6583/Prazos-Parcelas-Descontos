from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import structlog
from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session

from app.config import BASE_DIR, get_settings
from app.db import Base, engine, get_db, SessionLocal
from app.models import User
from app.services.admin import AdminService
from app.services.auth import AuthService
from app.services.execution import ExecutionService
from app.services.olist import OlistService
from app.services.policy import PolicyRuleInput, PolicyRuleService
from app.services.runtime_log import write_runtime_event
from app.services.scheduler import SchedulerService
from app.services.settings import SettingsService


def configure_logging() -> None:
    level_name = settings.log_level.upper()
    log_level = getattr(logging, level_name, logging.INFO)
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
    )


settings = get_settings()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
templates.env.filters["currency"] = lambda value: f"R$ {float(value or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
templates.env.filters["percent"] = lambda value: f"{float(value or 0):.2f}%".replace(".", ",")


def format_datetime_sp(value: object) -> str:
    if value in {None, ""}:
        return "—"

    normalized: datetime
    if isinstance(value, datetime):
        normalized = value
    else:
        try:
            normalized = datetime.fromisoformat(str(value))
        except ValueError:
            return str(value)

    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=UTC)

    return normalized.astimezone(ZoneInfo(settings.timezone)).strftime("%Y-%m-%d %H:%M:%S")


templates.env.filters["datetime_sp"] = format_datetime_sp


def _bootstrap() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        AuthService(db).bootstrap_master_user(settings)
        SettingsService(db).bootstrap(settings)
        AdminService(db).bootstrap_recipients("thiago@betinalimpeza.com.br")
        OlistService(db, settings).bootstrap_settings()
        PolicyRuleService(db).bootstrap_defaults()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    _bootstrap()
    scheduler = SchedulerService(settings)
    scheduler.start()
    app.state.scheduler = scheduler
    yield
    scheduler.shutdown()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, same_site="lax")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")
app.mount("/files", StaticFiles(directory=str(BASE_DIR / "files")), name="files")


def flash(request: Request, message: str, category: str = "info") -> None:
    request.session["flash"] = {"message": message, "category": category}


def consume_flash(request: Request) -> dict[str, str] | None:
    return request.session.pop("flash", None)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise PermissionError("Sessao ausente")
    user = AuthService(db).get_by_id(int(user_id))
    if user is None:
        request.session.clear()
        raise PermissionError("Sessao invalida")
    return user


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    try:
        return get_current_user(request, db)
    except PermissionError:
        raise


def redirect_to_login() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


def parse_decimal(value: str) -> Decimal:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("Valor numerico invalido.")

    normalized = normalized.replace("R$", "").replace("%", "").replace(" ", "")
    normalized = "".join(char for char in normalized if char.isdigit() or char in ",.-")

    if "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    elif normalized.count(".") > 1:
        parts = normalized.split(".")
        normalized = "".join(parts[:-1]) + "." + parts[-1]

    try:
        return Decimal(normalized)
    except (InvalidOperation, AttributeError):
        raise ValueError("Valor numerico invalido.") from None


def render_dashboard(request: Request, db: Session, user: User):
    admin_service = AdminService(db)
    settings_service = SettingsService(db)
    policy_service = PolicyRuleService(db)
    olist_service = OlistService(db, settings)
    config = settings_service.get()
    runs = admin_service.list_recent_runs()
    alerts = admin_service.list_recent_alerts()
    recipients = admin_service.list_recipients()
    users = AuthService(db).list_users()
    policies = policy_service.list_current_rules()
    token = admin_service.get_olist_token()
    olist_config = olist_service.get_connection_settings()
    online_log_lines = admin_service.get_online_log_lines(limit=10)

    last_run = runs[0] if runs else None
    last_irregular_alert = admin_service.get_last_irregular_alert_for_run(last_run.id if last_run else None)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "flash": consume_flash(request),
            "config": config,
            "users": users,
            "recipients": recipients,
            "policies": policies,
            "runs": runs,
            "alerts": alerts,
            "last_run": last_run,
            "last_irregular_alert": last_irregular_alert,
            "olist_token": token,
            "olist_config": olist_config,
            "online_log_lines": online_log_lines,
            "logo_href": "/files/Logo_Azul.webp",
        },
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(BASE_DIR / "files" / "Logo_Azul.webp", media_type="image/webp")


@app.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    try:
        get_current_user(request, db)
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    except PermissionError:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"request": request, "flash": consume_flash(request), "logo_href": "/files/Logo_Azul.webp"},
        )


@app.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    email = str(form.get("email", "")).strip().lower()
    password = str(form.get("password", ""))
    user = AuthService(db).authenticate(email, password)
    if user is None:
        flash(request, "Credenciais invalidas.", "error")
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    request.session["user_id"] = user.id
    flash(request, "Login realizado com sucesso.", "success")
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user(request, db)
    except PermissionError:
        return redirect_to_login()
    return render_dashboard(request, db, user)


@app.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user(request, db)
    except PermissionError:
        return redirect_to_login()
    return render_dashboard(request, db, user)


@app.post("/settings")
async def update_settings(request: Request, db: Session = Depends(get_db)):
    try:
        get_current_user(request, db)
    except PermissionError:
        return redirect_to_login()

    form = await request.form()
    try:
        SettingsService(db).update(
            frequency_minutes=int(str(form.get("frequency_minutes", "0"))),
            dias_retroativos_emissao=int(str(form.get("dias_retroativos_emissao", "0"))),
            resend_from_email=str(form.get("resend_from_email", "")).strip().lower(),
        )
        app.state.scheduler.reschedule()
        flash(request, "Configuracoes atualizadas.", "success")
    except Exception as exc:
        flash(request, str(exc), "error")
    return RedirectResponse(url="/#settings", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/users")
async def create_user(request: Request, db: Session = Depends(get_db)):
    try:
        get_current_user(request, db)
    except PermissionError:
        return redirect_to_login()

    form = await request.form()
    try:
        AuthService(db).create_user(
            email=str(form.get("email", "")),
            password=str(form.get("password", "")),
        )
        flash(request, "Usuario criado com sucesso.", "success")
    except Exception as exc:
        flash(request, str(exc), "error")
    return RedirectResponse(url="/#users", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/users/{user_id}/delete")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        current_user = get_current_user(request, db)
    except PermissionError:
        return redirect_to_login()

    if current_user.id == user_id:
        flash(request, "Nao e permitido excluir a propria sessao.", "error")
        return RedirectResponse(url="/#users", status_code=status.HTTP_303_SEE_OTHER)

    try:
        AuthService(db).soft_delete_user(user_id)
        flash(request, "Usuario excluido com sucesso.", "success")
    except Exception as exc:
        flash(request, str(exc), "error")
    return RedirectResponse(url="/#users", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/users/{user_id}/reset-password")
async def reset_password(user_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        get_current_user(request, db)
    except PermissionError:
        return redirect_to_login()

    form = await request.form()
    try:
        AuthService(db).reset_password(user_id, str(form.get("password", "")))
        flash(request, "Senha redefinida com sucesso.", "success")
    except Exception as exc:
        flash(request, str(exc), "error")
    return RedirectResponse(url="/#users", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/recipients")
async def add_recipient(request: Request, db: Session = Depends(get_db)):
    try:
        get_current_user(request, db)
    except PermissionError:
        return redirect_to_login()

    form = await request.form()
    try:
        AdminService(db).add_recipient(str(form.get("email", "")))
        flash(request, "Destinatario salvo com sucesso.", "success")
    except Exception as exc:
        flash(request, str(exc), "error")
    return RedirectResponse(url="/#recipients", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/recipients/{recipient_id}/delete")
def delete_recipient(recipient_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        get_current_user(request, db)
    except PermissionError:
        return redirect_to_login()

    try:
        AdminService(db).soft_delete_recipient(recipient_id)
        flash(request, "Destinatario excluido com sucesso.", "success")
    except Exception as exc:
        flash(request, str(exc), "error")
    return RedirectResponse(url="/#recipients", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/recipients/{recipient_id}/toggle")
def toggle_recipient(recipient_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        get_current_user(request, db)
    except PermissionError:
        return redirect_to_login()

    try:
        AdminService(db).toggle_recipient(recipient_id)
        flash(request, "Status do destinatario atualizado.", "success")
    except Exception as exc:
        flash(request, str(exc), "error")
    return RedirectResponse(url="/#recipients", status_code=status.HTTP_303_SEE_OTHER)


def _parse_policy_form(form_data) -> list[PolicyRuleInput]:
    names = [str(value) for value in form_data.getlist("rule_name")]
    mins = [str(value) for value in form_data.getlist("value_min")]
    maxs = [str(value) for value in form_data.getlist("value_max")]
    terms = [str(value) for value in form_data.getlist("max_term_days")]
    discounts = [str(value) for value in form_data.getlist("max_discount_percent")]
    actives = {str(value) for value in form_data.getlist("is_active")}
    cashes = {str(value) for value in form_data.getlist("requires_cash_payment")}
    ids = [str(value) for value in form_data.getlist("row_id")]

    rules: list[PolicyRuleInput] = []
    for index, row_id in enumerate(ids):
        rules.append(
            PolicyRuleInput(
                rule_name=names[index],
                value_min=parse_decimal(mins[index]),
                value_max=parse_decimal(maxs[index]) if maxs[index].strip() else None,
                max_term_days=int(terms[index]),
                max_discount_percent=parse_decimal(discounts[index]),
                requires_cash_payment=row_id in cashes,
                is_active=row_id in actives,
                sort_order=index + 1,
            ),
        )
    return rules


@app.post("/policy-rules")
async def update_policy_rules(request: Request, db: Session = Depends(get_db)):
    try:
        get_current_user(request, db)
    except PermissionError:
        return redirect_to_login()

    form = await request.form()
    try:
        PolicyRuleService(db).replace_rules(_parse_policy_form(form))
        flash(request, "Politicas comerciais atualizadas.", "success")
    except Exception as exc:
        flash(request, str(exc), "error")
    return RedirectResponse(url="/#policies", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/policy-rules/restore-defaults")
def restore_policy_defaults(request: Request, db: Session = Depends(get_db)):
    try:
        get_current_user(request, db)
    except PermissionError:
        return redirect_to_login()

    PolicyRuleService(db).restore_defaults()
    flash(request, "Politicas padrao restauradas.", "success")
    return RedirectResponse(url="/#policies", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/policy-rules")
def policy_rules_page(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user(request, db)
    except PermissionError:
        return redirect_to_login()
    return render_dashboard(request, db, user)


@app.get("/olist/connect")
def olist_connect(request: Request, db: Session = Depends(get_db)):
    try:
        get_current_user(request, db)
    except PermissionError:
        return redirect_to_login()

    try:
        url = OlistService(db, settings).build_authorize_url()
        return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)
    except Exception as exc:
        OlistService(db, settings).record_last_error(str(exc))
        write_runtime_event(
            "olist_authorization_request_failed",
            "Falha ao iniciar a autorizacao OAuth da Olist.",
            level="ERROR",
            detail=str(exc),
        )
        flash(request, str(exc), "error")
        return RedirectResponse(url="/#integration", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/olist/settings")
async def update_olist_settings(request: Request, db: Session = Depends(get_db)):
    try:
        get_current_user(request, db)
    except PermissionError:
        return redirect_to_login()

    form = await request.form()
    try:
        OlistService(db, settings).update_connection_settings(
            client_id=str(form.get("client_id", "")),
            client_secret=str(form.get("client_secret", "")),
            redirect_uri=str(form.get("redirect_uri", "")),
            auth_url=str(form.get("auth_url", "")),
            token_url=str(form.get("token_url", "")),
            api_base_url=str(form.get("api_base_url", "")),
            orders_path=str(form.get("orders_path", "")),
        )
        flash(request, "Configuracao da integracao Olist atualizada.", "success")
    except Exception as exc:
        OlistService(db, settings).record_last_error(str(exc))
        write_runtime_event(
            "olist_settings_update_failed",
            "Falha ao atualizar a configuracao da integracao Olist.",
            level="ERROR",
            detail=str(exc),
        )
        flash(request, str(exc), "error")
    return RedirectResponse(url="/#integration", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/olist/callback")
def olist_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    try:
        get_current_user(request, db)
    except PermissionError:
        return redirect_to_login()

    if error:
        OlistService(db, settings).record_last_error(f"Falha na autorizacao Olist: {error}")
        write_runtime_event(
            "olist_callback_error",
            "Callback OAuth da Olist retornou erro.",
            level="ERROR",
            detail=str(error),
        )
        flash(request, f"Falha na autorizacao Olist: {error}", "error")
        return RedirectResponse(url="/#integration", status_code=status.HTTP_303_SEE_OTHER)
    if not code:
        OlistService(db, settings).record_last_error("Callback Olist recebido sem code.")
        write_runtime_event(
            "olist_callback_missing_code",
            "Callback OAuth da Olist recebido sem codigo de autorizacao.",
            level="ERROR",
        )
        flash(request, "Callback Olist recebido sem code.", "error")
        return RedirectResponse(url="/#integration", status_code=status.HTTP_303_SEE_OTHER)

    try:
        OlistService(db, settings).exchange_code_for_token(code, state)
        flash(request, "Olist conectado com sucesso.", "success")
    except Exception as exc:
        OlistService(db, settings).record_last_error(str(exc))
        write_runtime_event(
            "olist_callback_failed",
            "Falha ao concluir o callback OAuth da Olist.",
            level="ERROR",
            detail=str(exc),
        )
        flash(request, str(exc), "error")
    return RedirectResponse(url="/#integration", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/olist/renew-token")
def renew_olist_token(request: Request, db: Session = Depends(get_db)):
    try:
        get_current_user(request, db)
    except PermissionError:
        return redirect_to_login()

    try:
        OlistService(db, settings).refresh_token()
        flash(request, "Token Olist renovado com sucesso.", "success")
    except Exception as exc:
        OlistService(db, settings).record_last_error(str(exc))
        write_runtime_event(
            "olist_token_renew_failed",
            "Falha ao renovar o token da Olist.",
            level="ERROR",
            detail=str(exc),
        )
        flash(request, str(exc), "error")
    return RedirectResponse(url="/#integration", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/runs/execute")
def execute_run(request: Request, db: Session = Depends(get_db)):
    try:
        get_current_user(request, db)
    except PermissionError:
        return redirect_to_login()

    try:
        job_run = ExecutionService(db, settings).run(trigger_type="manual")
        message = (
            f"Rotina executada com status {job_run.status}. "
            f"Pedidos avaliados: {job_run.orders_evaluated}. "
            f"Irregulares: {job_run.orders_irregular}."
        )
        flash(request, message, "success" if job_run.status == "success" else "warning")
    except Exception as exc:
        flash(request, str(exc), "error")
    return RedirectResponse(url="/#runs", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/runs")
def runs_page(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user(request, db)
    except PermissionError:
        return redirect_to_login()
    return render_dashboard(request, db, user)


@app.get("/alerts")
def alerts_page(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user(request, db)
    except PermissionError:
        return redirect_to_login()
    return render_dashboard(request, db, user)
